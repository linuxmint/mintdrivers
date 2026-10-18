"""Read-only native Qt visual probe; set QT_SCALE_FACTOR externally to test DPI."""
import argparse
import gettext
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "usr/lib/mainuan/mainuan-gestao-drivers"))

from PyQt6.QtCore import QCoreApplication
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QRadioButton
from mainuan_drivers import APP_NAME, APP_ID, DISPLAY_NAME, ORGANIZATION, VERSION, LOCALE_DIR
from mainuan_drivers.backend.session import SessionState
from mainuan_drivers.backend.test_scenarios import SCENARIOS
from mainuan_drivers.backend.transactions.execution import SnapshotSource, DriverExecutionController
from mainuan_drivers.backend.transactions.packagekit import QtDBusTransport
from mainuan_drivers.qt.main_window import MainWindow, DriverDetectionWorker, PlanDialog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compact", action="store_true")
    options = parser.parse_args()
    options.output.mkdir(parents=True, exist_ok=True)
    original = QtDBusTransport.call
    def guarded(self, path, interface, method, arguments, callback):
        if method not in ("Introspect", "GetAll", "CreateTransaction", "SetHints", "Resolve"):
            raise AssertionError("Mutating method forbidden: " + method)
        return original(self, path, interface, method, arguments, callback)
    QtDBusTransport.call = guarded
    gettext.bindtextdomain(APP_NAME, str(LOCALE_DIR))
    gettext.textdomain(APP_NAME)
    QCoreApplication.setApplicationName(APP_NAME)
    QCoreApplication.setOrganizationName(ORGANIZATION)
    QCoreApplication.setApplicationVersion(VERSION)
    QGuiApplication.setDesktopFileName(APP_ID)
    application = QApplication([APP_NAME])
    application.setApplicationDisplayName(DISPLAY_NAME)
    application.setQuitOnLastWindowClosed(False)
    print("Qt platform", application.platformName(), "DPR", application.devicePixelRatio(), "version", VERSION, flush=True)
    real = MainWindow()
    real.show()
    for tick in range(300):
        QTest.qWait(100)
        if real._thread is None:
            break
    assert real._thread is None and real._snapshot is not None
    print("REAL", real.ui_state.value, "session", real._snapshot.session.value, flush=True)
    real.grab().save(str(options.output / "real.png"))
    real.close()
    critical = {"default", "third-party-recommended", "third-party-dkms", "live-session", "no-drivers",
                "packagekit-unavailable", "backend-error", "secure-dkms-pending", "activation-active"}
    for name, title in SCENARIOS:
        if options.compact and name not in critical:
            continue
        source = SnapshotSource(test_mode=True, scenario=name)
        executor = DriverExecutionController(test_mode=True, source=source)
        window = MainWindow(test_mode=True, auto_start=False, executor=executor)
        window.scenario_combo.blockSignals(True)
        window.scenario_combo.setCurrentIndex(window.scenario_combo.findData(name))
        window.scenario_combo.blockSignals(False)
        worker = DriverDetectionWorker(source=source)
        worker.snapshotReady.connect(window._receive_snapshot)
        worker.planningReady.connect(window._set_planner)
        worker.loaded.connect(window.show_devices)
        worker.failed.connect(window.show_error)
        worker.run()
        window._update_controls()
        area = application.primaryScreen().availableGeometry()
        window.resize(min(560, area.width() - 40), min(440, area.height() - 40))
        window.show()
        QTest.qWait(70)
        if name != "backend-error":
            snapshot = window._snapshot
            if snapshot.planner.devices:
                device = snapshot.planner.devices[0]
                option = next((item for item in device.drivers if item.recommended and not item.selected), None)
                if option:
                    button = next(button for button in window.findChildren(QRadioButton)
                                  if button.accessibleName() == option.package_name)
                    button.click()
                    blocked = bool(window._preflight(window.controller.plan()).blockers)
                    blocked |= snapshot.session != SessionState.INSTALLED_SYSTEM or not executor.available
                    assert window.apply_button.isEnabled() == (not blocked), name
                    dialog = PlanDialog(window.controller.plan(), window, preflight=window._preflight(window.controller.plan()))
                    dialog.resize(min(560, area.width() - 40), min(440, area.height() - 40))
                    dialog.show()
                    QTest.qWait(40)
                    dialog.grab().save(str(options.output / (name + "-preview.png")))
                    dialog.close()
        assert window.apply_button.geometry().right() < window.width(), name
        window.grab().save(str(options.output / (name + ".png")))
        print("SCENARIO", name, window.ui_state.value, "size", window.width(), window.height(), flush=True)
        window.close()
        window.deleteLater()
        QTest.qWait(10)
    forbidden = {"gi", "Gtk", "Gdk", "GdkPixbuf", "XApp", "PackageKitGlib", "GLib", "Gio"}
    assert not any(set(name.split(".")) & forbidden for name in sys.modules)
    print("PASS: read-only native Qt scenarios; no forbidden imports", flush=True)


if __name__ == "__main__":
    main()
