import ast
from email.parser import Parser
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import unittest

from inspect_deb import audit_package, PackageAuditError, OBSOLETE_CONFFILE, PACKAGE

ROOT = Path(__file__).resolve().parents[1]
MODULES = ROOT / "usr/lib/mainuan/mainuan-gestao-drivers"


def member(path, mode=0o644):
    value = tarfile.TarInfo("./" + path)
    value.mode = mode
    return value


class QtOnlyPackagingTests(unittest.TestCase):
    def setUp(self):
        self.control = ("Package: %s\nVersion: 0.5\nArchitecture: all\n"
                        "Depends: python3, python3-pyqt6, python3-apt, ubuntu-drivers-common, packagekit\n"
                        "Recommends: mokutil, openssl, kmod\n" % PACKAGE)
        self.members = [member("usr/bin/" + PACKAGE),
                        member("usr/share/applications/org.mainuan.GestaoDrivers.desktop"),
                        member("usr/share/man/man1/" + PACKAGE + ".1.gz")]
        text = "dpkg-maintscript-helper rm_conffile %s 0.5~ %s -- \"$@\"" % (OBSOLETE_CONFFILE, PACKAGE)
        self.scripts = dict.fromkeys(("preinst", "postinst", "postrm"), text)

    def test_clean_qt_payload_and_migration_pass(self):
        self.assertEqual(audit_package(self.control, self.members, self.scripts)["Version"], "0.5")

    def test_sudoers_file_and_even_empty_directory_fail(self):
        for path in ("etc/sudoers.d", "etc/sudoers.d/rule", "etc/sudoers"):
            with self.subTest(path=path), self.assertRaises(PackageAuditError):
                audit_package(self.control, self.members + [member(path)], self.scripts)

    def test_runtime_legacy_payload_fails(self):
        for path in ("usr/bin/mainuan-gestao-drivers-gtk-legacy", "usr/lib/gtk_legacy.py",
                     "usr/share/gtk-legacy.ui", "usr/lib/load-broadcom-modules", "usr/bin/mintdrivers",
                     "usr/share/xapp/resource"):
            with self.subTest(path=path), self.assertRaises(PackageAuditError):
                audit_package(self.control, self.members + [member(path)], self.scripts)

    def test_setuid_setgid_and_custom_policy_fail(self):
        for extra in (member("usr/lib/helper", 0o4755), member("usr/lib/helper", 0o2755),
                      member("usr/share/polkit-1/actions/org.mainuan.policy")):
            with self.subTest(path=extra.name), self.assertRaises(PackageAuditError):
                audit_package(self.control, self.members + [extra], self.scripts)

    def test_tests_probe_and_bytecode_are_never_installed(self):
        for path in ("usr/tests/manual/packagekit_mutation_probe.py", "usr/lib/probe.pyc",
                     "usr/lib/__pycache__/probe.pyo"):
            with self.subTest(path=path), self.assertRaises(PackageAuditError):
                audit_package(self.control, self.members + [member(path)], self.scripts)

    def test_legacy_dependencies_fail(self):
        for dependency in ("python3-gi", "gir1.2-xapp-1.0", "gir1.2-packagekitglib-1.0", "python3-psutil"):
            with self.subTest(dependency=dependency), self.assertRaises(PackageAuditError):
                audit_package(self.control.replace("Depends: ", "Depends: " + dependency + ", "), self.members, self.scripts)

    def test_missing_migration_phase_fails(self):
        for phase in self.scripts:
            with self.subTest(phase=phase), self.assertRaises(PackageAuditError):
                audit_package(self.control, self.members, {key: value for key, value in self.scripts.items() if key != phase})

    def test_native_remove_on_upgrade_is_supported(self):
        audit_package(self.control, self.members, {}, "remove-on-upgrade " + OBSOLETE_CONFFILE)

    def test_debhelper_shell_escaping_preserves_migration_version(self):
        scripts = {name: text.replace("0.5~", r"0.5\~") for name, text in self.scripts.items()}
        audit_package(self.control, self.members, scripts)

    def test_wrong_version_or_missing_direct_apt_dependency_fails(self):
        for control in (self.control.replace("Version: 0.5", "Version: 0.4"),
                        self.control.replace("python3-apt, ", "")):
            with self.assertRaises(PackageAuditError):
                audit_package(control, self.members, self.scripts)

    def test_only_one_frontend_and_manual(self):
        for extra in (member("usr/bin/another-manager"), member("usr/share/applications/another.desktop"),
                      member("usr/share/man/man1/another.1.gz")):
            with self.assertRaises(PackageAuditError):
                audit_package(self.control, self.members + [extra], self.scripts)

    def test_domain_is_only_mainuan(self):
        audit_package(self.control, self.members + [member("usr/share/locale/pt_BR/LC_MESSAGES/" + PACKAGE + ".mo")], self.scripts)
        with self.assertRaises(PackageAuditError):
            audit_package(self.control, self.members + [member("usr/share/locale/pt_BR/LC_MESSAGES/mintdrivers.mo")], self.scripts)

    def test_historical_document_names_are_not_runtime_frontends(self):
        audit_package(self.control, self.members + [member("usr/share/doc/" + PACKAGE + "/beta-0.4-testing.md.gz")], self.scripts)

    def test_removed_source_files_and_symlink_are_absent(self):
        for path in ("usr/bin/mainuan-gestao-drivers-gtk-legacy", "usr/lib/mainuan/mainuan-gestao-drivers/gtk_legacy.py",
                     "usr/lib/mainuan/mainuan-gestao-drivers/load-broadcom-modules",
                     "usr/share/mainuan/mainuan-gestao-drivers/gtk-legacy.ui",
                     "usr/share/man/man1/mainuan-gestao-drivers-gtk-legacy.1", OBSOLETE_CONFFILE.lstrip("/")):
            self.assertFalse(os.path.lexists(ROOT / path), path)
        self.assertFalse(any((ROOT / "etc").rglob("*sudoers*")) and
                         any(path.is_file() for path in (ROOT / "etc").rglob("*")))

    def test_distribution_dependencies_and_compat_13(self):
        source, binary = [Parser().parsestr(stanza) for stanza in (ROOT / "debian/control").read_text().strip().split("\n\n")]
        self.assertIn("debhelper-compat (= 13)", source["Build-Depends"])
        self.assertEqual(source["Rules-Requires-Root"], "no")
        self.assertFalse((ROOT / "debian/compat").exists())
        for legacy in ("python3-gi", "gir1.2-xapp", "gir1.2-packagekitglib", "python3-psutil"):
            self.assertNotIn(legacy, binary["Depends"])
        self.assertIn("python3-apt", binary["Depends"])
        self.assertEqual((ROOT / "debian/install").read_text().strip(), "usr")

    def test_conffile_migration_is_declarative_and_version_limited(self):
        text = (ROOT / "debian/mainuan-gestao-drivers.maintscript").read_text().strip()
        self.assertEqual(text, "rm_conffile %s 0.5~ %s" % (OBSOLETE_CONFFILE, PACKAGE))
        for script in ("preinst", "postinst", "prerm", "postrm"):
            self.assertFalse((ROOT / "debian" / script).exists())

    def test_shared_icons_preserved_and_offline_icon_removed(self):
        icons = ROOT / "usr/share/mainuan/mainuan-gestao-drivers/icons"
        self.assertEqual({path.stem for path in icons.glob("*.svg")},
                         {"amd", "ati", "broadcom", "generic", "intel", "nvidia", "virtualbox"})
        self.assertFalse((ROOT / "usr/share/icons/hicolor/scalable/status/mainuan-gestao-drivers-offline-symbolic.svg").exists())

    def test_gettext_sources_are_only_active_python(self):
        text = (ROOT / "makepot").read_text()
        self.assertNotIn("gtk_legacy", text)
        self.assertNotIn("Glade", text)
        self.assertNotIn("gtk-legacy", (ROOT / "mainuan-gestao-drivers.pot").read_text())

    def test_runtime_python_has_no_gtk_imports(self):
        forbidden = {"gi", "Gtk", "Gdk", "GdkPixbuf", "XApp", "PackageKitGlib", "GLib", "Gio", "psutil"}
        for path in MODULES.rglob("*.py"):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                modules = [alias.name for alias in node.names] if isinstance(node, ast.Import) else (
                    [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
                self.assertFalse(any(set(name.split(".")) & forbidden for name in modules), str(path))

    def test_official_frontend_runtime_and_all_test_snapshots_are_qt_only(self):
        check = r'''
import sys
sys.path.insert(0, sys.argv[1])
from PyQt6.QtCore import QTimer
from mainuan_drivers.qt import application
from mainuan_drivers.qt.main_window import MainWindow
from mainuan_drivers.backend.transactions.execution import SnapshotSource
from mainuan_drivers.backend.test_scenarios import SCENARIOS
factory = application.QApplication
def create(argv):
    app = factory(argv)
    QTimer.singleShot(0, app.quit)
    return app
application.QApplication = create
application.MainWindow = lambda test_mode: MainWindow(test_mode=test_mode, auto_start=False)
assert application.run(['mainuan-gestao-drivers', 'test']) == 0
for scenario, label in SCENARIOS:
    assert SnapshotSource(test_mode=True, scenario=scenario).load().planner.preview_only
blocked = {'gi', 'Gtk', 'Gdk', 'GdkPixbuf', 'XApp', 'PackageKitGlib', 'GLib', 'Gio'}
assert not any(set(name.split('.')) & blocked for name in sys.modules)
'''
        result = subprocess.run([sys.executable, "-c", check, str(MODULES)], timeout=15,
                                env={**os.environ, "QT_QPA_PLATFORM": "offscreen"}, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
