import subprocess
import sys
import unittest
from pathlib import Path

from PyQt6.QtCore import QEventLoop, QObject, QTimer, pyqtSignal
from PyQt6 import QtDBus

from test_transaction_planner import scenario, target
from mainuan_drivers.backend.transactions import RestartRequirement, TransactionAction, TransactionError, TransactionState
from mainuan_drivers.backend.transactions.packagekit import (
    DriverTransactionController, PackageKitTransaction, PROPERTIES_INTERFACE,
    ROOT_PATH, TRANSACTION_INTERFACE, QtDBusTransport,
)


class FakeTransport(QObject):
    eventReceived = pyqtSignal(str, object)
    serviceLost = pyqtSignal()

    def __init__(self, parent, calls, auto_resolve=False, unavailable=False, subscribe_error=False):
        super().__init__(parent)
        self.calls = calls
        self.auto_resolve = auto_resolve
        self.unavailable = unavailable
        self.subscribe_error = subscribe_error
        self.subscribed = False

    def call(self, path, interface, method, arguments, callback):
        self.calls.append((path, interface, method, arguments))
        if self.unavailable:
            callback([], TransactionError("not-running", "No PackageKit service"))
        elif method == "CreateTransaction":
            callback(["/123_test_transaction"], None)
        elif method == "GetAll":
            callback([{"Status": 1, "Percentage": 101, "AllowCancel": True}], None)
        else:
            callback([], None)
            if method == "Resolve" and self.auto_resolve:
                for name in arguments[1]:
                    version = "1.0-installed" if name == "old-driver" else "2.0-candidate"
                    self.eventReceived.emit("Package", [1, "%s;%s;amd64;available" % (name, version), "Driver"])
                self.eventReceived.emit("Finished", [1, 2])

    def subscribe(self, path):
        self.calls.append((path, "signals", "subscribe", []))
        self.subscribed = not self.subscribe_error
        return self.subscribed

    def unsubscribe(self):
        self.subscribed = False


class PackageKitTransactionTests(unittest.TestCase):
    def test_transport_decodes_completed_async_reply_and_dbus_error(self):
        from test_qt_frontend import app

        app()

        class Connection:
            error_name = "org.freedesktop.PackageKit.Denied"

            def isConnected(self):
                return True

            def asyncCall(self, message, timeout):
                if message.member() == "GetAll":
                    reply = message.createReply([{"Status": 13}])
                else:
                    reply = message.createErrorReply(self.error_name, "Denied")
                return QtDBus.QDBusPendingCall.fromCompletedCall(reply)

        transport = QtDBusTransport(connection=Connection())
        replies = []
        loop = QEventLoop()

        def completed(args, error):
            replies.append((args, error))
            loop.quit()

        transport.call("/test", PROPERTIES_INTERFACE, "GetAll", [TRANSACTION_INTERFACE],
                       completed)
        QTimer.singleShot(1000, loop.quit)
        loop.exec()
        self.assertEqual(replies[0], ([{"Status": 13}], None))
        transport.call("/test", TRANSACTION_INTERFACE, "Cancel", [],
                       completed)
        QTimer.singleShot(1000, loop.quit)
        loop.exec()
        self.assertTrue(replies[1][1].authorization_denied)
        for name in ("org.freedesktop.PackageKit.Transaction.RefusedByPolicy",
                     "org.freedesktop.PolicyKit1.Error.Cancelled"):
            with self.subTest(error=name):
                transport.bus.error_name = name
                transport.call("/test", TRANSACTION_INTERFACE, "Cancel", [], completed)
                QTimer.singleShot(1000, loop.quit)
                loop.exec()
                self.assertTrue(replies[-1][1].authorization_denied)
                self.assertEqual(replies[-1][1].cancelled, name.endswith(".Cancelled"))

    def make_transaction(self, installed=False, **kwargs):
        _, device, planner = scenario(installed)
        plan = planner.build({device.device_id: target(device, "new-driver")})
        self.calls = []
        factory = lambda parent: FakeTransport(parent, self.calls, **kwargs)
        transaction = PackageKitTransaction(planner, transport_factory=factory)
        self.results = []
        self.errors = []
        transaction.finished.connect(self.results.append)
        transaction.errorOccurred.connect(self.errors.append)
        return transaction, plan

    def emit(self, transaction, name, arguments):
        transaction.transport.eventReceived.emit(name, arguments)

    def test_creation_subscribes_before_resolve_and_unknown_progress(self):
        transaction, plan = self.make_transaction()
        transaction.resolve(plan)
        self.assertEqual([call[2] for call in self.calls], [
            "Introspect", "CreateTransaction", "subscribe", "GetAll", "SetHints", "Resolve"])
        self.assertTrue(transaction.transport.subscribed)
        self.assertIsNone(transaction.progress.percentage)
        self.assertEqual(self.calls[-1][3], [2, ["new-driver"]])

    def test_states_properties_item_progress_and_percentage(self):
        transaction, plan = self.make_transaction()
        transaction.resolve(plan)
        for status, state in ((13, TransactionState.RESOLVING), (8, TransactionState.DOWNLOADING),
                              (9, TransactionState.INSTALLING), (6, TransactionState.REMOVING),
                              (18, TransactionState.FINALIZING), (28, TransactionState.WAITING)):
            self.emit(transaction, "PropertiesChanged", [TRANSACTION_INTERFACE, {"Status": status, "Percentage": 40}, []])
            self.assertEqual(transaction.progress.state, state)
            self.assertEqual(transaction.progress.percentage, 40)
        self.emit(transaction, "ItemProgress", ["new-driver;2.0-candidate;amd64;", 9, 90])
        self.assertEqual(transaction.progress.percentage, 40)
        self.assertEqual(transaction.progress.package_id, "new-driver;2.0-candidate;amd64;")
        self.emit(transaction, "PropertiesChanged", [TRANSACTION_INTERFACE, {"Percentage": 101}, []])
        self.assertIsNone(transaction.progress.percentage)

    def test_success_and_single_use_disconnect(self):
        transaction, plan = self.make_transaction()
        transaction.resolve(plan)
        self.emit(transaction, "Package", [1, "new-driver;2.0-candidate;amd64;available", "Driver"])
        self.emit(transaction, "Finished", [1, 3])
        self.emit(transaction, "Finished", [1, 3])
        self.assertEqual(len(self.results), 1)
        self.assertEqual(self.results[0].state, TransactionState.FINISHED)
        self.assertEqual(self.results[0].runtime_ms, 3)
        self.assertFalse(transaction.transport.subscribed)
        with self.assertRaises(RuntimeError):
            transaction.resolve(plan)

    def test_wrong_version_does_not_validate_plan(self):
        transaction, plan = self.make_transaction()
        transaction.resolve(plan)
        self.emit(transaction, "Package", [1, "new-driver;obsolete;amd64;available", "Driver"])
        self.emit(transaction, "Finished", [1, 1])
        self.assertEqual(self.results[0].state, TransactionState.FAILED)
        self.assertEqual(self.errors[0].error_code, "package-unavailable")

    def test_structured_error_and_authorization_denied(self):
        transaction, plan = self.make_transaction()
        transaction.resolve(plan)
        self.emit(transaction, "ErrorCode", [46, "Authorization denied"])
        self.assertEqual(self.results, [])
        self.emit(transaction, "Finished", [2, 1])
        self.assertTrue(self.results[0].error.authorization_denied)
        self.assertEqual(self.results[0].state, TransactionState.FAILED)

    def test_finished_failure_without_error_signal(self):
        transaction, plan = self.make_transaction()
        transaction.resolve(plan)
        self.emit(transaction, "Finished", [5, 1])
        self.assertEqual(self.results[0].error.error_code, "packagekit-exit-5")

    def test_cancel_requested_differs_from_failure(self):
        transaction, plan = self.make_transaction()
        transaction.resolve(plan)
        self.assertTrue(transaction.cancel())
        self.assertFalse(transaction.cancel())
        self.assertEqual(self.calls[-1][2], "Cancel")
        self.emit(transaction, "ErrorCode", [17, "Cancelled"])
        self.emit(transaction, "Finished", [3, 1])
        self.assertEqual(self.errors, [])
        self.assertEqual(self.results[0].state, TransactionState.CANCELLED)
        self.assertTrue(self.results[0].cancel_requested)
        self.assertTrue(self.results[0].error.cancelled)

    def test_cancel_disallowed(self):
        transaction, plan = self.make_transaction()
        transaction.resolve(plan)
        self.emit(transaction, "PropertiesChanged", [TRANSACTION_INTERFACE, {"AllowCancel": False}, []])
        self.assertFalse(transaction.cancel())
        self.assertFalse(any(call[2] == "Cancel" for call in self.calls))

    def test_restart_keeps_strongest_requirement(self):
        transaction, plan = self.make_transaction()
        transaction.resolve(plan)
        self.emit(transaction, "RequireRestart", [6, "new-driver;2.0-candidate;amd64;"])
        self.emit(transaction, "RequireRestart", [5, "new-driver;2.0-candidate;amd64;"])
        self.assertEqual(transaction.progress.restart, RestartRequirement.SYSTEM)

    def test_missing_service_and_signal_connection_failure(self):
        for kwargs, code in (({"unavailable": True}, "service-unavailable"),
                             ({"subscribe_error": True}, "signal-connection")):
            transaction, plan = self.make_transaction(**kwargs)
            transaction.resolve(plan)
            self.assertEqual(self.results[0].error.error_code, code)
            self.assertEqual(self.results[0].state, TransactionState.FAILED)

    def test_service_lost_and_destroy(self):
        transaction, plan = self.make_transaction()
        transaction.resolve(plan)
        transaction.transport.serviceLost.emit()
        self.assertEqual(self.results[0].error.error_code, "service-lost")
        transaction, plan = self.make_transaction()
        transaction.resolve(plan)
        self.emit(transaction, "Destroy", [])
        self.assertEqual(self.results[0].error.error_code, "transaction-destroyed")

    def test_modifications_disabled_by_default(self):
        for method in ("install", "remove"):
            transaction, plan = self.make_transaction(True)
            getattr(transaction, method)(plan)
            self.assertEqual(self.calls, [])
            self.assertEqual(self.results[0].error.error_code, "execution-disabled")

    def test_simulation_uses_flags_and_conservative_removal_without_enabling_execution(self):
        for action, expected in ((TransactionAction.INSTALL, [6, ["new-driver;2.0-candidate;amd64;"]]),
                                 (TransactionAction.REMOVE, [4, ["old-driver;1.0-installed;amd64;"], False, False])):
            transaction, plan = self.make_transaction(True)
            transaction.simulate(plan, action)
            self.assertEqual(self.calls[-1][3], expected)
            hints = next(call[3] for call in self.calls if call[2] == "SetHints")
            self.assertIn("interactive=false", hints[0])

    def test_removal_resolves_installed_filter_and_rejects_available_only_package(self):
        transaction, plan = self.make_transaction(True)
        transaction.execution_enabled = True
        transaction.remove(plan)
        validator = transaction._validator
        self.assertEqual(self.calls[-1][3], [4, ["old-driver"]])
        self.emit(validator, "Package", [2, "old-driver;1.0-installed;amd64;available", "Driver"])
        self.emit(validator, "Finished", [1, 1])
        self.assertEqual(self.results[0].error.error_code, "package-not-installed")
        self.assertFalse(any(call[2] == "RemovePackages" for call in self.calls))

    def test_daemon_loss_during_mutation_reports_unknown_outcome(self):
        transaction, plan = self.make_transaction(auto_resolve=True)
        transaction.execution_enabled = True
        transaction.install(plan)
        transaction.transport.serviceLost.emit()
        self.assertTrue(self.results[0].error.outcome_unknown)

    def test_mutation_method_timeout_keeps_listening_until_finished(self):
        transaction, plan = self.make_transaction(auto_resolve=True)
        transaction.execution_enabled = True
        transaction.install(plan)
        transaction._method_reply([], TransactionError("org.freedesktop.DBus.Error.NoReply", "Timed out"))
        self.assertFalse(transaction._done)
        self.assertEqual(self.results, [])
        self.assertTrue(transaction.transport.subscribed)
        self.assertTrue(self.errors[-1].outcome_unknown)
        self.emit(transaction, "Package", [12, "new-driver;2.0-candidate;amd64;", "Driver"])
        self.emit(transaction, "Finished", [1, 1])
        self.assertEqual(self.results[0].state, TransactionState.FINISHED)

    def test_mutation_progress_is_recorded_for_failure_reconciliation(self):
        transaction, plan = self.make_transaction(auto_resolve=True)
        transaction.execution_enabled = True
        transaction.install(plan)
        self.emit(transaction, "Package", [12, "new-driver;2.0-candidate;amd64;", "Driver"])
        self.emit(transaction, "ErrorCode", [54, "Configure failed"])
        self.emit(transaction, "Finished", [2, 1])
        self.assertTrue(self.results[0].mutation_observed)

    def test_internal_install_and_remove_only_call_fake_after_resolution(self):
        for method, expected, args in (
                ("install", "InstallPackages", [2, ["new-driver;2.0-candidate;amd64;"]]),
                ("remove", "RemovePackages", [0, ["old-driver;1.0-installed;amd64;"], False, False])):
            transaction, plan = self.make_transaction(True, auto_resolve=True)
            transaction.execution_enabled = True
            getattr(transaction, method)(plan)
            methods = [call[2] for call in self.calls]
            self.assertLess(methods.index("Resolve"), methods.index(expected))
            self.assertEqual(methods.count("CreateTransaction"), 2)
            self.assertEqual(self.calls[-1][2:], (expected, args))

    def test_cancel_during_validation_prevents_later_mutation_even_if_resolve_succeeds(self):
        transaction, plan = self.make_transaction()
        transaction.execution_enabled = True
        transaction.install(plan)
        self.assertTrue(transaction.cancel())
        validator = transaction._validator
        self.emit(validator, "Package", [1, "new-driver;2.0-candidate;amd64;available", "Driver"])
        self.emit(validator, "Finished", [1, 1])
        self.assertEqual(self.results[0].state, TransactionState.CANCELLED)
        self.assertFalse(any(call[2] == "InstallPackages" for call in self.calls))

    def test_controller_plan_preview_is_safe_and_transaction_lock(self):
        _, device, planner = scenario(True)
        controller = DriverTransactionController(planner, transport_factory=lambda parent: FakeTransport(parent, []))
        plan = controller.select(device, target(device, "new-driver"))
        self.assertEqual(plan.action, TransactionAction.SWITCH)
        self.assertIsNone(controller._transaction)
        controller.resolve(plan)
        with self.assertRaises(RuntimeError):
            controller.resolve(plan)

    def test_qt_dbus_and_frontend_do_not_import_forbidden_modules(self):
        root = str(Path(__file__).resolve().parents[1] / "usr/lib/mainuan/mainuan-gestao-drivers")
        subprocess.run([sys.executable, "-c",
                        "import sys; sys.path.insert(0, %r); "
                        "import mainuan_drivers.qt.application; import mainuan_drivers.backend.transactions.packagekit; "
                        "blocked=('Gtk','Gdk','GdkPixbuf','XApp','PackageKitGlib','GLib','Gio'); "
                        "assert 'gi' not in sys.modules; "
                        "assert not any(n.rsplit('.',1)[-1] in blocked for n in sys.modules)" % root], check=True)
