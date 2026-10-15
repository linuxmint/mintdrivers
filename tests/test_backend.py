import sys
import subprocess
import unittest
from pathlib import Path

sys.path.insert(0, str(
    Path(__file__).resolve().parents[1] / "usr/lib/mainuan/mainuan-gestao-drivers"))

from mainuan_drivers.backend import DeviceStatus, DriverBackend, DriverOptionType


class FakeVersion:
    def __init__(self, package, version, summary):
        self.package = package
        self.version = version
        self.summary = summary


class FakePackage:
    def __init__(self, name, installed=False, dependencies=()):
        self.shortname = name
        self.is_installed = installed
        self.installed = FakeVersion(self, "1.0-installed", "Installed summary") if installed else None
        self.candidate = FakeVersion(self, "2.0-candidate", "Candidate summary")
        self.candidate.dependencies = dependencies

    def architecture(self):
        return "amd64"


class FakeDependency:
    def __init__(self, name, rawtype="Depends"):
        self.name = name
        self.rawtype = rawtype


class FakeCache(dict):
    pass


def driver(recommended=False, free=False, builtin=False, from_distro=True):
    return {
        "recommended": recommended,
        "from_distro": from_distro,
        "free": free,
        "builtin": builtin,
    }


def make_backend(devices, packages=None, extra_devices=None, package_overrides=None):
    return DriverBackend(
        devices=devices,
        cache=FakeCache(packages or {}),
        extra_devices=extra_devices,
        package_overrides=package_overrides)


def find_device(backend, device_id="device"):
    return next(device for device in backend.get_devices() if device.device_id == device_id)


class DriverBackendTests(unittest.TestCase):
    def test_import_does_not_load_graphical_toolkits(self):
        module_path = Path(__file__).resolve().parents[1] / "usr/lib/mainuan/mainuan-gestao-drivers"
        check = (
            "import sys; sys.path.insert(0, %r); import mainuan_drivers.backend; "
            "blocked = ('gi.repository.Gtk', 'gi.repository.Gdk', "
            "'gi.repository.GdkPixbuf', 'gi.repository.XApp', 'apt', 'apt_pkg', "
            "'UbuntuDrivers', 'UbuntuDrivers.detect'); "
            "assert not any(name in sys.modules for name in blocked), "
            "set(sys.modules).intersection(blocked)"
        ) % str(module_path)
        subprocess.run([sys.executable, "-c", check], check=True)

    def test_recommended_and_alternative_package_options(self):
        raw_devices = {
            "device": {
                "vendor": "Example",
                "model": "Adapter",
                "drivers": {
                    "recommended-driver": driver(recommended=True),
                    "alternative-driver": driver(),
                },
            },
        }
        packages = {
            "recommended-driver": FakePackage("recommended-driver"),
            "alternative-driver": FakePackage("alternative-driver"),
        }
        device = find_device(make_backend(raw_devices, packages))
        options = {option.package_name: option for option in device.drivers}
        self.assertTrue(options["recommended-driver"].recommended)
        self.assertEqual(options["recommended-driver"].status, DeviceStatus.RECOMMENDED)
        self.assertFalse(options["alternative-driver"].recommended)
        self.assertEqual(options["alternative-driver"].status, DeviceStatus.ALTERNATIVE)
        self.assertTrue(next(o for o in device.drivers if o.option_type == DriverOptionType.DISABLE).selected)

    def test_detector_is_injectable_without_loading_system_detector(self):
        calls = []

        def detector():
            calls.append(True)
            return {"device": {"drivers": {}}}

        backend = DriverBackend(detector=detector, cache=FakeCache())
        self.assertEqual(find_device(backend).device_id, "device")
        self.assertEqual(calls, [True])

    def test_installed_package_is_selected_and_uninstalled_package_is_not(self):
        raw_devices = {"device": {"drivers": {
            "installed-driver": driver(),
            "available-driver": driver(recommended=True),
        }}}
        packages = {
            "installed-driver": FakePackage("installed-driver", installed=True),
            "available-driver": FakePackage("available-driver"),
        }
        options = {o.package_name: o for o in find_device(make_backend(raw_devices, packages)).drivers}
        self.assertTrue(options["installed-driver"].installed)
        self.assertTrue(options["installed-driver"].selected)
        self.assertFalse(options["available-driver"].installed)
        self.assertFalse(options["available-driver"].selected)

    def test_builtin_is_selected_without_being_reported_as_an_installed_package(self):
        raw_devices = {"device": {"drivers": {
            "builtin-driver": driver(free=True, builtin=True),
            "optional-driver": driver(),
        }}}
        packages = {
            "builtin-driver": FakePackage("builtin-driver", installed=True),
            "optional-driver": FakePackage("optional-driver"),
        }
        device = find_device(make_backend(raw_devices, packages))
        builtin = next(o for o in device.drivers if o.package_name == "builtin-driver")
        self.assertTrue(builtin.builtin)
        self.assertFalse(builtin.installed)
        self.assertTrue(builtin.selected)
        self.assertFalse(any(o.option_type == DriverOptionType.DISABLE for o in device.drivers))

    def test_device_without_drivers_has_selected_no_driver_option(self):
        device = find_device(make_backend({"device": {"drivers": {}}}))
        option = next(o for o in device.drivers if o.option_type == DriverOptionType.DISABLE)
        self.assertTrue(option.selected)
        self.assertEqual(device.status, DeviceStatus.NO_DRIVER)

    def test_manual_install_is_explicit_and_blocks_automatic_selection(self):
        raw_devices = {"device": {
            "manual_install": True,
            "drivers": {"candidate-driver": driver()},
        }}
        packages = {"candidate-driver": FakePackage("candidate-driver", installed=True)}
        device = find_device(make_backend(raw_devices, packages))
        manual = next(o for o in device.drivers if o.option_type == DriverOptionType.MANUAL)
        candidate = next(o for o in device.drivers if o.package_name == "candidate-driver")
        self.assertTrue(manual.selected)
        self.assertEqual(device.status, DeviceStatus.MANUALLY_INSTALLED)
        self.assertFalse(candidate.selected)

    def test_microcode_devices_keep_cpu_identity_and_semantic_icon(self):
        for package_name, expected_icon in (
                ("intel-microcode", "intel"), ("amd64-microcode", "amd")):
            device = find_device(make_backend(
                {"device": {"drivers": {package_name: driver(recommended=True)}}},
                {package_name: FakePackage(package_name)}))
            self.assertTrue(device.is_cpu)
            self.assertEqual(device.icon_key, expected_icon)

    def test_virtual_machine_device_identity_is_classified_by_backend(self):
        device = find_device(make_backend({
            "device": {"vendor": "Oracle", "model": "VirtualBox adapter", "drivers": {}},
        }))
        self.assertTrue(device.is_virtual)

    def test_nvidia_server_variants_are_ignored(self):
        names = (
            "nvidia-driver-550-server",
            "nvidia-driver-550-server-open",
            "nvidia-driver-550",
        )
        raw = {"device": {"vendor": "NVIDIA", "drivers": {name: driver() for name in names}}}
        packages = {name: FakePackage(name) for name in names}
        device = find_device(make_backend(raw, packages))
        self.assertEqual([o.package_name for o in device.drivers if o.package_name], ["nvidia-driver-550"])

    def test_nvidia_closed_driver_is_preferred_before_560_without_mutating_detection_data(self):
        closed = "nvidia-driver-550"
        opened = "nvidia-driver-550-open"
        raw = {"device": {"drivers": {
            closed: driver(),
            opened: driver(recommended=True),
        }}}
        packages = {name: FakePackage(name) for name in (closed, opened)}
        device = find_device(make_backend(raw, packages))
        options = {o.package_name: o for o in device.drivers if o.package_name}
        self.assertEqual(set(options), {closed})
        self.assertTrue(options[closed].recommended)
        self.assertFalse(raw["device"]["drivers"][closed]["recommended"])
        self.assertTrue(raw["device"]["drivers"][opened]["recommended"])

    def test_nvidia_open_driver_is_preferred_from_560(self):
        closed = "nvidia-driver-560"
        opened = "nvidia-driver-560-open"
        raw = {"device": {"drivers": {
            closed: driver(recommended=True),
            opened: driver(recommended=True),
        }}}
        packages = {name: FakePackage(name) for name in (closed, opened)}
        device = find_device(make_backend(raw, packages))
        options = {o.package_name: o for o in device.drivers if o.package_name}
        self.assertEqual(set(options), {opened})

    def test_test_device_flows_through_backend_as_display_only_options(self):
        from mainuan_drivers.backend.drivers import TEST_PACKAGE_OVERRIDES, make_test_device
        backend = make_backend(
            {}, extra_devices={"dummy": make_test_device()},
            package_overrides=TEST_PACKAGE_OVERRIDES)
        device = find_device(backend, "dummy")
        options = {o.package_name: o for o in device.drivers if o.package_name}
        self.assertIn("mint-dev-pkg", options)
        self.assertTrue(options["mint-dev-pkg"].recommended)
        self.assertFalse(options["mint-dev-pkg"].selectable)
        self.assertTrue(any(o.builtin for o in options.values()))

    def test_packagekit_ids_and_nvidia_dependency_resolution_stay_in_backend(self):
        main = FakePackage("nvidia-driver-550", installed=True, dependencies=[
            [FakeDependency("libnvidia-extra"), FakeDependency("nvidia-common-doc", "Suggests")],
        ])
        dependency = FakePackage("libnvidia-extra", installed=True)
        cache = FakeCache({
            "nvidia-driver-550": main,
            "libnvidia-extra": dependency,
        })
        backend = make_backend({}, packages=cache)
        self.assertEqual(
            backend.get_packagekit_id("nvidia-driver-550", installed=True),
            "nvidia-driver-550;1.0-installed;amd64;")
        self.assertEqual(
            backend.get_packagekit_id("nvidia-driver-550", installed=False),
            "nvidia-driver-550;2.0-candidate;amd64;")
        self.assertEqual(
            backend.get_installed_nvidia_dependency_ids("nvidia-driver-550"),
            ["libnvidia-extra;1.0-installed;amd64;"])


if __name__ == "__main__":
    unittest.main()
