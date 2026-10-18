import ast
import configparser
import gettext
import os
import subprocess
import sys
import tempfile
import unittest
from email.parser import Parser
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "usr/lib/mainuan/mainuan-gestao-drivers"
sys.path.insert(0, str(MODULE_PATH))

from mainuan_drivers import APP_ID, APP_NAME, DISPLAY_NAME, ORGANIZATION, VERSION, DATA_DIR, ICON_PATH
from mainuan_drivers.qt.main_window import DriverDetectionWorker
from test_backend import make_backend


class MainuanIdentityTests(unittest.TestCase):
    def test_official_identity_and_debian_metadata(self):
        self.assertEqual((APP_NAME, APP_ID, ORGANIZATION, DISPLAY_NAME, VERSION),
                         ("mainuan-gestao-drivers", "org.mainuan.GestaoDrivers",
                          "Mainuan", "Gestão de Drivers", "0.6"))
        source, binary = [Parser().parsestr(stanza) for stanza in
                          (ROOT / "debian/control").read_text().strip().split("\n\n")]
        self.assertEqual(source["Source"], APP_NAME)
        self.assertEqual(binary["Package"], APP_NAME)
        self.assertIn("python3-pyqt6", binary["Depends"])
        self.assertIn("packagekit", binary["Depends"])
        for field in ("Conflicts", "Replaces", "Breaks", "Provides"):
            self.assertIsNone(binary[field])

    def test_launchers_use_normal_package_imports_and_no_gtk_fallback(self):
        launcher = ROOT / "usr/bin" / APP_NAME
        self.assertTrue(launcher.is_symlink())
        self.assertTrue(os.access(launcher, os.X_OK))
        self.assertEqual(launcher.resolve().parent, MODULE_PATH)
        source = launcher.read_text()
        tree = ast.parse(source)
        self.assertTrue(any(isinstance(node, ast.ImportFrom)
                            and node.module == "mainuan_drivers.qt.application" for node in ast.walk(tree)))
        self.assertNotIn("sys.path", source)
        self.assertNotIn("gtk", source.lower())
        legacy = ROOT / "usr/bin/mainuan-gestao-drivers-gtk-legacy"
        self.assertFalse(os.path.lexists(legacy))
        for old in ("mintdrivers", "mintdrivers-qt", "driver-manager", "cinnamon-driver-manager"):
            self.assertFalse((ROOT / "usr/bin" / old).exists())

    def test_desktop_is_the_only_visible_launcher(self):
        files = list((ROOT / "usr/share/applications").rglob("*.desktop"))
        self.assertEqual([path.name for path in files], [APP_ID + ".desktop"])
        desktop = configparser.ConfigParser(interpolation=None)
        desktop.read(files[0], encoding="utf-8")
        entry = desktop["Desktop Entry"]
        self.assertEqual(entry["Name"], DISPLAY_NAME)
        self.assertEqual(entry["Exec"], APP_NAME)
        self.assertEqual(entry["Icon"], APP_NAME)
        self.assertFalse(entry.getboolean("NoDisplay", False))
        self.assertNotIn("X-KDE-SubstituteUID", entry)

    def test_installed_resource_names_and_maintainer_scripts(self):
        for path in (ROOT / "usr").rglob("*"):
            if path.is_file() or path.is_symlink():
                self.assertNotIn("mintdrivers", str(path.relative_to(ROOT)))
                self.assertNotIn("driver-manager", path.name)
        self.assertTrue((ROOT / "usr/share/icons/hicolor/48x48/apps/mainuan-gestao-drivers.png").is_file())
        for script in ("preinst", "postinst", "prerm", "postrm"):
            self.assertFalse((ROOT / "debian" / script).exists())
        rules = (ROOT / "debian/rules").read_text()
        for exclusion in ("-X__pycache__", "-X.pyc", "-X.pyo"):
            self.assertIn(exclusion, rules)

    def test_active_modules_and_resources_do_not_use_mint_namespace(self):
        for path in (MODULE_PATH / "mainuan_drivers").rglob("*.py"):
            text = path.read_text()
            self.assertNotIn("linuxmint", text, str(path))
            self.assertNotIn("mintdrivers", text, str(path))
            self.assertNotIn("sys.path", text, str(path))
        self.assertTrue(DATA_DIR.is_dir())
        self.assertTrue(ICON_PATH.is_file())
        self.assertNotIn("linuxmint", str(DATA_DIR))

    def test_application_initializes_qsettings_identity_before_qapplication(self):
        check = r'''
import sys
sys.path.insert(0, sys.argv[1])
from PyQt6.QtCore import QCoreApplication, QSettings, QTimer
from PyQt6.QtGui import QGuiApplication
from mainuan_drivers.qt import application
from mainuan_drivers.qt.main_window import MainWindow
factory = application.QApplication
def create(argv):
    assert QCoreApplication.applicationName() == 'mainuan-gestao-drivers'
    assert QCoreApplication.organizationName() == 'Mainuan'
    assert QGuiApplication.desktopFileName() == 'org.mainuan.GestaoDrivers'
    app = factory(argv)
    settings = QSettings()
    assert settings.applicationName() == 'mainuan-gestao-drivers'
    assert settings.organizationName() == 'Mainuan'
    QTimer.singleShot(0, app.quit)
    return app
def window(test_mode=False):
    result = MainWindow(test_mode=test_mode, auto_start=False)
    assert not test_mode
    assert result.windowTitle() == 'Gestão de Drivers'
    assert QGuiApplication.applicationDisplayName() == 'Gestão de Drivers'
    assert not QGuiApplication.windowIcon().isNull()
    return result
application.QApplication = create
application.MainWindow = window
assert application.run(['mainuan-gestao-drivers']) == 0
'''
        env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
        result = subprocess.run([sys.executable, "-c", check, str(MODULE_PATH)],
                                env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("QSettings::value: Empty key passed", result.stderr)

    def test_test_mode_reuses_shared_backend_fixtures_and_preview_guard(self):
        received, planners = [], []

        def backend(**kwargs):
            return make_backend({}, extra_devices=kwargs["extra_devices"],
                                package_overrides=kwargs["package_overrides"])

        worker = DriverDetectionWorker(test_mode=True)
        worker.loaded.connect(received.append)
        worker.planningReady.connect(planners.append)
        with patch("mainuan_drivers.qt.main_window.DriverBackend", side_effect=backend):
            worker.run()
        self.assertEqual({device.device_id for device in received[0]}, {"dummy", "dummy-microcode"})
        self.assertTrue(planners[0].preview_only)
        self.assertTrue(any(device.is_cpu for device in received[0]))
        self.assertTrue(any(option.builtin for device in received[0] for option in device.drivers))

    def test_official_test_argument_reaches_qt_without_gtk(self):
        check = r'''
import sys
sys.path.insert(0, sys.argv[1])
from PyQt6.QtCore import QTimer
from mainuan_drivers.qt import application
from mainuan_drivers.qt.main_window import MainWindow
factory = application.QApplication
def create(argv):
    app = factory(argv)
    QTimer.singleShot(0, app.quit)
    return app
def window(test_mode=False):
    assert test_mode
    result = MainWindow(test_mode=test_mode, auto_start=False)
    assert result.windowTitle().startswith('Gestão de Drivers')
    return result
application.QApplication = create
application.MainWindow = window
assert application.run(['mainuan-gestao-drivers', 'test']) == 0
assert 'gi' not in sys.modules
'''
        result = subprocess.run([sys.executable, "-c", check, str(MODULE_PATH)],
                                env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_gettext_domain_is_mainuan_and_upstream_credits_remain(self):
        self.assertNotIn("mintdrivers.mo", (ROOT / "Makefile").read_text())
        self.assertIn("mainuan-gestao-drivers.mo", (ROOT / "Makefile").read_text())
        for catalog in (ROOT / "po").glob("*.po"):
            self.assertTrue(catalog.name.startswith("mainuan-gestao-drivers-"))
            self.assertIn('"Project-Id-Version: mainuan-gestao-drivers ', catalog.read_text())
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "mainuan-gestao-drivers.mo"
            subprocess.run(["msgfmt", "--check", "-o", str(output),
                            str(ROOT / "po/mainuan-gestao-drivers-pt_BR.po")], check=True)
            with output.open("rb") as catalog:
                translated = gettext.GNUTranslations(catalog)
            self.assertEqual(translated.gettext("Recommended"), "Recomendado")
            self.assertEqual(translated.gettext("No additional drivers are necessary."),
                             "Nenhum driver adicional é necessário.")
        copyright_text = (ROOT / "debian/copyright").read_text()
        self.assertIn("2013-2014 Clement Lefebvre", copyright_text)
        self.assertIn("License: GPL-2+", copyright_text)
