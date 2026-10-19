import unittest
from dataclasses import replace
from unittest.mock import patch

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QCloseEvent
from PyQt6.QtTest import QSignalSpy
from PyQt6.QtWidgets import QDialogButtonBox, QLabel, QMessageBox
from test_qt_frontend import app
from test_driver_execution import FakeSource, FakeWorkflowFactory, await_signal
from test_transaction_planner import scenario, target
from mainuan_drivers.backend.transactions.execution import DriverExecutionController
from mainuan_drivers.backend.transactions.models import (
    ExecutionResult, PreparedPlan, RestartRequirement, TransactionAction,
    TransactionError, TransactionProgress, TransactionState,
)
from mainuan_drivers.qt.main_window import MainWindow, PlanDialog, execution_message


class DriverExecutionUITests(unittest.TestCase):
    def setUp(self):
        app().setQuitOnLastWindowClosed(False)
        self.windows = []

    def tearDown(self):
        for window in self.windows:
            self.assertFalse(window.executor.active)
            if window._thread:
                spy = QSignalSpy(window._thread.finished)
                await_signal(spy)
            window.close()

    def window(self):
        backend, device, planner = scenario(True)
        source = FakeSource(planner)
        factory = FakeWorkflowFactory()
        executor = DriverExecutionController(source=source, transaction_factory=factory)
        executor.available = True
        window = MainWindow(auto_start=False, executor=executor)
        window._set_planner(planner)
        window.show_devices(planner.devices)
        self.windows.append(window)
        return window, device, planner, factory

    def test_apply_enablement_and_controls_lock(self):
        window, device, planner, factory = self.window()
        self.assertFalse(window.apply_button.isEnabled())
        window.controller.select(device, target(device, "new-driver"))
        self.assertTrue(window.apply_button.isEnabled())
        window.executor._set_busy(True)
        self.assertFalse(window.apply_button.isEnabled())
        self.assertFalse(window.refresh_button.isEnabled())
        self.assertFalse(window.content.isEnabled())
        window.executor._set_busy(False)
        window.executor.available = False
        window._update_controls()
        self.assertFalse(window.apply_button.isEnabled())

    def test_invalid_plan_keeps_apply_disabled(self):
        window, device, planner, factory = self.window()
        window.controller.desired = {device.device_id: replace(target(device, "new-driver"), package_name="other-package")}
        window._update_controls()
        self.assertFalse(window.apply_button.isEnabled())

    def test_confirmation_has_concrete_packages_beta_and_explicit_actions(self):
        window, device, planner, factory = self.window()
        plan = planner.build({device.device_id: target(device, "new-driver")})
        prepared = PreparedPlan(plan, plan.installs, plan.removals)
        dialog = PlanDialog(prepared, confirmation=True, changed=True)
        labels = [label.text() for label in dialog.findChildren(QLabel)]
        self.assertIn("Release candidate", labels)
        self.assertIn("new-driver", labels)
        self.assertIn("old-driver", labels)
        self.assertTrue(any("Review the updated" in label for label in labels))
        buttons = dialog.findChild(QDialogButtonBox)
        self.assertEqual(buttons.standardButtons(),
                         QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel)
        self.assertTrue(buttons.button(QDialogButtonBox.StandardButton.Cancel).isDefault())

    def test_close_is_blocked_in_resolution_download_installation_and_removal(self):
        window, device, planner, factory = self.window()
        window.show()
        for state in (TransactionState.RESOLVING, TransactionState.DOWNLOADING,
                      TransactionState.INSTALLING, TransactionState.REMOVING):
            with self.subTest(state=state):
                window.executor.active = True
                window.executor.progress = TransactionProgress(TransactionAction.INSTALL, state, allow_cancel=False)
                event = QCloseEvent()
                with patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Close):
                    window.closeEvent(event)
                self.assertFalse(event.isAccepted())
                self.assertTrue(window.isVisible())
        window.executor.active = False

    def test_close_can_request_cancel_but_does_not_abandon_operation(self):
        window, device, planner, factory = self.window()
        window.executor.active = True
        window.executor.progress = TransactionProgress(TransactionAction.INSTALL, allow_cancel=True)
        event = QCloseEvent()
        with patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Cancel), \
                patch.object(window.executor, "cancel", return_value=True) as cancel:
            window.closeEvent(event)
            cancel.assert_called_once()
        self.assertFalse(event.isAccepted())
        window.executor.active = False

    def test_parent_cannot_close_while_confirmation_is_open(self):
        window, device, planner, factory = self.window()
        window._confirmation_open = True
        event = QCloseEvent()
        window.closeEvent(event)
        self.assertFalse(event.isAccepted())
        window._confirmation_open = False

    def test_unknown_percentage_and_non_cancellable_phase(self):
        window, device, planner, factory = self.window()
        window.executor.active = True
        window._show_progress(TransactionProgress(TransactionAction.INSTALL, TransactionState.DOWNLOADING,
                                                 package_id="new-driver;1;amd64;", message="Downloading", allow_cancel=True))
        self.assertEqual((window.progress_bar.minimum(), window.progress_bar.maximum()), (0, 0))
        self.assertIn("new-driver", window.progress_label.text())
        self.assertFalse(window.cancel_button.isHidden())
        window._show_progress(TransactionProgress(TransactionAction.INSTALL, TransactionState.INSTALLING, 55, allow_cancel=False))
        self.assertEqual(window.progress_bar.value(), 55)
        self.assertTrue(window.cancel_button.isHidden())
        window.executor.active = False

    def test_double_click_starts_one_preparation_and_cancel_refreshes_actual_data(self):
        window, device, planner, factory = self.window()
        window.controller.select(device, target(device, "new-driver"))
        # Close confirmation via its real Cancel action, without any mutation.
        def cancel_dialog():
            for widget in app().topLevelWidgets():
                if isinstance(widget, PlanDialog):
                    widget.reject()
                    return
            QTimer.singleShot(10, cancel_dialog)
        QTimer.singleShot(10, cancel_dialog)
        done = QSignalSpy(window.executor.finished)
        window.apply_changes()
        window.apply_changes()
        result = await_signal(done)[0]
        self.assertEqual(result.state, TransactionState.CANCELLED)
        self.assertEqual(sum(method == "resolve" for method, action in factory.calls), 1)
        self.assertFalse(any(method in ("install", "remove") for method, action in factory.calls))
        if window._thread:
            await_signal(QSignalSpy(window._thread.finished))
        self.assertEqual(window.executor.source.loads, 2)
        self.assertFalse(window.apply_button.isEnabled())

    def test_refresh_is_requested_after_every_terminal_result(self):
        window, device, planner, factory = self.window()
        for state in (TransactionState.FINISHED, TransactionState.FAILED,
                      TransactionState.CANCELLED, TransactionState.PARTIAL_FAILURE):
            with self.subTest(state=state):
                with patch.object(window, "refresh") as refresh:
                    # Signal wiring was made before patching; verify the real call by emitting.
                    prior = window.executor.source.loads
                    result = ExecutionResult(state, (), None, RestartRequirement.NONE)
                    window.executor.finished.emit(result)
                    window.executor.refreshRequested.emit()
                    if window._thread:
                        await_signal(QSignalSpy(window._thread.finished))
                    self.assertEqual(window.executor.source.loads, prior + 1)
                    self.assertTrue(window.result_label.text())

    def test_restart_and_error_presentations_do_not_claim_rollback(self):
        for restart, message in ((RestartRequirement.SYSTEM, "system restart"),
                                 (RestartRequirement.SESSION, "session"),
                                 (RestartRequirement.APPLICATION, "applications")):
            result = ExecutionResult(TransactionState.FINISHED, (), None, restart)
            self.assertIn(message, execution_message(result))
        result = ExecutionResult(TransactionState.FAILED, (), TransactionError(46, "Denied", authorization_denied=True),
                                 RestartRequirement.NONE)
        self.assertIn("authorization", execution_message(result))
        self.assertNotIn("Traceback", execution_message(result))
