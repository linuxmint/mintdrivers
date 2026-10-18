import gettext
import logging
from collections import Counter
from dataclasses import replace

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from mainuan_drivers.backend import DriverBackend
from mainuan_drivers.backend.drivers import make_test_devices
from mainuan_drivers.backend.preflight import (
    ActivationState, DriverPreflight, DkmsState, HeadersState, MokState, SecureBootState, assess_activation,
)
from mainuan_drivers.backend.test_scenarios import SCENARIOS
from mainuan_drivers.backend.transactions import PlanningError, TransactionPlanner
from mainuan_drivers.backend.transactions.packagekit import DriverTransactionController
from mainuan_drivers.backend.transactions.execution import (
    DriverExecutionController, PackageKitAvailability, SnapshotSource,
)
from mainuan_drivers.backend.transactions.models import TransactionState, RestartRequirement
from mainuan_drivers.backend.transactions.planner import package_identity

from .widgets import DeviceWidget
from .. import DISPLAY_NAME


_ = gettext.gettext
logger = logging.getLogger(__name__)


class DriverDetectionWorker(QObject):
    snapshotReady = pyqtSignal(object)
    planningReady = pyqtSignal(object)
    loaded = pyqtSignal(object)
    failed = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, test_mode=False, source=None, inspection_plan=None):
        super().__init__()
        self.test_mode = test_mode
        self.source = source
        self.inspection_plan = inspection_plan

    @pyqtSlot()
    def run(self):
        try:
            source = self.source or SnapshotSource(self.test_mode, backend_factory=DriverBackend)
            snapshot = (source.inspect(self.inspection_plan) if self.inspection_plan and hasattr(source, "inspect")
                        else source.load())
            self.snapshotReady.emit(snapshot)
            planner = snapshot.planner
            self.planningReady.emit(planner)
            self.loaded.emit(planner.devices)
        except Exception:
            logger.exception("driver detection failed")
            self.failed.emit(_("Driver detection failed. Consult the application log for details."))
        finally:
            self.finished.emit()


def _make_test_devices():
    return make_test_devices()


class MainWindow(QMainWindow):
    def __init__(self, test_mode=False, auto_start=True, executor=None):
        super().__init__()
        self.test_mode = test_mode
        self._thread = None
        self._worker = None
        self.controller = None
        self._snapshot = None
        self._pending_result = None
        self.executor = executor or DriverExecutionController(self, test_mode=test_mode)
        self.executor.busyChanged.connect(self._update_controls)
        self.executor.progressChanged.connect(self._show_progress)
        self.executor.prepared.connect(self._confirm_plan)
        self.executor.finished.connect(self._execution_finished)
        self.executor.refreshRequested.connect(self.refresh)
        self._confirmation_open = False
        self._service_message = ""
        self._availability = None

        title = DISPLAY_NAME
        if self.test_mode:
            title = _("%s - Qt test mode") % title
        self.setWindowTitle(title)
        self.resize(840, 560)

        self.refresh_button = QPushButton(_("Refresh"))
        self.refresh_button.setIcon(QIcon.fromTheme("view-refresh"))
        self.refresh_button.clicked.connect(self.refresh)
        self.close_button = QPushButton(_("Close"))
        self.close_button.setIcon(QIcon.fromTheme("window-close"))
        self.close_button.clicked.connect(self.close)
        self.plan_button = QPushButton(_("Preview changes"))
        self.plan_button.setIcon(QIcon.fromTheme("document-preview"))
        self.plan_button.setEnabled(False)
        self.plan_button.clicked.connect(self.preview_plan)
        self.apply_button = QPushButton(_("Apply changes"))
        self.apply_button.setIcon(QIcon.fromTheme("dialog-ok-apply"))
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self.apply_changes)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)

        header_layout = QHBoxLayout()
        header_layout.addStretch(1)
        header_layout.addWidget(self.plan_button)
        header_layout.addWidget(self.apply_button)
        header_layout.addWidget(self.refresh_button)
        header_layout.addWidget(self.close_button)

        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(12)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll_area.setWidget(self.content)

        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(18, 18, 18, 18)
        root_layout.setSpacing(14)
        if self.test_mode:
            indicator = QLabel(_("Test mode - no changes will be applied to the system"))
            indicator.setWordWrap(True)
            root_layout.addWidget(indicator)
            self.scenario_combo = QComboBox()
            for key, label in SCENARIOS:
                self.scenario_combo.addItem(_(label), key)
            self.scenario_combo.setAccessibleName(_("Test scenario"))
            self.scenario_combo.currentIndexChanged.connect(self._change_scenario)
            root_layout.addWidget(self.scenario_combo)
        root_layout.addWidget(self.status_label)
        root_layout.addLayout(header_layout)
        self.service_label = QLabel()
        self.service_label.setWordWrap(True)
        root_layout.addWidget(self.service_label)
        self.preflight_label = QLabel()
        self.preflight_label.setTextFormat(Qt.TextFormat.PlainText)
        self.preflight_label.setWordWrap(True)
        root_layout.addWidget(self.preflight_label)
        self.result_label = QLabel()
        self.result_label.setTextFormat(Qt.TextFormat.PlainText)
        self.result_label.setWordWrap(True)
        root_layout.addWidget(self.result_label)
        root_layout.addWidget(scroll_area, 1)
        self.progress_label = QLabel()
        self.progress_label.setTextFormat(Qt.TextFormat.PlainText)
        self.progress_label.setWordWrap(True)
        root_layout.addWidget(self.progress_label)
        progress_layout = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.cancel_button = QPushButton(_("Cancel"))
        self.cancel_button.setIcon(QIcon.fromTheme("process-stop"))
        self.cancel_button.clicked.connect(self.executor.cancel)
        progress_layout.addWidget(self.progress_bar, 1)
        progress_layout.addWidget(self.cancel_button)
        root_layout.addLayout(progress_layout)
        self.progress_bar.hide()
        self.progress_label.hide()
        self.cancel_button.hide()
        self.setCentralWidget(root)

        if auto_start:
            if not self.test_mode:
                self._availability = PackageKitAvailability(self)
                self._availability.changed.connect(self._service_changed)
                self._availability.check()
            self.refresh()

    def refresh(self):
        if self._thread is not None or self.executor.active:
            return
        if self._availability:
            self._availability.check()
        self._clear_content()
        self.plan_button.setEnabled(False)
        if self.controller:
            self.controller.deleteLater()
            self.controller = None
        self.refresh_button.setEnabled(False)
        self._update_controls()
        self.status_label.setText(_("Searching for available drivers..."))

        loading = QLabel(_("Searching for available drivers..."))
        loading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        loading.setWordWrap(True)
        self.content_layout.addStretch(1)
        self.content_layout.addWidget(loading)
        self.content_layout.addStretch(1)

        self._thread = QThread(self)
        self._worker = DriverDetectionWorker(test_mode=self.test_mode, source=self.executor.source,
                                            inspection_plan=self._pending_result.plan if self._pending_result else None)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.loaded.connect(self.show_devices)
        self._worker.planningReady.connect(self._set_planner)
        self._worker.snapshotReady.connect(self._receive_snapshot)
        self._worker.failed.connect(self.show_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._detection_finished)
        self._thread.start()
        self._update_controls()

    @pyqtSlot(object)
    def show_devices(self, devices):
        self._clear_content()
        if not devices:
            self.status_label.setText(_("No additional drivers are necessary."))
            empty = QLabel(
                _("No additional drivers are necessary.\n\n"
                  "Your computer is already using the available/recommended drivers.")
            )
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setWordWrap(True)
            self.content_layout.addStretch(1)
            self.content_layout.addWidget(empty)
            self.content_layout.addStretch(1)
            return

        self.status_label.setText(
            gettext.ngettext(
                "%(count)d device was found.",
                "%(count)d devices were found.",
                len(devices),
            ) % {"count": len(devices)}
        )
        for device in devices:
            callback = (lambda option, current_device=device: self._select(current_device, option)) if self.controller else None
            self.content_layout.addWidget(DeviceWidget(device, callback, self.test_mode))
        self.content_layout.addStretch(1)

    @pyqtSlot(object)
    def _set_planner(self, planner):
        self.controller = DriverTransactionController(planner, self)
        self.controller.planChanged.connect(self._update_controls)

    def _select(self, device, option):
        try:
            self.controller.select(device, option)
        except PlanningError as error:
            QMessageBox.warning(self, _("Cannot plan this change"),
                                _("The driver selection is inconsistent or cannot be changed automatically."),
                                QMessageBox.StandardButton.Close)
            logger.warning("invalid driver selection: %s", error)
            return False
        return True

    def preview_plan(self):
        if self.controller and not self.executor.active and self._thread is None:
            plan = self.controller.plan()
            PlanDialog(plan, self, preflight=self._preflight(plan)).exec()

    def _change_scenario(self):
        if self._thread is not None or self.executor.active:
            return
        self.executor.source.set_scenario(self.scenario_combo.currentData())
        self.result_label.clear()
        self._pending_result = None
        self.refresh()

    def _preflight(self, plan):
        if self._snapshot and self._snapshot.context:
            return DriverPreflight(self._snapshot.context, self._snapshot.evidence).check(plan.installs)
        return None

    @pyqtSlot(object)
    def _receive_snapshot(self, snapshot):
        self._snapshot = snapshot
        if self._pending_result:
            result = self._pending_result
            if result.plan and snapshot.context:
                activations = assess_activation(result.plan, snapshot.context, snapshot.installed_packages,
                                                result.state != TransactionState.FINISHED, snapshot.evidence)
                result = replace(result, activations=activations)
            self.result_label.setText(execution_message(result))
            self._pending_result = None

    def _service_changed(self, available, message):
        self.executor.available = available
        self._service_message = message
        self.service_label.setText(message)
        self._update_controls()

    def _update_controls(self, *args):
        idle = not self.executor.active and self._thread is None and not self._confirmation_open
        if self.test_mode:
            self.scenario_combo.setEnabled(idle)
        self.content.setEnabled(idle)
        self.refresh_button.setEnabled(idle)
        self.apply_button.setEnabled(False)
        self.plan_button.setEnabled(False)
        self.preflight_label.clear()
        if idle and self.controller:
            try:
                plan = self.controller.plan()
                self.plan_button.setEnabled(bool(plan.selections))
                preflight = self._preflight(plan)
                if preflight:
                    self.preflight_label.setText("\n".join(issue.message for issue in preflight.blockers + preflight.warnings))
                self.apply_button.setEnabled(self.executor.can_apply(self.controller.planner, plan)
                                             and not (preflight and preflight.blockers))
            except PlanningError:
                pass
        if not self.executor.active:
            self.progress_bar.hide()
            self.progress_label.hide()
            self.cancel_button.hide()

    def apply_changes(self):
        if not self.apply_button.isEnabled() or not self.controller or self._confirmation_open:
            return
        self.result_label.clear()
        self.executor.prepare(self.controller.planner, self.controller.plan())

    def _confirm_plan(self, prepared, changed):
        self._confirmation_open = True
        self._update_controls()
        dialog = PlanDialog(prepared, self, confirmation=True, changed=changed)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        self._confirmation_open = False
        if accepted:
            if not self.executor.confirm(prepared):
                self.executor.discard(prepared)
        else:
            self.executor.discard(prepared)
        self._update_controls()

    def _show_progress(self, progress):
        self.progress_label.show()
        text = progress.message
        if progress.package_id:
            text += "\n" + progress.package_id.split(";", 1)[0]
        self.progress_label.setText(text)
        self.progress_bar.show()
        if progress.percentage is None:
            self.progress_bar.setRange(0, 0)
        else:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(progress.percentage)
        self.cancel_button.setVisible(progress.allow_cancel)
        self.cancel_button.setEnabled(progress.allow_cancel and not progress.cancel_requested)

    def _execution_finished(self, result):
        self._pending_result = result if result.plan else None
        message = (_("Package operations finished. Checking driver activation...")
                   if result.state == TransactionState.FINISHED and result.completed else execution_message(result))
        self.result_label.setText(message)
        if self._availability:
            self._availability.check()

    @pyqtSlot(str)
    def show_error(self, details):
        self._clear_content()
        self.status_label.setText(_("Driver detection failed."))
        label = QLabel(_("Driver detection failed."))
        label.setWordWrap(True)
        label.setToolTip(details)
        self.content_layout.addWidget(label)
        self.result_label.setText(details)

    @pyqtSlot()
    def _detection_finished(self):
        self.refresh_button.setEnabled(True)
        self._thread = None
        self._worker = None
        self._update_controls()

    def closeEvent(self, event):
        if self._confirmation_open:
            event.ignore()
            return
        if self.executor.active:
            event.ignore()
            can_cancel = self.executor.progress.allow_cancel
            buttons = QMessageBox.StandardButton.Close
            if can_cancel:
                buttons |= QMessageBox.StandardButton.Cancel
            answer = QMessageBox.warning(
                self, _("Driver changes are in progress"),
                _("Wait for the operation to finish before closing this window.") +
                ("\n" + _("Choose Cancel to request transaction cancellation.") if can_cancel else ""),
                buttons, QMessageBox.StandardButton.Close)
            if can_cancel and answer == QMessageBox.StandardButton.Cancel:
                self.executor.cancel()
            return
        if self._thread is not None:
            # Detection cannot be interrupted safely while APT is in use.
            self._thread.requestInterruption()
            event.ignore()
            self.hide()
            self._thread.finished.connect(self.close)
            return
        super().closeEvent(event)

    def _clear_content(self):
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()


class PlanDialog(QDialog):
    def __init__(self, plan, parent=None, confirmation=False, changed=False, preflight=None):
        super().__init__(parent)
        self.setWindowTitle(_("Planned changes"))
        preflight = preflight or getattr(plan, "preflight", None)
        self.resize(560, 420)
        layout = QVBoxLayout(self)
        if confirmation:
            layout.addWidget(QLabel(_("Beta version")))
            label = QLabel(_("Changes that will be applied"))
            label.setWordWrap(True)
            layout.addWidget(label)
            if changed:
                label = QLabel(_("The system or package plan changed. Review the updated changes before applying."))
                label.setWordWrap(True)
                layout.addWidget(label)
            if plan.simulated:
                label = QLabel(_("Test mode - no changes will be applied to the system"))
                label.setWordWrap(True)
                layout.addWidget(label)
        else:
            layout.addWidget(QLabel(_("Preview only. These changes will not be executed.")))
        content = QWidget()
        details = QVBoxLayout(content)
        if preflight:
            heading = QLabel(_("System verification"))
            font = heading.font()
            font.setBold(True)
            heading.setFont(font)
            details.addWidget(heading)
            secure = {SecureBootState.ENABLED: _("Secure Boot: enabled"),
                      SecureBootState.DISABLED: _("Secure Boot: disabled"),
                      SecureBootState.UNSUPPORTED: _("Secure Boot: unsupported"),
                      SecureBootState.UNKNOWN: _("Secure Boot: unknown")}[preflight.secure_boot_state]
            module = {DkmsState.NO_DKMS: _("Module: no DKMS required"),
                      DkmsState.DKMS_REQUIRED: _("Module: DKMS required"),
                      DkmsState.DKMS_POSSIBLE: _("Module: prebuilt/DKMS alternatives"),
                      DkmsState.UNKNOWN: _("Module requirements: unknown")}[preflight.dkms_state]
            for text in (secure, module):
                details.addWidget(QLabel(text))
            if preflight.dkms_state != DkmsState.NO_DKMS:
                mok = {MokState.ENROLLED: _("MOK: enrolled; module signing is not verified"),
                       MokState.NOT_ENROLLED: _("MOK: not enrolled"),
                       MokState.PENDING: _("MOK: enrollment pending"),
                       MokState.UNKNOWN: _("MOK: unknown")}[preflight.mok_state]
                headers = {HeadersState.PRESENT: _("Kernel headers: present"),
                           HeadersState.MISSING: _("Kernel headers: missing"),
                           HeadersState.UNKNOWN: _("Kernel headers: unknown"),
                           HeadersState.NOT_REQUIRED: _("Kernel headers: not required")}[preflight.headers_state]
                details.addWidget(QLabel(mok))
                details.addWidget(QLabel(headers))
            if preflight.requires_reboot:
                details.addWidget(QLabel(_("Restart: required to complete activation")))
            for issue in preflight.blockers + preflight.warnings:
                label = QLabel((_("Blocked: ") if issue in preflight.blockers else _("Warning: ")) + issue.message)
                label.setTextFormat(Qt.TextFormat.PlainText)
                label.setWordWrap(True)
                details.addWidget(label)
        for title, packages in ((_("Install:"), plan.installs), (_("Remove:"), plan.removals)):
            label = QLabel(title)
            font = label.font()
            font.setBold(True)
            label.setFont(font)
            details.addWidget(label)
            counts = Counter(package.name for package in packages)
            names = ["%s (%s)" % (package.name, package_identity(package.package_id)[2])
                     if counts[package.name] > 1 and package.package_id else package.name for package in packages]
            text = "\n".join(names) or _("None")
            label = QLabel(text)
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            details.addWidget(label)
        if plan.installs or plan.removals:
            details.addWidget(QLabel(_("A restart may be required.")))
        details.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        if confirmation:
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel)
            apply = buttons.button(QDialogButtonBox.StandardButton.Apply)
            apply.setText(_("Apply"))
            apply.setEnabled(not (preflight and preflight.blockers))
            apply.clicked.connect(self.accept)
            buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(_("Cancel"))
            buttons.button(QDialogButtonBox.StandardButton.Cancel).setDefault(True)
        else:
            buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


def execution_message(result):
    if result.state == TransactionState.PARTIAL_FAILURE:
        message = _("The driver change was not completed. Some changes may already have been applied. "
                    "The actual system state is being detected again. No automatic restoration was attempted.")
        if result.completed:
            message += "\n" + _("Completed stages: %s") % ", ".join(
                _("Removal") if stage.action.value == "remove" else _("Installation") for stage in result.completed)
    elif result.error and result.error.authorization_denied:
        message = _("The changes were not applied because authorization was cancelled or denied.")
    elif result.state == TransactionState.CANCELLED:
        message = _("The operation was cancelled. The actual system state is being detected again.")
    elif result.state == TransactionState.FINISHED:
        message = (_("Simulation completed. No system changes were made.") if result.simulated else
                   _("The changes were applied successfully.") if result.completed else
                   _("No driver changes were necessary."))
        if result.activations and not result.simulated:
            message = _("Package changes completed. Driver activation is not yet confirmed.")
    elif result.error and result.error.error_code in (2, 10, 42):
        message = _("The package download failed. Check the connection and review the detected driver state.")
    elif result.error and result.error.error_code in (13, 20, 35):
        message = _("Package dependencies prevented this change. No more aggressive removal was attempted.")
    else:
        message = _("The driver operation failed. The actual system state is being detected again.")
    if result.error:
        message += "\n" + result.error.details
    activation_text = {
        ActivationState.ACTIVE: _("Driver activation verified."),
        ActivationState.INSTALLED_REBOOT_REQUIRED: _("Installed; restart the computer to complete driver activation."),
        ActivationState.INSTALLED_MOK_REQUIRED: _("Installed; restart the computer and complete key enrollment in MokManager."),
        ActivationState.INSTALLED_NOT_ACTIVE: _("Installed, but driver activation could not be verified. Review system verification warnings."),
        ActivationState.FAILED: _("The requested driver package is not installed."),
        ActivationState.UNKNOWN: _("The current driver activation state is unknown."),
    }
    for activation in result.activations:
        message += "\n" + (activation.package_name + ": " if activation.package_name else "") + activation_text[activation.state]
    if result.restart == RestartRequirement.SYSTEM:
        message += "\n" + _("A system restart is required to complete driver activation.")
    elif result.restart == RestartRequirement.SESSION:
        message += "\n" + _("Restart your session to complete the changes.")
    elif result.restart == RestartRequirement.APPLICATION:
        message += "\n" + _("Restart the affected applications to complete the changes.")
    elif result.restart == RestartRequirement.POSSIBLE:
        message += "\n" + _("A restart may be required.")
    return message

