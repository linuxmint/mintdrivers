# SPDX-License-Identifier: GPL-2.0-or-later
"""Read-only device binding evidence, never bind/unbind or load modules."""
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess

from .signing import SigningReadiness, read_command


@dataclass(frozen=True)
class DeviceBinding:
    driver: str = ""
    module: str = ""
    verified: bool = False
    filename: str = ""
    signer: str = ""
    sig_key: str = ""
    sig_hashalgo: str = ""


class DriverActivationProbe:
    def __init__(self, sys_root="/sys", runner=subprocess.run):
        self.sys_root = Path(sys_root)
        self.runner = runner

    def probe(self, sys_path):
        if not sys_path:
            return DeviceBinding()
        try:
            root = self.sys_root.resolve(strict=True)
            device = Path(sys_path).resolve(strict=True)
            if root not in device.parents or not device.is_dir():
                return DeviceBinding()
            link = device / "driver"
            if not link.is_symlink():
                return DeviceBinding()
            driver = link.resolve(strict=True)
            if root not in driver.parents or not driver.is_dir():
                return DeviceBinding()
            module = ""
            module_link = driver / "module"
            if module_link.is_symlink():
                target = module_link.resolve(strict=True)
                if root in target.parents and target.is_dir():
                    module = target.name
            facts = {}
            if module and re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_+-]*", module):
                code, output, error = read_command(self.runner, ["modinfo", module])
                if code == 0 and not error:
                    for line in output.splitlines():
                        key, separator, value = line.partition(":")
                        if separator and key in ("filename", "signer", "sig_key", "sig_hashalgo"):
                            facts[key] = value.strip()
            return DeviceBinding(driver.name, module, True, **facts)
        except (OSError, RuntimeError, ValueError):
            return DeviceBinding()


def activation_state(package, binding, before, context, dkms, changing=False):
    from .preflight import ActivationState, DkmsState, SecureBootState
    expected = ("nvidia" if package.startswith("nvidia-driver-") else
                "wl" if package in ("broadcom-sta-dkms", "bcmwl-kernel-source") else "")
    if not expected:
        return ActivationState.INSTALLED_ACTIVATION_UNVERIFIED
    if not binding or not binding.verified:
        return ActivationState.INSTALLED_ACTIVATION_UNVERIFIED
    if binding.driver != expected or (binding.module and binding.module != expected):
        return ActivationState.INSTALLED_REBOOT_REQUIRED
    if changing and (not before or not before.verified):
        return ActivationState.INSTALLED_ACTIVATION_UNVERIFIED
    # A loaded nvidia module cannot distinguish branches or open/closed variants.
    if changing and before and before.verified and before.driver == binding.driver:
        return ActivationState.INSTALLED_REBOOT_REQUIRED
    if context.secure_boot_state == SecureBootState.UNKNOWN and dkms != DkmsState.NO_DKMS:
        return ActivationState.INSTALLED_ACTIVATION_UNVERIFIED
    if context.secure_boot_state == SecureBootState.ENABLED and dkms != DkmsState.NO_DKMS:
        if (context.signing.state != SigningReadiness.READY_ENROLLED
                or not binding.signer or not binding.sig_hashalgo or not context.signing.key_id
                or binding.sig_key.replace(":", "").lower() != context.signing.key_id):
            return ActivationState.INSTALLED_ACTIVATION_UNVERIFIED
    return ActivationState.ACTIVE_CONFIRMED
