# SPDX-License-Identifier: GPL-2.0-or-later
import re
from pathlib import Path

from ..drivers import PackageUnavailableError
from ..models import DriverOptionType
from .models import (
    DriverSelection, PackageReference, RestartRequirement,
    TransactionAction, TransactionPlan,
)


class PlanningError(ValueError):
    pass


def validate_package_name(name):
    if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9][a-z0-9+.-]+", name):
        raise PlanningError("Invalid driver package name")


def package_identity(package_id):
    if not isinstance(package_id, str):
        raise PlanningError("Invalid PackageKit ID")
    parts = package_id.split(";")
    if len(parts) != 4 or not parts[1] or not re.fullmatch(r"[a-z0-9_-]+", parts[2]):
        raise PlanningError("Invalid PackageKit ID")
    validate_package_name(parts[0])
    if any(char.isspace() or ord(char) < 32 for char in package_id):
        raise PlanningError("Invalid PackageKit ID")
    return tuple(parts[:3])


def reboot_required(path="/var/run/reboot-required"):
    """Read the system marker without performing a restart."""
    return Path(path).exists()


class TransactionPlanner:
    """Plan only choices belonging to a backend device snapshot.

    Build the snapshot in the detection worker. No APT objects are retained,
    and build()/validate_plan() perform no I/O on the GUI thread.
    """

    def __init__(self, devices, packages=None, nvidia_dependencies=None, preview_only=False):
        self.devices = tuple(devices)
        self._devices = {device.device_id: device for device in self.devices}
        if len(self._devices) != len(self.devices):
            raise PlanningError("Duplicate device ID")
        self._packages = dict(packages or {})
        self._nvidia_dependencies = dict(nvidia_dependencies or {})
        self.preview_only = preview_only
        for device in self.devices:
            for option in device.drivers:
                if option.package_name:
                    validate_package_name(option.package_name)
        for reference in list(self._packages.values()) + [
                ref for refs in self._nvidia_dependencies.values() for ref in refs]:
            validate_package_name(reference.name)
            if reference.package_id and package_identity(reference.package_id)[0] != reference.name:
                raise PlanningError("Package name and ID disagree")

    @classmethod
    def from_backend(cls, backend, devices, preview_only=False):
        packages = {}
        dependencies = {}
        for device in devices:
            for option in device.drivers:
                if option.option_type != DriverOptionType.PACKAGE or option.builtin:
                    continue
                name = option.package_name
                validate_package_name(name)
                for installed in (False, True) if option.installed else (False,):
                    try:
                        package_id = backend.get_packagekit_id(name, installed)
                    except PackageUnavailableError:
                        package_id = None
                    packages[(name, installed)] = PackageReference(name, package_id)
                if option.installed and "nvidia" in name:
                    dependencies[name] = tuple(
                        PackageReference(package_identity(package_id)[0], package_id)
                        for package_id in backend.get_installed_nvidia_dependency_ids(name)
                    )
        return cls(devices, packages, dependencies, preview_only)

    def _package(self, name, installed):
        return self._packages.get((name, installed), PackageReference(name, None))

    def build(self, desired=None):
        desired = dict(desired or {})
        if set(desired) - set(self._devices):
            raise PlanningError("Unknown device")
        installs, removals, retained, selections = {}, {}, set(), []
        preview = self.preview_only
        for device in self.devices:
            current_options = [option for option in device.drivers if option.selected]
            if len(current_options) != 1:
                raise PlanningError("A device must have exactly one current driver")
            current = current_options[0]
            target = desired.get(device.device_id, current)
            if target not in device.drivers:
                raise PlanningError("Target is not a driver option for this device")
            if target.package_name and not target.builtin:
                retained.add(target.package_name)
            if target == current:
                continue
            if current.option_type == DriverOptionType.MANUAL or target.option_type == DriverOptionType.MANUAL:
                raise PlanningError("Manually installed drivers cannot be changed automatically")
            if not target.selectable:
                if not self.preview_only:
                    raise PlanningError("Driver option cannot be selected")
                preview = True
            has_install = target.option_type == DriverOptionType.PACKAGE and not target.builtin
            has_remove = current.option_type == DriverOptionType.PACKAGE and not current.builtin
            if has_install and not target.installed:
                installs[target.package_name] = self._package(target.package_name, False)
            if has_remove and current.installed:
                removals[current.package_name] = self._package(current.package_name, True)
                for ref in self._nvidia_dependencies.get(current.package_name, ()):
                    removals[ref.name] = ref
            action = (TransactionAction.SWITCH if has_install and has_remove else
                      TransactionAction.INSTALL if has_install else TransactionAction.REMOVE)
            selections.append(DriverSelection(device.device_id, current, target, action))
        # A shared package still chosen by another device must survive the plan.
        removals = {name: ref for name, ref in removals.items() if name not in retained}
        if set(installs) & set(removals):
            raise PlanningError("Conflicting installation and removal")
        action = (TransactionAction.SWITCH if installs and removals else
                  TransactionAction.INSTALL if installs else
                  TransactionAction.REMOVE if removals else TransactionAction.NO_CHANGE)
        return TransactionPlan(
            tuple(selections), tuple(installs.values()), tuple(removals.values()), action,
            RestartRequirement.POSSIBLE if installs or removals else RestartRequirement.NONE,
            preview)

    def validate_plan(self, plan, executable=False):
        if not isinstance(plan, TransactionPlan):
            raise PlanningError("A driver transaction plan is required")
        desired = {selection.device_id: selection.target for selection in plan.selections}
        if len(desired) != len(plan.selections) or self.build(desired) != plan:
            raise PlanningError("Plan does not match the backend snapshot")
        if executable and (plan.preview_only or any(
                not package.package_id for package in plan.installs + plan.removals)):
            raise PlanningError("Preview or unavailable packages cannot be executed")
        return plan
