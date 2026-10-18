# SPDX-License-Identifier: GPL-2.0-or-later
"""Explicit visual fixtures. Only SnapshotSource(test_mode=True) consumes these."""
from dataclasses import replace

from .preflight import (
    DkmsState, HeadersState, KernelModuleContext, KernelState, MokState, SecureBootState,
)

N_ = lambda text: text
SCENARIOS = (
    ("default", N_("General devices")),
    ("secure-prebuilt", N_("Secure Boot + prebuilt module")),
    ("secure-dkms-enrolled", N_("Secure Boot + DKMS + enrolled MOK")),
    ("secure-dkms-missing", N_("Secure Boot + DKMS + missing MOK")),
    ("disabled-dkms", N_("Secure Boot disabled + DKMS")),
    ("unknown-dkms", N_("Secure Boot unknown + DKMS")),
    ("broadcom", N_("Broadcom DKMS")),
    ("nvidia-pin", N_("NVIDIA custom closed pin")),
    ("nvidia-open", N_("NVIDIA open recommended")),
    ("nvidia-closed", N_("NVIDIA closed recommended")),
    ("nvidia-server", N_("NVIDIA server recommended")),
    ("kernel-outdated", N_("Kernel update pending")),
    ("headers-missing", N_("Kernel headers missing")),
    ("mok-pending", N_("MOK enrollment pending")),
)


def scenario_data(name):
    if name not in dict(SCENARIOS) or name == "default":
        raise ValueError("Unknown security test scenario")
    context = KernelModuleContext(SecureBootState.DISABLED, True, KernelState.CURRENT,
                                  "6.20.0-1-generic", "", False, HeadersState.PRESENT)
    state = DkmsState.DKMS_REQUIRED
    target = "nvidia-driver-580"
    alternatives = ["nvidia-driver-580-open"]
    if name in ("secure-prebuilt", "mok-pending"):
        target, state = "nvidia-driver-580-open", DkmsState.NO_DKMS
        alternatives = ["nvidia-driver-580"]
        context = replace(context, secure_boot_state=SecureBootState.ENABLED)
    elif name.startswith("secure-dkms"):
        context = replace(context, secure_boot_state=SecureBootState.ENABLED,
                          mok_state=MokState.ENROLLED if name.endswith("enrolled") else MokState.NOT_ENROLLED)
    elif name == "unknown-dkms":
        context = replace(context, secure_boot_state=SecureBootState.UNKNOWN)
    elif name == "broadcom":
        target, alternatives = "broadcom-sta-dkms", []
    elif name == "nvidia-open":
        target, alternatives = "nvidia-driver-580-open", ["nvidia-driver-580"]
    elif name == "nvidia-pin":
        alternatives.append("nvidia-driver-590-open")
    elif name == "nvidia-server":
        target, alternatives = "nvidia-driver-470-server", ["nvidia-driver-535"]
    elif name == "kernel-outdated":
        context = replace(context, kernel_state=KernelState.OUTDATED, latest_kernel="6.20.0-2-generic")
    elif name == "headers-missing":
        context = replace(context, headers_state=HeadersState.MISSING)
    if name == "mok-pending":
        context = replace(context, mok_state=MokState.PENDING)
    drivers = {package: {"recommended": package == target, "from_distro": True, "free": False}
               for package in [target, *alternatives]}
    device = {"vendor": "Broadcom" if name == "broadcom" else "NVIDIA",
              "model": "Test adapter", "modalias": "", "drivers": drivers}
    overrides = {package: ("1.0", "Test driver", False) for package in drivers}
    states = {package: state for package in drivers}
    return {"security-test": device}, overrides, context, states
