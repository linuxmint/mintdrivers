"""No real D-Bus or APT access: exercise the manual probe with fake transport."""
from dataclasses import replace
import unittest
from unittest.mock import Mock, patch

from PyQt6.QtCore import QObject, pyqtSignal

from manual import packagekit_mutation_probe as probe
from mainuan_drivers.backend.transactions.models import (
    PackageReference, TransactionAction, TransactionError, TransactionState,
)
from mainuan_drivers.backend.transactions.packagekit import TRANSACTION_INTERFACE
from mainuan_drivers.backend.transactions.planner import PlanningError
from test_qt_frontend import app


REF = PackageReference("hello", "hello;2.10;amd64;ubuntu")


class Harness:
    def __init__(self):
        self.snapshot = probe.Snapshot(REF)
        self.calls = []
        self.error = None
        self.unavailable = False
        self.hang = False
        self.transports = []
        self.transactions = []

    def factory(self, parent):
        transport = FakeTransport(parent, self)
        self.transactions.append(parent)
        self.transports.append(transport)
        return transport

    def mutations(self):
        return [call for call in self.calls if call[0] in ("InstallPackages", "RemovePackages")]


class FakeTransport(QObject):
    eventReceived = pyqtSignal(str, object)
    serviceLost = pyqtSignal()

    def __init__(self, parent, harness):
        super().__init__(parent)
        self.harness = harness

    def call(self, path, interface, method, arguments, callback):
        h = self.harness
        h.calls.append((method, arguments))
        if h.unavailable:
            callback([], TransactionError("service-unavailable", "Fake unavailable service"))
            return
        if method == "CreateTransaction":
            callback(["/test_%d" % len(h.calls)], None)
        elif method == "GetAll":
            callback([{"Status": 1, "Percentage": 101, "AllowCancel": True}], None)
        else:
            callback([], None)
            if method == "Resolve":
                self.eventReceived.emit("Package", [1 if h.snapshot.installed else 2, REF.package_id, "Hello"])
                self.eventReceived.emit("Finished", [1, 10])
            elif method in ("InstallPackages", "RemovePackages"):
                if h.hang:
                    return
                if h.error:
                    self.eventReceived.emit("ErrorCode", [h.error, "Fake PackageKit error"])
                    self.eventReceived.emit("Finished", [2, 10])
                    return
                installing = method == "InstallPackages"
                state = 9 if installing else 6
                self.eventReceived.emit("PropertiesChanged", [TRANSACTION_INTERFACE,
                    {"Status": state, "Percentage": 50, "AllowCancel": False}, []])
                self.eventReceived.emit("Package", [12 if installing else 13, REF.package_id, "Hello"])
                h.snapshot = probe.Snapshot(REF, REF if installing else None, installing)
                self.eventReceived.emit("Finished", [1, 10])

    def subscribe(self, path):
        return True

    def unsubscribe(self):
        pass


class MutationProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app()

    def setUp(self):
        self.uid = patch.object(probe.os, "geteuid", return_value=1000)
        self.uid.start()
        self.addCleanup(self.uid.stop)
        self.h = Harness()
        self.runner = probe.QtRunner(transport_factory=self.h.factory)
        self.confirm = Mock(return_value=True)
        self.session = probe.ProbeSession(self.runner, lambda: self.h.snapshot, self.confirm)

    def install(self):
        self.session.precheck()
        return self.session.install()

    def test_root_refused_before_bus_cache_or_prompt(self):
        with patch.object(probe.os, "geteuid", return_value=0), \
                patch.object(probe, "read_snapshot") as read, \
                patch.object(probe, "QtRunner") as runner, \
                patch.object(probe.logging, "basicConfig"), \
                self.assertLogs(probe.log, level="ERROR"):
            self.assertEqual(probe.main(["full"]), 1)
        read.assert_not_called()
        runner.assert_not_called()
        with patch.object(probe.os, "geteuid", return_value=0):
            with self.assertRaisesRegex(probe.ProbeError, "normal"):
                self.session.precheck()
        self.assertEqual(self.h.calls, [])

    def test_existing_hello_refused_without_any_transaction(self):
        self.h.snapshot = probe.Snapshot(REF, REF, True)
        with self.assertRaisesRegex(probe.ProbeError, "ja estava instalado"):
            self.session.precheck()
        self.assertEqual(self.h.calls, [])
        self.confirm.assert_not_called()

    def test_partial_installation_also_refused(self):
        self.h.snapshot = probe.Snapshot(REF, None, True)
        with self.assertRaises(probe.ProbeError):
            self.session.precheck()
        self.assertEqual(self.h.calls, [])

    def test_resolve_selects_only_exact_candidate(self):
        wrong = PackageReference("hello", "hello;1.0;amd64;other")
        other = PackageReference("other", "other;2.10;amd64;ubuntu")
        self.assertEqual(probe.select_package((wrong, other, REF), REF), REF)
        for packages in ((wrong,), (other,), (REF, replace(REF, package_id="hello;2.10;amd64;other"))):
            with self.subTest(packages=packages), self.assertRaises(probe.ProbeError):
                probe.select_package(packages, REF)

    def test_fixed_plan_source_rejects_other_packages_or_altered_plans(self):
        plans = probe.HelloPlans()
        with self.assertRaises(PlanningError):
            plans.issue(TransactionAction.INSTALL, PackageReference("other", "other;1;amd64;"))
        plan = plans.issue(TransactionAction.INSTALL, REF)
        plans.validate_plan(plan, executable=True)
        with self.assertRaises(PlanningError):
            plans.validate_plan(replace(plan, preview_only=True), executable=True)

    def test_success_uses_production_transaction_and_owns_only_after_finished(self):
        self.assertFalse(self.session.installed_by_probe)
        self.session.precheck()
        self.assertFalse(self.session.installed_by_probe)
        self.assertEqual(self.h.mutations(), [])
        with self.assertLogs(probe.log, level="INFO") as logs:
            self.assertTrue(self.session.install())
        self.assertTrue(self.session.installed_by_probe)
        self.assertIn("PASS: hello installed through PackageKit", "\n".join(logs.output))
        self.assertEqual(self.h.mutations(), [("InstallPackages", [2, [REF.package_id]])])
        self.assertTrue(all(isinstance(t, probe.PackageKitTransaction) for t in self.h.transactions))

    def test_removal_without_same_session_ownership_is_forbidden(self):
        self.h.snapshot = probe.Snapshot(REF, REF, True)
        with self.assertRaisesRegex(probe.ProbeError, "mesma execucao"):
            self.session.remove()
        self.assertEqual(self.h.calls, [])
        self.confirm.assert_not_called()

    def test_install_remove_success_conservative_flags_and_independent_confirmation(self):
        self.assertTrue(self.install())
        with self.assertLogs(probe.log, level="INFO") as logs:
            self.assertTrue(self.session.remove())
        self.assertFalse(self.session.installed_by_probe)
        self.assertFalse(self.h.snapshot.present)
        self.assertEqual(self.confirm.call_args_list, [(("install",),), (("remove",),)])
        self.assertEqual(self.h.mutations()[-1], ("RemovePackages", [0, [REF.package_id], False, False]))
        self.assertIn("PASS: hello removed through PackageKit", "\n".join(logs.output))

    def test_authorization_cancelled_is_expected_and_system_unchanged(self):
        self.session.precheck()
        self.h.error = 46
        with self.assertLogs(probe.log, level="INFO") as logs:
            self.assertFalse(self.session.install())
        self.assertFalse(self.session.installed_by_probe)
        self.assertFalse(self.h.snapshot.present)
        self.assertIn("PASS: authorization cancelled", "\n".join(logs.output))
        self.assertIn("PASS: system unchanged", "\n".join(logs.output))
        self.assertEqual(len(self.h.mutations()), 1)

    def test_error_does_not_grant_ownership_or_start_cleanup(self):
        self.session.precheck()
        self.h.error = 8
        with self.assertLogs(probe.log, level="ERROR"), self.assertRaises(probe.ProbeError):
            self.session.install()
        self.assertFalse(self.session.installed_by_probe)
        self.assertEqual(len(self.h.mutations()), 1)

    def test_user_cancellation_is_distinct_from_authorization_denial(self):
        self.session.precheck()
        self.h.error = 17
        with self.assertLogs(probe.log, level="INFO") as logs:
            self.assertFalse(self.session.install())
        self.assertFalse(self.session.installed_by_probe)
        self.assertIn("PASS: transaction cancelled", "\n".join(logs.output))
        self.assertNotIn("PASS: authorization cancelled", "\n".join(logs.output))

    def test_unavailable_service_never_mutates(self):
        self.h.unavailable = True
        with self.assertLogs(probe.log, level="ERROR"), self.assertRaises(probe.ProbeError):
            self.session.precheck()
        self.assertEqual(self.h.mutations(), [])

    def test_human_declining_each_stage_prevents_its_mutation(self):
        self.session.precheck()
        self.confirm.return_value = False
        self.assertFalse(self.session.install())
        self.assertEqual(self.h.mutations(), [])
        self.confirm.return_value = True
        self.assertTrue(self.session.install())
        self.confirm.return_value = False
        with self.assertLogs(probe.log, level="WARNING"):
            self.assertFalse(self.session.remove())
        self.assertEqual(len(self.h.mutations()), 1)
        self.assertTrue(self.session.installed_by_probe)

    def test_changed_state_after_confirmation_never_mutates(self):
        self.session.precheck()
        self.h.snapshot = probe.Snapshot(REF, REF, True)
        with self.assertRaises(probe.ProbeError):
            self.session.install()
        self.assertEqual(self.h.mutations(), [])

    def test_changed_installed_version_prevents_owned_removal(self):
        self.assertTrue(self.install())
        self.h.snapshot = probe.Snapshot(REF, replace(REF, package_id="hello;9.0;amd64;"), True)
        with self.assertRaises(probe.ProbeError):
            self.session.remove()
        self.assertEqual(len(self.h.mutations()), 1)

    def test_failed_removal_retains_ownership_and_reports_remaining_package(self):
        self.assertTrue(self.install())
        self.h.error = 13
        with self.assertLogs(probe.log, level="ERROR"), self.assertRaises(probe.ProbeError):
            self.session.remove()
        with self.assertLogs(probe.log, level="WARNING") as logs:
            self.session.report_state()
        self.assertIn("permanece instalado", "\n".join(logs.output))
        self.assertTrue(self.session.installed_by_probe)
        self.assertEqual(len(self.h.mutations()), 2)

    def test_timeout_never_cancels_retries_or_removes(self):
        self.session.precheck()
        self.runner.timeout_ms = 1
        self.h.hang = True
        with self.assertRaisesRegex(probe.ProbeError, "Timeout"):
            self.session.install()
        self.assertFalse(self.session.installed_by_probe)
        self.assertEqual(len(self.h.mutations()), 1)
        self.assertNotIn("Cancel", [method for method, args in self.h.calls])

    def test_cancel_delegates_only_when_allowed(self):
        active = Mock()
        self.runner.active = active
        active.progress.allow_cancel = False
        with self.assertLogs(probe.log, level="WARNING"):
            self.runner.cancel()
        active.cancel.assert_not_called()
        active.progress.allow_cancel = True
        self.runner.cancel()
        active.cancel.assert_called_once_with()

    def test_confirmation_requires_exact_phrase(self):
        with patch("builtins.input", return_value="yes"):
            self.assertFalse(probe.confirm("install"))
        with patch("builtins.input", return_value="INSTALAR hello"):
            self.assertTrue(probe.confirm("install"))
        with patch("builtins.input", return_value="REMOVER hello"):
            self.assertTrue(probe.confirm("remove"))

    def test_readonly_cli_never_dispatches_install_or_remove(self):
        session = Mock()
        with patch.object(probe, "ProbeSession", return_value=session), \
                patch.object(probe.logging, "basicConfig"):
            self.assertEqual(probe.main(["resolve"]), 0)
        session.precheck.assert_called_once_with()
        session.install.assert_not_called()
        session.remove.assert_not_called()

    def test_remove_cli_cannot_adopt_another_process_installation(self):
        self.h.snapshot = probe.Snapshot(REF, REF, True)
        with patch.object(probe, "ProbeSession", return_value=self.session), \
                patch.object(probe.sys.stdin, "isatty", return_value=True), \
                patch.object(probe.logging, "basicConfig"), \
                self.assertLogs(probe.log, level="WARNING"):
            self.assertEqual(probe.main(["remove"]), 1)
        self.assertEqual(self.h.calls, [])

    def test_full_cli_requires_both_phrases_and_removes_in_same_session(self):
        self.session.confirmation = probe.confirm
        with patch.object(probe, "ProbeSession", return_value=self.session), \
                patch.object(probe.sys.stdin, "isatty", return_value=True), \
                patch.object(probe.logging, "basicConfig"), \
                patch("builtins.input", side_effect=["INSTALAR hello", "remove", "REMOVER hello"]) as prompt:
            self.assertEqual(probe.main(["full"]), 0)
        self.assertEqual(prompt.call_count, 3)
        self.assertEqual(len(self.h.mutations()), 2)
        self.assertFalse(self.session.installed_by_probe)


if __name__ == "__main__":
    unittest.main()
