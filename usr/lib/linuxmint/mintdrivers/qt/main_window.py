import gettext
import traceback

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from backend import DriverBackend
from backend.drivers import TEST_PACKAGE_OVERRIDES, make_test_device
from backend.transactions import PlanningError, TransactionPlanner
from backend.transactions.packagekit import DriverTransactionController

from .widgets import DeviceWidget


_ = gettext.gettext


class DriverDetectionWorker(QObject):
    planningReady = pyqtSignal(object)
    loaded = pyqtSignal(object)
    failed = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, test_mode=False):
        super().__init__()
        self.test_mode = test_mode

    @pyqtSlot()
    def run(self):
        try:
            backend = DriverBackend(
                extra_devices=_make_test_devices() if self.test_mode else None,
                package_overrides=TEST_PACKAGE_OVERRIDES if self.test_mode else None,
            )
            devices = backend.get_devices()
            planner = TransactionPlanner.from_backend(backend, devices, preview_only=self.test_mode)
            self.planningReady.emit(planner)
            self.loaded.emit(devices)
        except Exception:
            self.failed.emit(traceback.format_exc())
        finally:
            self.finished.emit()


def _make_test_devices():
    devices = {"dummy": make_test_device()}
    devices["dummy-microcode"] = {
        "modalias": "",
        "vendor": "Intel Corporation",
        "model": "Processor Microcode",
        "drivers": {
            "intel-microcode": {
                "free": False,
                "from_distro": True,
                "recommended": True,
            },
        },
    }
    return devices


class MainWindow(QMainWindow):
    def __init__(self, test_mode=False, auto_start=True):
        super().__init__()
        self.test_mode = test_mode
        self._thread = None
        self._worker = None
        self.controller = None

        title = _("Driver Manager")
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

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)

        header_layout = QHBoxLayout()
        header_layout.addWidget(self.status_label, 1)
        header_layout.addWidget(self.plan_button)
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
        root_layout.addLayout(header_layout)
        root_layout.addWidget(scroll_area, 1)
        self.setCentralWidget(root)

        if auto_start:
            self.refresh()

    def refresh(self):
        if self._thread is not None:
            return
        self._clear_content()
        self.plan_button.setEnabled(False)
        if self.controller:
            self.controller.deleteLater()
            self.controller = None
        self.refresh_button.setEnabled(False)
        self.status_label.setText(_("Searching for available drivers..."))

        loading = QLabel(_("Searching for available drivers..."))
        loading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        loading.setWordWrap(True)
        self.content_layout.addStretch(1)
        self.content_layout.addWidget(loading)
        self.content_layout.addStretch(1)

        self._thread = QThread(self)
        self._worker = DriverDetectionWorker(test_mode=self.test_mode)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.loaded.connect(self.show_devices)
        self._worker.planningReady.connect(self._set_planner)
        self._worker.failed.connect(self.show_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._detection_finished)
        self._thread.start()

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
        self.controller.planChanged.connect(
            lambda plan: self.plan_button.setEnabled(bool(plan.selections)))

    def _select(self, device, option):
        try:
            self.controller.select(device, option)
        except PlanningError as error:
            QMessageBox.warning(self, _("Cannot plan this change"),
                                _("The driver selection is inconsistent or cannot be changed automatically."),
                                QMessageBox.StandardButton.Close)
            print(str(error))
            return False
        return True

    def preview_plan(self):
        if self.controller:
            PlanDialog(self.controller.plan(), self).exec()

    @pyqtSlot(str)
    def show_error(self, details):
        self._clear_content()
        self.status_label.setText(_("Driver detection failed."))
        label = QLabel(_("Driver detection failed."))
        label.setWordWrap(True)
        label.setToolTip(details)
        self.content_layout.addWidget(label)
        print(details)

    @pyqtSlot()
    def _detection_finished(self):
        self.refresh_button.setEnabled(True)
        self._thread = None
        self._worker = None

    def closeEvent(self, event):
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
    def __init__(self, plan, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Planned changes"))
        self.resize(560, 420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(_("Preview only. These changes will not be executed.")))
        content = QWidget()
        details = QVBoxLayout(content)
        for title, packages in ((_("Install:"), plan.installs), (_("Remove:"), plan.removals)):
            label = QLabel(title)
            font = label.font()
            font.setBold(True)
            label.setFont(font)
            details.addWidget(label)
            text = "\n".join(package.name for package in packages) or _("None")
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
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

