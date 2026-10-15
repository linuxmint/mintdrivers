import subprocess
import sys
import unittest
from dataclasses import replace
from pathlib import Path

from test_backend import FakeDependency, FakePackage, driver, make_backend

from mainuan_drivers.backend import DeviceInfo, DriverOptionType
from mainuan_drivers.backend.transactions import (
    PackageReference, PlanningError, RestartRequirement, TransactionAction,
    TransactionPlanner,
)
from mainuan_drivers.backend.transactions.planner import package_identity, reboot_required


def scenario(installed=False, name="old-driver", device_id="device"):
    backend = make_backend({device_id: {"drivers": {
        name: driver(), "new-driver": driver(recommended=True),
        "linux-generic": driver(free=True, builtin=True),
    }}}, {
        name: FakePackage(name, installed),
        "new-driver": FakePackage("new-driver"),
        "linux-generic": FakePackage("linux-generic"),
    })
    devices = backend.get_devices()
    planner = TransactionPlanner.from_backend(backend, devices)
    return backend, devices[0], planner


def target(device, name):
    return next(option for option in device.drivers if option.package_name == name)


class TransactionPlannerTests(unittest.TestCase):
    def test_planner_import_has_no_qt_or_glib_dependency(self):
        root = str(Path(__file__).resolve().parents[1] / "usr/lib/mainuan/mainuan-gestao-drivers")
        subprocess.run([sys.executable, "-c",
                        "import sys; sys.path.insert(0, %r); import mainuan_drivers.backend.transactions; "
                        "assert not any(n == 'gi' or n.startswith('PyQt6') for n in sys.modules)" % root], check=True)

    def test_no_changes(self):
        _, _, planner = scenario()
        plan = planner.build()
        self.assertEqual(plan.action, TransactionAction.NO_CHANGE)
        self.assertEqual(plan.installs + plan.removals + plan.selections, ())

    def test_install(self):
        _, device, planner = scenario()
        plan = planner.build({device.device_id: target(device, "new-driver")})
        self.assertEqual(plan.action, TransactionAction.INSTALL)
        self.assertEqual(plan.installs[0].package_id, "new-driver;2.0-candidate;amd64;")
        self.assertEqual(plan.removals, ())
        self.assertEqual(plan.restart, RestartRequirement.POSSIBLE)

    def test_remove_to_builtin(self):
        _, device, planner = scenario(installed=True)
        plan = planner.build({device.device_id: target(device, "linux-generic")})
        self.assertEqual(plan.action, TransactionAction.REMOVE)
        self.assertEqual(plan.installs, ())
        self.assertEqual(plan.removals[0].package_id, "old-driver;1.0-installed;amd64;")

    def test_remove_to_disabled(self):
        backend = make_backend({"device": {"drivers": {"old-driver": driver()}}},
                               {"old-driver": FakePackage("old-driver", True)})
        device = backend.get_devices()[0]
        disabled = next(o for o in device.drivers if o.option_type == DriverOptionType.DISABLE)
        planner = TransactionPlanner.from_backend(backend, (device,))
        self.assertEqual(planner.build({"device": disabled}).action, TransactionAction.REMOVE)

    def test_switch_preserves_current_and_target(self):
        _, device, planner = scenario(installed=True)
        plan = planner.build({device.device_id: target(device, "new-driver")})
        self.assertEqual(plan.action, TransactionAction.SWITCH)
        self.assertEqual(plan.selections[0].current.package_name, "old-driver")
        self.assertEqual(plan.selections[0].target.package_name, "new-driver")

    def test_multiple_devices_aggregate_and_deduplicate(self):
        backend = make_backend({name: {"drivers": {
            "old-driver": driver(), "new-driver": driver(),
        }} for name in ("one", "two")}, {
            "old-driver": FakePackage("old-driver", True), "new-driver": FakePackage("new-driver"),
        })
        devices = backend.get_devices()
        planner = TransactionPlanner.from_backend(backend, devices)
        plan = planner.build({d.device_id: target(d, "new-driver") for d in devices})
        self.assertEqual(len(plan.selections), 2)
        self.assertEqual(len(plan.installs), 1)
        self.assertEqual(len(plan.removals), 1)
        retained = planner.build({"one": target(devices[0], "new-driver")})
        self.assertEqual(retained.removals, ())

    def test_nvidia_dependencies_use_existing_backend_rule(self):
        backend, device, _ = scenario(True, "nvidia-driver-550")
        main = backend._get_cache()["nvidia-driver-550"]
        main.candidate.dependencies = [[FakeDependency("libnvidia-extra"),
                                        FakeDependency("nvidia-doc", "Suggests")]]
        backend._get_cache()["libnvidia-extra"] = FakePackage("libnvidia-extra", True)
        backend._get_cache()["nvidia-doc"] = FakePackage("nvidia-doc", True)
        planner = TransactionPlanner.from_backend(backend, (device,))
        plan = planner.build({device.device_id: target(device, "linux-generic")})
        self.assertEqual([ref.name for ref in plan.removals], ["nvidia-driver-550", "libnvidia-extra"])

    def test_rejects_arbitrary_option_and_forged_plan(self):
        _, device, planner = scenario()
        option = target(device, "new-driver")
        with self.assertRaises(PlanningError):
            planner.build({"device": replace(option, package_name="unrelated-package")})
        plan = planner.build({"device": option})
        with self.assertRaises(PlanningError):
            planner.validate_plan(replace(plan, installs=(PackageReference("unrelated-package", "unrelated-package;1;amd64;"),)))
        with self.assertRaises(PlanningError):
            planner.build({"external-device": option})

    def test_rejects_two_active_drivers(self):
        _, device, _ = scenario(True)
        device = replace(device, drivers=tuple(replace(o, selected=True) for o in device.drivers))
        with self.assertRaises(PlanningError):
            TransactionPlanner((device,)).build()

    def test_manual_changes_are_blocked(self):
        backend = make_backend({"device": {"manual_install": True, "drivers": {
            "linux-generic": driver(builtin=True), "new-driver": driver(),
        }}}, {"linux-generic": FakePackage("linux-generic"), "new-driver": FakePackage("new-driver")})
        device = backend.get_devices()[0]
        # The planner also rejects any inconsistent legacy snapshot.
        device = replace(device, drivers=tuple(replace(o, selected=o.option_type == DriverOptionType.MANUAL)
                                              for o in device.drivers))
        with self.assertRaises(PlanningError):
            TransactionPlanner((device,)).build({"device": target(device, "new-driver")})

    def test_preview_and_unavailable_ids_cannot_execute(self):
        _, device, _ = scenario()
        planner = TransactionPlanner((device,), preview_only=True)
        plan = planner.build({"device": target(device, "new-driver")})
        self.assertEqual(plan.installs[0].name, "new-driver")
        with self.assertRaises(PlanningError):
            planner.validate_plan(plan, executable=True)
        planner = TransactionPlanner((device,))
        plan = planner.build({"device": target(device, "new-driver")})
        with self.assertRaises(PlanningError):
            planner.validate_plan(plan, executable=True)

    def test_ids_and_reboot_marker(self):
        self.assertEqual(package_identity("driver-name;1.0;amd64;installed"), ("driver-name", "1.0", "amd64"))
        for invalid in ("bad", "driver;1;amd64;extra;field", "driver;;amd64;", "bad name;1;amd64;"):
            with self.assertRaises(PlanningError):
                package_identity(invalid)
        self.assertFalse(reboot_required("/definitely-missing-mainuan-drivers-marker"))

