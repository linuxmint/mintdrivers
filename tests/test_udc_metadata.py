import unittest
from dataclasses import replace

from test_backend import FakePackage, make_backend
from mainuan_drivers.backend.transactions.planner import TransactionPlanner, PlanningError
from mainuan_drivers.backend.transactions.models import PackageReference


class UdcMetadataTests(unittest.TestCase):
    def backend(self, path="/sys/devices/pci/test", packages=None, explicit=None):
        option = {"recommended": True, "free": False, "from_distro": True}
        if packages is not None:
            option["packages"] = packages
        source = {"vendor": "NVIDIA", "model": "Test", "drivers": {"nvidia-driver-580": option}}
        if explicit is not None:
            source["sys_path"] = explicit
        return make_backend({path: source}, {name: FakePackage(name) for name in
                            ("nvidia-driver-580", "linux-modules-nvidia-580-generic")})

    def test_implicit_device_key_is_sys_path(self):
        self.assertEqual(self.backend().get_devices()[0].sys_path, "/sys/devices/pci/test")

    def test_explicit_sys_path_is_preserved(self):
        self.assertEqual(self.backend(path="device", explicit="/sys/devices/real").get_devices()[0].sys_path,
                         "/sys/devices/real")

    def test_plugin_without_sys_path_degrades_to_none(self):
        self.assertIsNone(self.backend(path="plugin-name").get_devices()[0].sys_path)

    def test_non_sysfs_and_traversal_are_rejected(self):
        for value in ("/etc", "/sys/../etc", "relative"):
            self.assertIsNone(self.backend(explicit=value).get_devices()[0].sys_path)

    def test_old_api_keeps_single_driver_plan(self):
        backend = self.backend()
        devices = backend.get_devices()
        planner = TransactionPlanner.from_backend(backend, devices)
        option = next(option for option in devices[0].drivers if option.recommended)
        self.assertIsNone(option.packages)
        self.assertEqual([ref.name for ref in planner.build({devices[0].device_id: option}).installs], ["nvidia-driver-580"])

    def test_optional_official_package_set_is_in_plan(self):
        names = ["nvidia-driver-580", "linux-modules-nvidia-580-generic"]
        backend = self.backend(packages=names + names)
        devices = backend.get_devices()
        planner = TransactionPlanner.from_backend(backend, devices)
        option = next(option for option in devices[0].drivers if option.recommended)
        self.assertEqual(option.packages, tuple(names))
        plan = planner.build({devices[0].device_id: option})
        self.assertEqual([ref.name for ref in plan.installs], names)
        planner.validate_plan(plan, executable=True)

    def test_malformed_optional_metadata_is_not_silently_guessed(self):
        for packages in ("driver", {"driver": True}, ["invalid;id"], ["--option"], []):
            with self.subTest(packages=packages), self.assertRaises(ValueError):
                self.backend(packages=packages).get_devices()

    def test_arbitrary_package_cannot_be_added_to_plan(self):
        backend = self.backend(packages=["linux-modules-nvidia-580-generic"])
        devices = backend.get_devices()
        planner = TransactionPlanner.from_backend(backend, devices)
        option = next(option for option in devices[0].drivers if option.recommended)
        plan = planner.build({devices[0].device_id: option})
        with self.assertRaises(PlanningError):
            planner.validate_plan(replace(plan, installs=plan.installs + (PackageReference("hello", "hello;1;all;"),)))
