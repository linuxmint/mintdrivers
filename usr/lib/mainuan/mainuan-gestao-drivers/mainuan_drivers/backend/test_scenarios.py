# SPDX-License-Identifier: GPL-2.0-or-later
"""Explicit visual fixtures. Only SnapshotSource(test_mode=True) consumes these."""
from dataclasses import replace

from .preflight import (
    DkmsState, HeadersState, KernelModuleContext, KernelState, MokState, SecureBootState,
)
from .signing import SigningEvidence, SigningReadiness
from .activation import DeviceBinding

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
    ("secure-dkms-unrelated", N_("Secure Boot + DKMS + unrelated MOK")),
    ("secure-dkms-pending", N_("Secure Boot + DKMS + matching enrollment pending")),
    ("secure-dkms-unknown", N_("Secure Boot + DKMS + signing unknown")),
    ("activation-active", N_("Installed + driver active")),
    ("activation-reboot", N_("Installed + restart required")),
    ("activation-mok", N_("Installed + MOK enrollment required")),
    ("activation-unverified", N_("Installed + activation unverified")),
    ("activation-old-driver", N_("Installed + previous driver bound")),
    ("third-party-recommended", N_("Third-party recommended driver")),
    ("third-party-dkms", N_("Third-party DKMS driver")),
    ("live-session", N_("Live Session; changes blocked")),
    ("packagekit-unavailable", N_("PackageKit unavailable")),
    ("backend-error", N_("Driver detection error")),
    ("no-drivers", N_("No additional drivers")),
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
        readiness = {"secure-dkms-enrolled": SigningReadiness.READY_ENROLLED,
                     "secure-dkms-missing": SigningReadiness.CERTIFICATE_NOT_ENROLLED,
                     "secure-dkms-unrelated": SigningReadiness.CERTIFICATE_NOT_ENROLLED,
                     "secure-dkms-pending": SigningReadiness.PENDING_ENROLLMENT}.get(name, SigningReadiness.UNKNOWN)
        context = replace(context, signing=SigningEvidence(readiness, "/test/public.der"),
                          mok_state=MokState.PENDING if readiness == SigningReadiness.PENDING_ENROLLMENT else context.mok_state)
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
    if name == "activation-mok":
        context = replace(context, secure_boot_state=SecureBootState.ENABLED, mok_state=MokState.PENDING,
                          signing=SigningEvidence(SigningReadiness.PENDING_ENROLLMENT, "/test/public.der"))
    if name == "activation-unverified":
        target, alternatives = "generic-driver", []
    drivers = {package: {"recommended": package == target, "from_distro": True, "free": False}
               for package in [target, *alternatives]}
    if name.startswith("third-party"):
        drivers[target]["source"] = "third-party"
        state = DkmsState.NO_DKMS if name == "third-party-recommended" else DkmsState.DKMS_REQUIRED
    device = {"vendor": "Broadcom" if name == "broadcom" else "NVIDIA",
              "model": "Test adapter", "modalias": "", "drivers": drivers}
    overrides = {package: ("1.0", "Test driver", name.startswith("activation-") and package == target)
                 for package in drivers}
    states = {package: state for package in drivers}
    return {"security-test": device}, overrides, context, states


def scenario_bindings(name):
    """Synthetic evidence only; never inspect host sysfs or invoke modinfo."""
    if name == "activation-active":
        return (("security-test", DeviceBinding("nvidia", "nvidia", True)),)
    if name in ("activation-reboot", "activation-old-driver"):
        return (("security-test", DeviceBinding("nouveau", "nouveau", True)),)
    return ()
