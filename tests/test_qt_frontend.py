import os
import subprocess
import sys
import unittest
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

MODULE_PATH = Path(__file__).resolve().parents[1] / "usr/lib/mainuan/mainuan-gestao-drivers"
sys.path.insert(0, str(MODULE_PATH))

from PyQt6.QtWidgets import QApplication, QLabel

from mainuan_drivers.backend import DeviceInfo, DeviceStatus, DriverOption, DriverOptionType
from mainuan_drivers.qt.main_window import MainWindow, PlanDialog
from mainuan_drivers.qt.widgets import device_status_text, driver_option_presentation


_APP = None


def app():
    global _APP
    instance = QApplication.instance()
    if instance is None:
        instance = QApplication([])
    _APP = instance
    return _APP


def option(package_name, **kwargs):
    defaults = {
        "version": "1.0",
        "summary": "Driver summary",
        "installed": False,
        "selected": False,
        "recommended": False,
        "builtin": False,
        "free": False,
        "requires_internet": False,
        "status": DeviceStatus.ALTERNATIVE,
        "option_type": DriverOptionType.PACKAGE,
        "selectable": False,
    }
    defaults.update(kwargs)
    return DriverOption(package_name=package_name, **defaults)


def device(*drivers):
    return DeviceInfo(
        device_id="device",
        modalias="",
        vendor="Example",
        model="Adapter",
        display_name="Example: Adapter",
        is_cpu=False,
        is_virtual=False,
        status=DeviceStatus.RECOMMENDED,
        icon_key="generic",
        drivers=drivers,
    )


class QtFrontendTests(unittest.TestCase):
    def test_selection_previews_plan_without_starting_transaction(self):
        from PyQt6.QtWidgets import QDialogButtonBox, QRadioButton
        from mainuan_drivers.backend.transactions import TransactionPlanner

        app()
        initial = option("old-driver", installed=True, selected=True, selectable=True)
        desired = option("new-driver", recommended=True, selected=False, selectable=True)
        current_device = device(initial, desired)
        window = MainWindow(auto_start=False)
        window._set_planner(TransactionPlanner((current_device,)))
        window.show_devices((current_device,))
        self.assertFalse(window.plan_button.isEnabled())
        radio = next(button for button in window.findChildren(QRadioButton)
                     if button.accessibleName() == "new-driver")
        radio.click()
        self.assertTrue(window.plan_button.isEnabled())
        self.assertTrue(radio.isChecked())
        self.assertIsNone(window.controller._transaction)
        plan = window.controller.plan()
        self.assertEqual([package.name for package in plan.installs], ["new-driver"])
        self.assertEqual([package.name for package in plan.removals], ["old-driver"])
        dialog = PlanDialog(plan)
        buttons = dialog.findChild(QDialogButtonBox)
        self.assertEqual(buttons.standardButtons(), QDialogButtonBox.StandardButton.Close)
        labels = [label.text() for label in dialog.findChildren(QLabel)]
        self.assertIn("Preview only. These changes will not be executed.", labels)

    def test_qt_frontend_import_does_not_load_gtk_xapp_or_packagekit(self):
        check = (
            "import sys; sys.path.insert(0, %r); import mainuan_drivers.qt.application; "
            "blocked = ('gi.repository.Gtk', 'gi.repository.Gdk', "
            "'gi.repository.GdkPixbuf', 'gi.repository.XApp', "
            "'gi.repository.PackageKitGlib', 'gi.repository.GLib', 'gi.repository.Gio'); "
            "assert not any(name in sys.modules for name in blocked), "
            "set(sys.modules).intersection(blocked)"
        ) % str(MODULE_PATH)
        subprocess.run([sys.executable, "-c", check], check=True)

    def test_driver_option_presentation_exposes_recommended_builtin_and_license(self):
        recommended = driver_option_presentation(option(
            "nvidia-driver-560",
            recommended=True,
            selected=True,
            installed=True,
            free=False,
            status=DeviceStatus.RECOMMENDED,
        ))
        self.assertIn("Recommended", recommended.badges)
        self.assertIn("Proprietary", recommended.badges)
        self.assertIn("Installed", recommended.badges)
        self.assertIn("Current", recommended.badges)

        builtin = driver_option_presentation(option(
            "linux-generic",
            builtin=True,
            free=True,
        ))
        self.assertIn("Integrated into the system", builtin.badges)
        self.assertNotIn("Open-source", builtin.badges)

        free = driver_option_presentation(option("mesa-driver", free=True))
        self.assertIn("Open-source", free.badges)

    def test_manual_and_disable_options_have_user_facing_titles(self):
        manual = driver_option_presentation(option(
            None,
            status=DeviceStatus.MANUALLY_INSTALLED,
            option_type=DriverOptionType.MANUAL,
        ))
        disabled = driver_option_presentation(option(
            None,
            status=DeviceStatus.NO_DRIVER,
            option_type=DriverOptionType.DISABLE,
        ))
        self.assertEqual(manual.title, "Continue using a manually installed driver")
        self.assertEqual(disabled.title, "Do not use the device")

    def test_device_status_text_handles_microcode(self):
        cpu = device(option("intel-microcode", recommended=True))
        cpu = DeviceInfo(**{**cpu.__dict__, "is_cpu": True})
        self.assertEqual(device_status_text(cpu), "Processor microcode")

    def test_empty_state_is_not_an_error(self):
        app()
        window = MainWindow(auto_start=False)
        window.show_devices(())
        labels = [label.text() for label in window.findChildren(QLabel)]
        self.assertTrue(any("No additional drivers are necessary." in text for text in labels))

    def test_device_with_multiple_options_is_rendered(self):
        app()
        window = MainWindow(auto_start=False)
        window.show_devices((device(
            option("recommended-driver", recommended=True, status=DeviceStatus.RECOMMENDED),
            option("alternative-driver", free=True),
            option("linux-generic", builtin=True, free=True, selected=True),
        ),))
        labels = [label.text() for label in window.findChildren(QLabel)]
        self.assertIn("recommended-driver", labels)
        self.assertIn("alternative-driver", labels)
        self.assertIn("linux-generic", labels)
        self.assertIn("Recommended", labels)
        self.assertIn("Integrated into the system", labels)


if __name__ == "__main__":
    unittest.main()
