from dataclasses import replace
import json
import logging
import os
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest, QSignalSpy
from PyQt6.QtWidgets import QLabel, QRadioButton, QDialogButtonBox, QScrollArea
from test_qt_frontend import app
from test_driver_execution import FakeSource, FakeWorkflowFactory, await_signal
from test_transaction_planner import scenario, target
from mainuan_drivers.backend.session import SessionState, SystemSessionProbe
from mainuan_drivers.backend.diagnostics import diagnostic_text
from mainuan_drivers.backend.transactions.execution import DriverExecutionController, SnapshotSource
from mainuan_drivers.backend.transactions.models import TransactionState, TransactionError, ExecutionResult, PreparedPlan, RestartRequirement
from mainuan_drivers.qt.main_window import MainWindow, DriverDetectionWorker, PlanDialog
from mainuan_drivers.qt.state import DetectionFailure, ViewModel, ViewState
from mainuan_drivers.qt.widgets import Badge


class SessionProbeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.cmdline, self.mountinfo = root / "cmdline", root / "mountinfo"
        self.cmdline.write_text("root=UUID=example ro quiet")
        self.mountinfo.write_text("33 2 8:17 / / rw - ext4 /dev/sda1 rw\n")
        self.probe = SystemSessionProbe(self.cmdline, self.mountinfo)

    def test_installed_block_root(self):
        self.assertEqual(self.probe.probe(), SessionState.INSTALLED_SYSTEM)

    def test_boot_casper_and_persistent_live(self):
        for value in ("boot=casper", "boot=casper persistent", "boot=live"):
            self.cmdline.write_text(value)
            self.assertEqual(self.probe.probe(), SessionState.LIVE_SESSION)

    def test_overlay_cow_is_live_without_boot_argument(self):
        self.mountinfo.write_text("33 2 0:1 / / rw - overlay overlay rw,upperdir=/cow/upper,workdir=/cow/work\n")
        self.assertEqual(self.probe.probe(), SessionState.LIVE_SESSION)

    def test_overlay_not_automatically_installed(self):
        self.mountinfo.write_text("33 2 0:1 / / rw - overlay overlay rw,upperdir=/other/upper\n")
        self.assertEqual(self.probe.probe(), SessionState.UNKNOWN)

    def test_missing_proc_data_is_unknown(self):
        self.cmdline.unlink()
        self.assertEqual(self.probe.probe(), SessionState.UNKNOWN)

    def test_permission_error_is_unknown(self):
        with patch.object(Path, "open", side_effect=PermissionError()):
            self.assertEqual(self.probe.probe(), SessionState.UNKNOWN)

    def test_malformed_or_ambiguous_mounts_are_unknown(self):
        for value in ("unexpected", "", self.mountinfo.read_text() * 2):
            self.mountinfo.write_text(value)
            self.assertEqual(self.probe.probe(), SessionState.UNKNOWN)

    def test_unknown_boot_method_and_ram_root_are_unknown(self):
        self.cmdline.write_text("boot=custom")
        self.assertEqual(self.probe.probe(), SessionState.UNKNOWN)
        self.cmdline.write_text("")
        self.mountinfo.write_text("33 2 0:1 / / rw - tmpfs tmpfs rw\n")
        self.assertEqual(self.probe.probe(), SessionState.UNKNOWN)


class SessionExecutionTests(unittest.TestCase):
    def setUp(self):
        app().setQuitOnLastWindowClosed(False)
        _, device, self.planner = scenario(False)
        self.plan = self.planner.build({device.device_id: target(device, "new-driver")})
        self.source = FakeSource(self.planner)
        self.original_load = self.source.load
        self.session = SessionState.INSTALLED_SYSTEM
        self.source.load = lambda: replace(self.original_load(), session=self.session)
        self.factory = FakeWorkflowFactory()
        self.controller = DriverExecutionController(source=self.source, transaction_factory=self.factory)
        self.controller.available = True
        self.addCleanup(self.controller.deleteLater)

    def test_live_and_unknown_block_before_any_packagekit_operation(self):
        for value in (SessionState.LIVE_SESSION, SessionState.UNKNOWN):
            self.session = value
            done = QSignalSpy(self.controller.finished)
            self.assertTrue(self.controller.prepare(self.planner, self.plan))
            result = await_signal(done)[0]
            self.assertEqual(result.error.error_code, "session-blocked")
            self.assertFalse(self.factory.calls)

    def test_session_rechecked_after_confirmation(self):
        ready = QSignalSpy(self.controller.prepared)
        self.controller.prepare(self.planner, self.plan)
        prepared = await_signal(ready)[0]
        self.session = SessionState.LIVE_SESSION
        done = QSignalSpy(self.controller.finished)
        self.assertTrue(self.controller.confirm(prepared))
        self.assertEqual(await_signal(done)[0].error.error_code, "session-blocked")
        self.assertFalse(any(method in ("install", "remove") for method, action in self.factory.calls))

    def test_installed_system_still_allows_fake_execution(self):
        ready = QSignalSpy(self.controller.prepared)
        self.controller.prepare(self.planner, self.plan)
        done = QSignalSpy(self.controller.finished)
        self.controller.confirm(await_signal(ready)[0])
        self.assertEqual(await_signal(done)[0].state, TransactionState.FINISHED)


class UxAndDiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app().setQuitOnLastWindowClosed(False)

    def window(self, scenario_name="default"):
        source = SnapshotSource(test_mode=True, scenario=scenario_name)
        snapshot = source.load()
        executor = DriverExecutionController(test_mode=True, source=source)
        window = MainWindow(test_mode=True, auto_start=False, executor=executor)
        self.addCleanup(window.deleteLater)
        self.addCleanup(window.close)
        window._receive_snapshot(snapshot)
        window._set_planner(snapshot.planner)
        window.show_devices(snapshot.planner.devices)
        window._update_controls()
        return window, snapshot

    def test_live_allows_selection_and_preview_but_not_apply(self):
        window, snapshot = self.window("live-session")
        device = snapshot.planner.devices[0]
        window._select(device, next(option for option in device.drivers if option.recommended))
        self.assertTrue(window.plan_button.isEnabled())
        self.assertFalse(window.apply_button.isEnabled())
        self.assertEqual(window.ui_state, ViewState.LIVE_SESSION)
        self.assertIn("Live Session", window.service_label.text())

    def test_packagekit_unavailable_retains_devices(self):
        window, snapshot = self.window("packagekit-unavailable")
        self.assertTrue(snapshot.planner.devices)
        self.assertEqual(window.ui_state, ViewState.PACKAGEKIT_UNAVAILABLE)
        self.assertFalse(window.apply_button.isEnabled())

    def test_unknown_session_disables_apply_but_keeps_preview(self):
        window, snapshot = self.window("third-party-recommended")
        window._receive_snapshot(replace(snapshot, session=SessionState.UNKNOWN))
        device = snapshot.planner.devices[0]
        window._select(device, next(option for option in device.drivers if option.recommended))
        self.assertEqual(window.ui_state, ViewState.SESSION_UNKNOWN)
        self.assertFalse(window.apply_button.isEnabled())
        self.assertTrue(window.plan_button.isEnabled())

    def test_empty_state_is_not_backend_error(self):
        window, snapshot = self.window("no-drivers")
        self.assertEqual(window.ui_state, ViewState.READY_NO_DRIVERS)
        self.assertIn("No additional drivers", window.status_label.text())

    def test_backend_failure_is_friendly_and_retryable(self):
        window, _ = self.window()
        window.show_error(DetectionFailure(ViewState.BACKEND_ERROR, "Friendly error"))
        self.assertEqual(window.ui_state, ViewState.BACKEND_ERROR)
        self.assertEqual(window.refresh_button.text(), "Try again")
        self.assertEqual(window.result_label.text(), "Friendly error")
        self.assertIsNone(window.controller)

    def test_backend_unavailable_is_distinct(self):
        window, _ = self.window()
        window.show_error(DetectionFailure(ViewState.BACKEND_UNAVAILABLE, "Unavailable"))
        self.assertEqual(window.ui_state, ViewState.BACKEND_UNAVAILABLE)

    def test_worker_error_does_not_expose_exception_credentials(self):
        source = Mock()
        source.load.side_effect = RuntimeError("https://user:secret@host/?token=secret")
        worker = DriverDetectionWorker(source=source)
        failed = QSignalSpy(worker.failed)
        with self.assertLogs("mainuan_drivers.qt.main_window", level="ERROR") as logs:
            worker.run()
        self.assertNotIn("secret", " ".join(logs.output))
        self.assertNotIn("secret", failed[0][0].message)

    def test_view_state_priority_prevents_empty_during_loading(self):
        view = ViewModel()
        self.assertEqual(view.state, ViewState.LOADING)
        view.ready, view.loading = True, True
        self.assertEqual(view.state, ViewState.LOADING)
        view.loading = False
        self.assertEqual(view.state, ViewState.READY_NO_DRIVERS)
        view.devices = 1
        self.assertEqual(view.state, ViewState.READY_WITH_DRIVERS)
        view.running = True
        self.assertEqual(view.state, ViewState.TRANSACTION_RUNNING)

    def test_terminal_states_and_offline_are_explicit_not_connectivity_probes(self):
        view = ViewModel(ready=True)
        for state in (ViewState.TRANSACTION_SUCCESS, ViewState.TRANSACTION_FAILURE, ViewState.REBOOT_REQUIRED,
                      ViewState.MOK_REQUIRED, ViewState.OFFLINE):
            view.outcome = state
            self.assertEqual(view.state, state)
        view.session = SessionState.LIVE_SESSION
        self.assertEqual(view.state, ViewState.LIVE_SESSION)
        view.backend_error = ViewState.BACKEND_ERROR
        self.assertEqual(view.state, ViewState.BACKEND_ERROR)

    def test_network_failure_sets_offline_only_after_packagekit_error(self):
        window, _ = self.window()
        window._execution_finished(ExecutionResult(TransactionState.FAILED, (), TransactionError(2, "Download failed"), RestartRequirement.NONE))
        self.assertEqual(window.ui_state, ViewState.OFFLINE)

    def test_download_or_missing_file_does_not_prove_offline(self):
        window, _ = self.window()
        for code in (10, 42):
            with self.subTest(code=code):
                window._execution_finished(ExecutionResult(TransactionState.FAILED, (), TransactionError(code, "Package error"), RestartRequirement.NONE))
                self.assertEqual(window.ui_state, ViewState.TRANSACTION_FAILURE)

    def test_diagnostic_allowlist_and_explicit_clipboard_action(self):
        window, snapshot = self.window("third-party-recommended")
        data = json.loads(diagnostic_text(snapshot, True, window.ui_state, True))
        self.assertEqual(data["version"], "1.0~rc1")
        self.assertTrue(data["test_mode"])
        self.assertNotIn("sys_path", json.dumps(data))
        self.assertNotIn("certificate", json.dumps(data))
        with patch.object(app().clipboard(), "setText") as copied:
            window.copy_diagnostics()
            copied.assert_called_once()

    def test_diagnostics_work_without_successful_detection(self):
        data = json.loads(diagnostic_text(None, False, ViewState.BACKEND_ERROR))
        self.assertEqual(data["devices"], [])
        self.assertEqual(data["session"], "unknown")

    def test_accessible_controls_and_radio_metadata(self):
        window, _ = self.window("third-party-recommended")
        for widget in (window.apply_button, window.cancel_button, window.refresh_button,
                       window.progress_bar, window.status_label, window.result_label):
            self.assertTrue(widget.accessibleName())
            self.assertTrue(widget.accessibleDescription())
        radio = window.findChild(QRadioButton)
        self.assertTrue(radio.accessibleName())
        self.assertTrue(radio.accessibleDescription())

    def test_keyboard_selection_and_escape_confirmation(self):
        window, snapshot = self.window("third-party-recommended")
        window.show()
        radio = next(button for button in window.findChildren(QRadioButton) if button.accessibleName() == "nvidia-driver-580")
        radio.setFocus()
        QTest.keyClick(radio, Qt.Key.Key_Space)
        self.assertTrue(window.plan_button.isEnabled())
        dialog = PlanDialog(window.controller.plan(), window)
        dialog.show()
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        self.assertFalse(dialog.isVisible())
        dialog.deleteLater()
        window.close()

    def test_tab_and_shift_tab_follow_command_order(self):
        window, _ = self.window()
        window.show()
        window.activateWindow()
        QTest.qWait(20)
        window.refresh_button.setFocus()
        QTest.qWait(1)
        self.assertTrue(window.refresh_button.hasFocus())
        QTest.keyClick(window.refresh_button, Qt.Key.Key_Tab)
        self.assertTrue(window.close_button.hasFocus())
        QTest.keyClick(window.close_button, Qt.Key.Key_Tab, Qt.KeyboardModifier.ShiftModifier)
        self.assertTrue(window.refresh_button.hasFocus())
        window.close()

    def test_enter_in_confirmation_defaults_to_cancel(self):
        window, _ = self.window()
        plan = window.controller.plan()
        prepared = PreparedPlan(plan, plan.installs, plan.removals, True, window._preflight(plan))
        dialog = PlanDialog(prepared, window, confirmation=True)
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        QTest.keyClick(dialog, Qt.Key.Key_Return)
        self.assertFalse(dialog.isVisible())
        self.assertEqual(dialog.result(), dialog.DialogCode.Rejected)

    def test_long_badges_wrap_as_plain_text(self):
        badge = Badge("<source> " + "Long translated repository information " * 10)
        self.addCleanup(badge.deleteLater)
        self.assertTrue(badge.wordWrap())
        self.assertEqual(badge.textFormat(), Qt.TextFormat.PlainText)

    def test_small_window_long_text_scrolls_without_hiding_commands(self):
        window, _ = self.window("third-party-recommended")
        window.result_label.setText("Long translated diagnostic message " * 100)
        window.result_label.show()
        window.resize(480, 360)
        window.show()
        QTest.qWait(10)
        scroll = window.findChild(QScrollArea)
        self.assertTrue(scroll.widgetResizable())
        self.assertGreater(scroll.verticalScrollBar().maximum(), 0)
        self.assertTrue(window.apply_button.isVisible())
        self.assertTrue(window.refresh_button.isVisible())
        self.assertTrue(window.result_label.wordWrap())
        window.close()

    def test_confirmation_identifies_third_party_without_promoting_it(self):
        window, snapshot = self.window("third-party-recommended")
        device = snapshot.planner.devices[0]
        window._select(device, next(option for option in device.drivers if option.recommended))
        dialog = PlanDialog(window.controller.plan(), window)
        self.addCleanup(dialog.deleteLater)
        self.assertTrue(any("Third-party repository" in label.text() for label in dialog.findChildren(QLabel)))


class CommandLineTests(unittest.TestCase):
    def test_version_is_available_without_detection(self):
        launcher = Path(__file__).resolve().parents[1] / "usr/bin/mainuan-gestao-drivers"
        result = subprocess.run([str(launcher), "--version"], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertIn("1.0~rc1", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_normal_and_debug_logging_levels(self):
        root = Path(__file__).resolve().parents[1] / "usr/lib/mainuan/mainuan-gestao-drivers"
        check = r'''
import logging,sys
from unittest.mock import Mock
sys.path.insert(0, sys.argv[1])
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QWidget
from mainuan_drivers.qt import application
factory = application.QApplication
def create(argv):
    app = factory(argv)
    QTimer.singleShot(0, app.quit)
    return app
application.QApplication = create
application.MainWindow = lambda test_mode: QWidget()
application.logging.basicConfig = Mock()
args = ['mainuan-gestao-drivers'] + (['--debug'] if sys.argv[2] == 'debug' else [])
assert application.run(args) == 0
assert application.logging.basicConfig.call_args.kwargs['level'] == (logging.DEBUG if sys.argv[2] == 'debug' else logging.WARNING)
'''
        for mode in ("normal", "debug"):
            with self.subTest(mode=mode):
                result = subprocess.run([sys.executable, "-c", check, str(root), mode], capture_output=True,
                                        text=True, timeout=10, env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
                self.assertEqual(result.returncode, 0, result.stderr)
