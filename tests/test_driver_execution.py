import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "usr/lib/mainuan/mainuan-gestao-drivers"))

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtTest import QSignalSpy
from test_qt_frontend import app
from test_transaction_planner import scenario, target
from mainuan_drivers.backend.transactions.execution import DriverExecutionController, DriverSnapshot, PackageKitAvailability
from mainuan_drivers.backend.transactions.models import (
    PackageReference, RestartRequirement, TransactionAction, TransactionError,
    TransactionProgress, TransactionResult, TransactionState,
)
from mainuan_drivers.backend.transactions.safety import SecureBootState


def await_signal(spy):
    if not spy:
        if not spy.wait(3000):
            raise AssertionError("Qt signal did not arrive")
    return spy[-1]


class FakeSource:
    def __init__(self, planner, snapshots=None, secure_boot=SecureBootState.DISABLED):
        self.planner = planner
        self.snapshots = list(snapshots or ())
        self.loads = 0
        self.secure_boot = secure_boot

    def load(self):
        self.loads += 1
        planner = self.snapshots.pop(0) if self.snapshots else self.planner
        return DriverSnapshot(planner, self.secure_boot)


class FakeWorkflowFactory:
    def __init__(self, failures=None, extra_installs=(), extra_removals=(), hold=None,
                 restart=RestartRequirement.NONE, mutation_observed=False, extra_effects=None):
        self.calls = []
        self.failures = failures or {}
        self.extra_installs = extra_installs
        self.extra_removals = extra_removals
        self.hold = hold
        self.restart = restart
        self.mutation_observed = mutation_observed
        self.extra_effects = extra_effects
        self.transactions = []

    def __call__(self, planner, parent=None, execution_enabled=False):
        factory = self

        class Transaction(QObject):
            progressChanged = pyqtSignal(object)
            errorOccurred = pyqtSignal(object)
            finished = pyqtSignal(object)

            def __init__(self):
                super().__init__(parent)
                self.progress = TransactionProgress(TransactionAction.RESOLVE)
                self._done = False

            def resolve(self, plan):
                self.start("resolve", plan, TransactionAction.RESOLVE)

            def simulate(self, plan, action):
                self.start("simulate", plan, action)

            def install(self, plan):
                self.start("install", plan, TransactionAction.INSTALL)

            def remove(self, plan):
                self.start("remove", plan, TransactionAction.REMOVE)

            def start(self, method, plan, action):
                self.method, self.action, self.plan = method, action, plan
                factory.calls.append((method, action))
                self.ordinal = factory.calls.count((method, action))
                state = (TransactionState.RESOLVING if method in ("resolve", "simulate") else
                         TransactionState.INSTALLING if method == "install" else TransactionState.REMOVING)
                self.progress = TransactionProgress(action, state, None, message="Working", allow_cancel=True)
                self.progressChanged.emit(self.progress)
                if factory.hold != method:
                    QTimer.singleShot(0, self.complete)

            def complete(self, cancelled=False):
                if self._done:
                    return
                self._done = True
                error = factory.failures.get((self.method, self.action, self.ordinal),
                                             factory.failures.get((self.method, self.action)))
                state = TransactionState.CANCELLED if cancelled else TransactionState.FAILED if error else TransactionState.FINISHED
                if self.method == "resolve":
                    effects = ()
                elif self.action == TransactionAction.INSTALL:
                    effects = tuple((27, ref) for ref in self.plan.installs + tuple(factory.extra_installs))
                    effects += tuple((28, ref) for ref in factory.extra_removals)
                else:
                    effects = tuple((28, ref) for ref in self.plan.removals + tuple(factory.extra_removals))
                if factory.extra_effects:
                    effects += tuple(factory.extra_effects(self.method, self.action, self.ordinal))
                self.finished.emit(TransactionResult(
                    self.action, state, 3 if cancelled else 2 if error else 1, error,
                    factory.restart, effects=effects,
                    mutation_observed=factory.mutation_observed and self.method in ("install", "remove")))

            def cancel(self):
                if self._done or not self.progress.allow_cancel:
                    return False
                QTimer.singleShot(0, lambda: self.complete(cancelled=True))
                return True

        result = Transaction()
        self.transactions.append(result)
        return result


class DriverExecutionTests(unittest.TestCase):
    def setUp(self):
        app().setQuitOnLastWindowClosed(False)
        self.controllers = []

    def build(self, kind="switch", factory=None, source=None):
        backend, device, planner = scenario(installed=kind != "install")
        desired = target(device, "linux-generic" if kind == "remove" else "new-driver")
        plan = planner.build({device.device_id: desired})
        factory = factory or FakeWorkflowFactory()
        source = source or FakeSource(planner)
        controller = DriverExecutionController(source=source, transaction_factory=factory)
        controller.available = True
        self.controllers.append(controller)
        return controller, planner, plan, factory, source

    def prepare(self, controller, planner, plan):
        spy = QSignalSpy(controller.prepared)
        self.assertTrue(controller.prepare(planner, plan))
        return await_signal(spy)[0]

    def run_plan(self, controller, planner, plan):
        prepared = self.prepare(controller, planner, plan)
        completed = QSignalSpy(controller.finished)
        refresh = QSignalSpy(controller.refreshRequested)
        self.assertTrue(controller.confirm(prepared))
        result = await_signal(completed)[0]
        self.assertEqual(len(refresh), 1)
        return result

    def test_install_remove_and_switch_success(self):
        for kind, actions in (("install", [TransactionAction.INSTALL]),
                              ("remove", [TransactionAction.REMOVE]),
                              ("switch", [TransactionAction.REMOVE, TransactionAction.INSTALL])):
            with self.subTest(kind=kind):
                controller, planner, plan, factory, source = self.build(kind)
                result = self.run_plan(controller, planner, plan)
                self.assertEqual(result.state, TransactionState.FINISHED)
                self.assertEqual(result.restart, RestartRequirement.POSSIBLE)
                self.assertEqual([stage.action for stage in result.completed], actions)
                self.assertEqual([action for method, action in factory.calls if method in ("install", "remove")], actions)
                self.assertEqual(source.loads, 2)

    def test_confirmation_is_required_and_double_click_is_rejected(self):
        controller, planner, plan, factory, source = self.build()
        spy = QSignalSpy(controller.prepared)
        self.assertTrue(controller.prepare(planner, plan))
        self.assertFalse(controller.prepare(planner, plan))
        prepared = await_signal(spy)[0]
        self.assertFalse(any(method in ("install", "remove") for method, action in factory.calls))
        result = QSignalSpy(controller.finished)
        self.assertTrue(controller.confirm(prepared))
        self.assertFalse(controller.confirm(prepared))
        await_signal(result)
        self.assertEqual(sum(method == "remove" for method, action in factory.calls), 1)

    def test_changed_plan_requires_a_new_confirmation(self):
        backend, device, original = scenario(True)
        backend._get_cache()["new-driver"].candidate.version = "3.0"
        changed = type(original).from_backend(backend, backend.get_devices())
        controller, planner, plan, factory, source = self.build(source=FakeSource(original, [original, changed, changed]))
        prepared = self.prepare(controller, planner, plan)
        spy = QSignalSpy(controller.prepared)
        self.assertTrue(controller.confirm(prepared))
        updated, changed_flag = await_signal(spy)
        self.assertTrue(changed_flag)
        self.assertNotEqual(updated.plan, prepared.plan)
        self.assertFalse(any(method in ("install", "remove") for method, action in factory.calls))
        done = QSignalSpy(controller.finished)
        self.assertTrue(controller.confirm(updated))
        self.assertEqual(await_signal(done)[0].state, TransactionState.FINISHED)

    def test_stale_confirmation_object_and_forged_plan_are_rejected(self):
        controller, planner, plan, factory, source = self.build()
        prepared = self.prepare(controller, planner, plan)
        self.assertFalse(controller.confirm(replace(prepared)))
        self.assertFalse(controller.prepare(planner, replace(plan, installs=())))
        controller.discard(prepared)

    def test_dependency_installs_are_shown_and_unrelated_removals_are_blocked(self):
        dependency = PackageReference("driver-library", "driver-library;1;amd64;")
        controller, planner, plan, factory, source = self.build(factory=FakeWorkflowFactory(extra_installs=(dependency,)))
        prepared = self.prepare(controller, planner, plan)
        self.assertIn(dependency, prepared.installs)
        controller.discard(prepared)
        unrelated = PackageReference("unrelated-package", "unrelated-package;1;amd64;")
        controller, planner, plan, factory, source = self.build(factory=FakeWorkflowFactory(extra_removals=(unrelated,)))
        finished = QSignalSpy(controller.finished)
        controller.prepare(planner, plan)
        result = await_signal(finished)[0]
        self.assertEqual(result.error.error_code, "unsafe-dependencies")
        self.assertFalse(any(method in ("install", "remove") for method, action in factory.calls))

    def test_failure_before_removal_starts_no_mutation(self):
        factory = FakeWorkflowFactory(failures={("resolve", TransactionAction.RESOLVE): TransactionError(4, "PackageKit failure")})
        controller, planner, plan, factory, source = self.build(factory=factory)
        finished = QSignalSpy(controller.finished)
        refresh = QSignalSpy(controller.refreshRequested)
        controller.prepare(planner, plan)
        result = await_signal(finished)[0]
        self.assertEqual(result.state, TransactionState.FAILED)
        self.assertEqual(len(refresh), 1)
        self.assertEqual(result.completed, ())

    def test_changed_root_package_id_in_simulation_prevents_mutation(self):
        changed = PackageReference("new-driver", "new-driver;3;amd64;")
        factory = FakeWorkflowFactory(extra_effects=lambda method, action, ordinal:
            ((27, changed),) if method == "simulate" and action == TransactionAction.INSTALL else ())
        controller, planner, plan, factory, source = self.build(factory=factory)
        done = QSignalSpy(controller.finished)
        controller.prepare(planner, plan)
        self.assertEqual(await_signal(done)[0].error.error_code, "unsafe-dependencies")
        self.assertFalse(any(method in ("install", "remove") for method, action in factory.calls))

    def test_partial_failure_after_removal_has_no_rollback(self):
        factory = FakeWorkflowFactory(failures={("install", TransactionAction.INSTALL): TransactionError(10, "Download failed")})
        controller, planner, plan, factory, source = self.build(factory=factory)
        result = self.run_plan(controller, planner, plan)
        self.assertEqual(result.state, TransactionState.PARTIAL_FAILURE)
        self.assertEqual([stage.action for stage in result.completed], [TransactionAction.REMOVE])
        self.assertTrue(result.refresh_required)
        self.assertEqual([method for method, action in factory.calls if method in ("remove", "install")], ["remove", "install"])
        from mainuan_drivers.qt.main_window import execution_message
        self.assertIn("No automatic restoration", execution_message(result))

    def test_failed_simulation_after_removal_stops_before_installation(self):
        factory = FakeWorkflowFactory(failures={
            ("simulate", TransactionAction.INSTALL, 3): TransactionError(13, "Dependencies changed")})
        controller, planner, plan, factory, source = self.build(factory=factory)
        result = self.run_plan(controller, planner, plan)
        self.assertEqual(result.state, TransactionState.PARTIAL_FAILURE)
        self.assertFalse(any(method == "install" for method, action in factory.calls))

    def test_changed_dependencies_after_removal_stop_with_partial_failure(self):
        dependency = PackageReference("driver-library", "driver-library;2;amd64;")
        factory = FakeWorkflowFactory(extra_effects=lambda method, action, ordinal:
            ((27, dependency),) if (method, action, ordinal) == ("simulate", TransactionAction.INSTALL, 3) else ())
        controller, planner, plan, factory, source = self.build(factory=factory)
        result = self.run_plan(controller, planner, plan)
        self.assertEqual(result.state, TransactionState.PARTIAL_FAILURE)
        self.assertEqual(result.error.error_code, "changed-dependencies")
        self.assertFalse(any(method == "install" for method, action in factory.calls))

    def test_multiarch_dependencies_remain_distinct_in_confirmation_and_recheck(self):
        dependencies = (PackageReference("driver-library", "driver-library;1;amd64;"),
                        PackageReference("driver-library", "driver-library;1;i386;"))
        controller, planner, plan, factory, source = self.build(factory=FakeWorkflowFactory(extra_installs=dependencies))
        prepared = self.prepare(controller, planner, plan)
        self.assertTrue(set(dependencies) <= set(prepared.installs))
        from mainuan_drivers.qt.main_window import PlanDialog
        from PyQt6.QtWidgets import QLabel
        dialog = PlanDialog(prepared, confirmation=True)
        labels = "\n".join(label.text() for label in dialog.findChildren(QLabel))
        self.assertIn("driver-library (amd64)", labels)
        self.assertIn("driver-library (i386)", labels)
        done = QSignalSpy(controller.finished)
        controller.confirm(prepared)
        self.assertEqual(await_signal(done)[0].state, TransactionState.FINISHED)
        self.assertEqual(len(done[0][0].completed), 2)

    def test_downgrades_and_untrusted_effects_are_blocked_before_mutation(self):
        dependency = PackageReference("driver-library", "driver-library;1;amd64;")
        for info in (20, 30, 23):
            with self.subTest(info=info):
                factory = FakeWorkflowFactory(extra_effects=lambda method, action, ordinal:
                    ((info, dependency),) if method == "simulate" else ())
                controller, planner, plan, factory, source = self.build(factory=factory)
                done = QSignalSpy(controller.finished)
                controller.prepare(planner, plan)
                self.assertEqual(await_signal(done)[0].error.error_code, "unsafe-dependencies")
                self.assertFalse(any(method in ("install", "remove") for method, action in factory.calls))

    def test_unexpected_actual_removal_of_another_architecture_stops_switch(self):
        unrelated = PackageReference("old-driver", "old-driver;1.0-installed;i386;")
        factory = FakeWorkflowFactory(extra_effects=lambda method, action, ordinal:
            ((13, unrelated),) if method == "remove" else ())
        controller, planner, plan, factory, source = self.build(factory=factory)
        result = self.run_plan(controller, planner, plan)
        self.assertEqual(result.state, TransactionState.PARTIAL_FAILURE)
        self.assertEqual(result.error.error_code, "unexpected-removal")
        self.assertFalse(any(method == "install" for method, action in factory.calls))

    def test_authorization_network_dependency_and_packagekit_failures_refresh(self):
        errors = (TransactionError(46, "Denied", authorization_denied=True),
                  TransactionError(10, "No network"), TransactionError(13, "Dependency failure"),
                  TransactionError(4, "Internal error"))
        for error in errors:
            with self.subTest(code=error.error_code):
                factory = FakeWorkflowFactory(failures={("install", TransactionAction.INSTALL): error})
                controller, planner, plan, factory, source = self.build("install", factory=factory)
                result = self.run_plan(controller, planner, plan)
                self.assertEqual(result.state, TransactionState.FAILED)
                self.assertEqual(result.error, error)
                from mainuan_drivers.qt.main_window import execution_message
                if error.authorization_denied:
                    self.assertIn("authorization", execution_message(result))

    def test_daemon_loss_and_mid_install_failure_report_partial_uncertainty(self):
        for error, observed in ((TransactionError("service-lost", "Daemon disappeared", outcome_unknown=True), False),
                                (TransactionError(54, "Configuration failed"), True)):
            factory = FakeWorkflowFactory(failures={("install", TransactionAction.INSTALL): error}, mutation_observed=observed)
            controller, planner, plan, factory, source = self.build("install", factory=factory)
            result = self.run_plan(controller, planner, plan)
            self.assertEqual(result.state, TransactionState.PARTIAL_FAILURE)
            self.assertTrue(result.error.outcome_unknown)

    def test_user_cancellation_and_non_cancellable_phase(self):
        factory = FakeWorkflowFactory(hold="install")
        controller, planner, plan, factory, source = self.build("install", factory=factory)
        prepared = self.prepare(controller, planner, plan)
        controller.confirm(prepared)
        loop = QSignalSpy(controller.progressChanged)
        while not any(method == "install" for method, action in factory.calls):
            self.assertTrue(loop.wait(1000))
        transaction = factory.transactions[-1]
        controller._progress(replace(transaction.progress, allow_cancel=False))
        self.assertFalse(controller.cancel())
        controller._progress(transaction.progress)
        finished = QSignalSpy(controller.finished)
        self.assertTrue(controller.cancel())
        self.assertEqual(await_signal(finished)[0].state, TransactionState.CANCELLED)

    def test_cancel_after_completed_removal_is_partial_not_rollback(self):
        factory = FakeWorkflowFactory(hold="install")
        controller, planner, plan, factory, source = self.build(factory=factory)
        controller.confirm(self.prepare(controller, planner, plan))
        progress = QSignalSpy(controller.progressChanged)
        while not any(method == "install" for method, action in factory.calls):
            self.assertTrue(progress.wait(1000))
        done = QSignalSpy(controller.finished)
        self.assertTrue(controller.cancel())
        result = await_signal(done)[0]
        self.assertEqual(result.state, TransactionState.PARTIAL_FAILURE)
        self.assertTrue(result.error.cancelled)
        self.assertEqual([item.action for item in result.completed], [TransactionAction.REMOVE])
        self.assertEqual(sum(method == "remove" for method, action in factory.calls), 1)

    def test_restart_and_unknown_percentage(self):
        controller, planner, plan, factory, source = self.build("install", factory=FakeWorkflowFactory(restart=RestartRequirement.SESSION))
        progress = []
        controller.progressChanged.connect(progress.append)
        result = self.run_plan(controller, planner, plan)
        self.assertEqual(result.restart, RestartRequirement.SESSION)
        self.assertTrue(any(item.percentage is None for item in progress))

    def test_secure_boot_blocks_dkms_but_not_plain_packages(self):
        backend, device, planner = scenario()
        refs = dict(planner._packages)
        refs[("new-driver", False)] = replace(refs[("new-driver", False)], requires_dkms=True)
        guarded = type(planner)(planner.devices, refs)
        controller, unused, unused_plan, factory, source = self.build("install", source=FakeSource(guarded, secure_boot=SecureBootState.ENABLED))
        plan = guarded.build({"device": target(device, "new-driver")})
        finished = QSignalSpy(controller.finished)
        controller.prepare(guarded, plan)
        self.assertIn("Secure Boot", await_signal(finished)[0].error.details)
        self.assertEqual(factory.calls, [])
        controller, planner, plan, factory, source = self.build("install")
        source.secure_boot = SecureBootState.ENABLED
        self.assertEqual(self.run_plan(controller, planner, plan).state, TransactionState.FINISHED)

    def test_test_mode_never_uses_injected_real_transaction_factory(self):
        backend, device, planner = scenario(True)
        planner.preview_only = True
        plan = planner.build({"device": target(device, "new-driver")})
        source = FakeSource(planner)
        source.record_simulation = lambda plan, action: None
        factory = FakeWorkflowFactory()
        controller = DriverExecutionController(test_mode=True, source=source, transaction_factory=factory)
        result = self.run_plan(controller, planner, plan)
        self.assertTrue(result.simulated)
        self.assertEqual(factory.calls, [])

    def test_packagekit_unavailable_blocks_prepare(self):
        controller, planner, plan, factory, source = self.build()
        controller.available = False
        self.assertFalse(controller.can_apply(planner, plan))
        self.assertFalse(controller.prepare(planner, plan))
        self.assertEqual(factory.calls, [])

    def test_service_lost_while_confirmation_is_open_refreshes_without_mutation(self):
        controller, planner, plan, factory, source = self.build()
        prepared = self.prepare(controller, planner, plan)
        controller.available = False
        done = QSignalSpy(controller.finished)
        refresh = QSignalSpy(controller.refreshRequested)
        self.assertFalse(controller.confirm(prepared))
        self.assertEqual(done[0][0].error.error_code, "service-unavailable")
        self.assertEqual(len(refresh), 1)
        self.assertFalse(any(method in ("remove", "install") for method, action in factory.calls))


class AvailabilityTests(unittest.TestCase):
    def test_missing_busy_and_supported_daemon(self):
        for data, error, expected in (({}, TransactionError("missing", "Unavailable"), False),
                                      ({"VersionMajor": 1, "VersionMinor": 3, "Locked": True}, None, False),
                                      ({"VersionMajor": 1, "VersionMinor": 3, "Locked": False}, None, True),
                                      ({"VersionMajor": 2, "VersionMinor": 0}, None, False)):
            class Transport(QObject):
                def call(self, path, interface, method, args, callback):
                    callback([data], error)
            monitor = PackageKitAvailability(transport_factory=lambda parent: Transport(parent))
            changed = QSignalSpy(monitor.changed)
            monitor.check()
            self.assertEqual(changed[0][0], expected)
