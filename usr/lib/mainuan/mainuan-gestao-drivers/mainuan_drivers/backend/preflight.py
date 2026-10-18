# SPDX-License-Identifier: GPL-2.0-or-later
"""Read-only kernel/security evidence and policy. No Qt, GLib or mutation APIs."""
from dataclasses import dataclass
from enum import Enum
import gettext
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
from typing import Optional

_ = gettext.gettext


class SecureBootState(Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class DkmsState(Enum):
    NO_DKMS = "no_dkms"
    DKMS_REQUIRED = "dkms_required"
    DKMS_POSSIBLE = "dkms_possible"
    UNKNOWN = "unknown"


class KernelState(Enum):
    CURRENT = "current"
    OUTDATED = "outdated"
    UNKNOWN = "unknown"


class HeadersState(Enum):
    PRESENT = "present"
    MISSING = "missing"
    NOT_REQUIRED = "not_required"
    UNKNOWN = "unknown"


class MokState(Enum):
    ENROLLED = "enrolled"
    NOT_ENROLLED = "not_enrolled"
    PENDING = "pending"
    UNKNOWN = "unknown"


class ActivationState(Enum):
    ACTIVE = "active"  # Reserved: package success alone is never proof of this.
    INSTALLED_REBOOT_REQUIRED = "installed_reboot_required"
    INSTALLED_MOK_REQUIRED = "installed_mok_required"
    INSTALLED_NOT_ACTIVE = "installed_not_active"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class KernelModuleContext:
    secure_boot_state: SecureBootState = SecureBootState.UNKNOWN
    uefi: bool = False
    kernel_state: KernelState = KernelState.UNKNOWN
    running_kernel: str = ""
    latest_kernel: str = ""
    kernel_requires_dkms: Optional[bool] = None
    headers_state: HeadersState = HeadersState.UNKNOWN
    mok_state: MokState = MokState.UNKNOWN
    certificate: str = ""


@dataclass(frozen=True)
class ModuleEvidence:
    package_id: str
    dkms_state: DkmsState
    prebuilt_compatible: bool = False
    installed: bool = False
    roots: tuple = ()
    prebuilt_module: bool = False


@dataclass(frozen=True)
class PreflightIssue:
    code: str
    message: str


@dataclass(frozen=True)
class DriverPreflightResult:
    secure_boot_state: SecureBootState
    uefi: bool
    dkms_state: DkmsState
    kernel_state: KernelState
    headers_state: HeadersState
    mok_state: MokState
    warnings: tuple = ()
    blockers: tuple = ()
    requires_reboot: bool = False


@dataclass(frozen=True)
class DriverActivation:
    device_id: str
    package_name: str
    state: ActivationState


class KernelDetectionAdapter:
    """Isolate the installed UDC's non-guaranteed Python API; never use its CLI."""

    def __init__(self, factory=None):
        self.factory = factory

    def read(self):
        try:
            factory = self.factory
            if factory is None:
                from UbuntuDrivers.kerneldetection import KernelDetection
                factory = KernelDetection
            value = factory().is_running_kernel_outdated()
            if (not isinstance(value, tuple) or len(value) != 4 or type(value[0]) is not bool
                    or type(value[3]) is not bool or not isinstance(value[1], str)
                    or not re.fullmatch(r"[A-Za-z0-9_.+-]+", value[1])
                    or (value[2] is not None and not isinstance(value[2], str))):
                raise ValueError("Unsupported KernelDetection result")
            return (KernelState.OUTDATED if value[0] else KernelState.CURRENT,
                    value[1], value[2] or "", value[3])
        except Exception:
            return KernelState.UNKNOWN, os.uname().release, "", None


class SystemSecurityProbe:
    def __init__(self, efi_root="/sys/firmware/efi", modules_root="/lib/modules",
                 config_root="/etc/dkms", runner=subprocess.run, kernel_adapter=None):
        self.efi_root = Path(efi_root)
        self.modules_root = Path(modules_root)
        self.config_root = Path(config_root)
        self.runner = runner
        self.kernel_adapter = kernel_adapter or KernelDetectionAdapter()

    def _mokutil(self, *args):
        try:
            result = self.runner(["mokutil", *args], capture_output=True, text=True,
                                 timeout=10, check=False, env={**os.environ, "LC_ALL": "C"})
            return result.returncode, result.stdout.strip(), result.stderr.strip()
        except (OSError, subprocess.SubprocessError, UnicodeError):
            return None, "", ""

    def _certificate(self):
        # Configuration is shell syntax. Accept only static assignments, never
        # source/eval it and never guess which of Ubuntu's two defaults is used.
        certificate = ""
        try:
            files = [self.config_root / "framework.conf"]
            files += sorted((self.config_root / "framework.conf.d").glob("*.conf"))
            for path in files:
                if not path.exists():
                    continue
                for line in path.read_text().splitlines():
                    tokens = shlex.split(line, comments=True)
                    if not tokens:
                        continue
                    if len(tokens) != 1 or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=[^$`;<>|&]*", tokens[0]):
                        return ""
                    key, value = tokens[0].split("=", 1)
                    if key == "sign_file" and value:
                        return ""
                    if key == "mok_certificate":
                        certificate = value
            path = Path(certificate)
            return str(path) if path.is_absolute() and path.is_file() and path.read_bytes() else ""
        except (OSError, ValueError):
            return ""

    def probe(self):
        inaccessible_efi = False
        try:
            uefi = stat.S_ISDIR(self.efi_root.stat().st_mode)
        except FileNotFoundError:
            uefi = False
        except OSError:
            uefi, inaccessible_efi = False, True
        secure = SecureBootState.UNSUPPORTED
        if inaccessible_efi:
            secure = SecureBootState.UNKNOWN
        mok, certificate = MokState.UNKNOWN, ""
        if uefi:
            secure = SecureBootState.UNKNOWN
            code, output, error = self._mokutil("--sb-state")
            if code == 0 and output in ("SecureBoot enabled", "Secure Boot enabled"):
                secure = SecureBootState.ENABLED
            elif code == 0 and output in ("SecureBoot disabled", "Secure Boot disabled"):
                secure = SecureBootState.DISABLED
            code, output, error = self._mokutil("--list-new")
            if code == 0 and re.search(r"(?:SHA1|SHA256) Fingerprint:|(?:SHA1|SHA256)Fingerprint:", output):
                mok = MokState.PENDING
            elif code == 0 and not output:
                certificate = self._certificate()
                if certificate:
                    code, output, error = self._mokutil("--test-key", certificate)
                    if code == 0 and output == certificate + " is already enrolled":
                        mok = MokState.ENROLLED
                    elif code == 1 and output == certificate + " is not enrolled":
                        mok = MokState.NOT_ENROLLED
        kernel, running, latest, dkms = self.kernel_adapter.read()
        headers = HeadersState.UNKNOWN
        try:
            if re.fullmatch(r"[A-Za-z0-9_.+-]+", running):
                try:
                    build = self.modules_root / running / "build"
                    info = (build / "Makefile").stat()
                    release = (build / "include/config/kernel.release").read_text().strip()
                    headers = (HeadersState.PRESENT if stat.S_ISREG(info.st_mode) and release == running
                               else HeadersState.MISSING)
                except FileNotFoundError:
                    headers = HeadersState.MISSING
        except (OSError, UnicodeError):
            pass
        return KernelModuleContext(secure, uefi, kernel, running, latest, dkms, headers, mok, certificate)


def explicit_dkms(name):
    return name == "dkms" or name.endswith("-dkms") or "-dkms-" in name


def providers(cache, name):
    reader = getattr(cache, "get_providing_packages", None)
    return reader(name, include_nonvirtual=True) if reader else ()


def analyze_dkms(cache, package_name):
    known, visiting = {}, set()

    def requirement(name, depth=0):
        if name in known:
            return known[name]
        if depth > 64:
            return DkmsState.UNKNOWN
        if name in visiting:
            return DkmsState.NO_DKMS
        visiting.add(name)
        alternatives = [requirement(package.shortname, depth + 1) for package in providers(cache, name)
                        if package.shortname != name]
        if explicit_dkms(name):
            visiting.remove(name)
            return (DkmsState.DKMS_POSSIBLE if any(item != DkmsState.DKMS_REQUIRED for item in alternatives)
                    else DkmsState.DKMS_REQUIRED)
        try:
            candidate = cache[name].candidate
        except KeyError:
            candidate = None
        if candidate is None:
            visiting.remove(name)
            return (DkmsState.NO_DKMS if alternatives and all(item == DkmsState.NO_DKMS for item in alternatives)
                    else DkmsState.DKMS_POSSIBLE if alternatives and DkmsState.UNKNOWN not in alternatives
                    else DkmsState.UNKNOWN)
        groups = []
        for group in candidate.dependencies:
            alternatives = [requirement(dep.name, depth + 1) for dep in group
                            if dep.rawtype in ("Depends", "PreDepends")]
            if not alternatives:
                continue
            if all(item == DkmsState.DKMS_REQUIRED for item in alternatives):
                groups.append(DkmsState.DKMS_REQUIRED)
            elif all(item == DkmsState.NO_DKMS for item in alternatives):
                groups.append(DkmsState.NO_DKMS)
            elif DkmsState.UNKNOWN in alternatives:
                groups.append(DkmsState.UNKNOWN)
            else:
                groups.append(DkmsState.DKMS_POSSIBLE)
        visiting.remove(name)
        value = next((state for state in (DkmsState.DKMS_REQUIRED, DkmsState.UNKNOWN, DkmsState.DKMS_POSSIBLE)
                      if state in groups), DkmsState.NO_DKMS)
        if alternatives and any(item != value for item in alternatives):
            value = DkmsState.UNKNOWN if DkmsState.UNKNOWN in alternatives else DkmsState.DKMS_POSSIBLE
        known[name] = value
        return value

    return requirement(package_name)


def collect_module_evidence(backend, names, running_kernel):
    cache = backend._get_cache()
    pending, seen, evidence = [(name, name) for name in names], set(), []
    while pending:
        name, root = pending.pop()
        if (name, root) in seen:
            continue
        seen.add((name, root))
        pending.extend((package.shortname, root) for package in providers(cache, name)
                       if package.is_installed or (running_kernel and package.shortname.endswith("-" + running_kernel)))
        try:
            package = cache[name]
        except KeyError:
            continue
        for installed in (False, True) if package.is_installed else (False,):
            version = package.installed if installed else package.candidate
            if version is None:
                continue
            compatible = bool(
                running_kernel and name.startswith("linux-modules-nvidia-")
                and name.endswith("-" + running_kernel) and "unsigned" not in name
                and getattr(version, "source_name", "").startswith("linux-restricted-modules")
                and any(origin.origin == "Ubuntu" and origin.trusted for origin in getattr(version, "origins", ())))
            evidence.append(ModuleEvidence(backend.get_packagekit_id(name, installed),
                                          analyze_dkms(cache, name), compatible, installed, (root,),
                                          bool(name.startswith("linux-modules-nvidia-") and
                                               re.search(r"-\d+\.\d+\.\d+-\d+", name))))
            for group in getattr(version, "dependencies", ()):
                pending.extend((dep.name, root) for dep in group if dep.rawtype in ("Depends", "PreDepends"))
    return tuple(evidence)


class DriverPreflight:
    def __init__(self, context, evidence=()):
        self.context = context
        self.evidence = evidence

    def check(self, installs, resolved=False):
        context = self.context
        facts = {tuple(item.package_id.split(";")[:3]): item for item in self.evidence}
        states = []
        incompatible = False
        actual_ids = {tuple(ref.package_id.split(";")[:3]) for ref in installs if ref.package_id}
        for ref in installs:
            fact = facts.get(tuple(ref.package_id.split(";")[:3])) if ref.package_id else None
            incompatible = incompatible or bool(fact and fact.prebuilt_module and not fact.prebuilt_compatible)
            state = DkmsState.DKMS_REQUIRED if explicit_dkms(ref.name) else fact.dkms_state if fact else (
                DkmsState.DKMS_REQUIRED if ref.requires_dkms is True else
                DkmsState.NO_DKMS if ref.requires_dkms is False else DkmsState.UNKNOWN)
            if state == DkmsState.DKMS_POSSIBLE and resolved and any(
                    item.prebuilt_compatible and ref.name in item.roots and
                    (item.installed or tuple(item.package_id.split(";")[:3]) in actual_ids)
                    for item in self.evidence):
                state = DkmsState.NO_DKMS
            states.append(state)
        dkms = next((state for state in (DkmsState.DKMS_REQUIRED, DkmsState.UNKNOWN, DkmsState.DKMS_POSSIBLE)
                     if state in states), DkmsState.NO_DKMS)
        warnings, blockers = [], []
        if incompatible:
            blockers.append(PreflightIssue("prebuilt-incompatible", _("The prebuilt module does not have a verified Ubuntu source and matching running kernel.")))
        if installs and context.kernel_requires_dkms:
            warnings.append(PreflightIssue("kernel-dkms-hint", _("The running kernel is outside the standard prebuilt module update path. Verify module compatibility.")))
        if installs and context.kernel_state == KernelState.OUTDATED:
            warnings.append(PreflightIssue("kernel-outdated", _("A kernel update is pending. Review system updates before changing drivers.")))
        if installs and context.kernel_state == KernelState.UNKNOWN:
            warnings.append(PreflightIssue("kernel-unknown", _("The kernel update state could not be verified.")))
        if installs and context.mok_state == MokState.PENDING:
            warnings.append(PreflightIssue("mok-pending", _("Restart the computer and complete key enrollment in MokManager.")))
        uncertain = dkms in (DkmsState.DKMS_REQUIRED, DkmsState.DKMS_POSSIBLE, DkmsState.UNKNOWN)
        deferred = not resolved and dkms == DkmsState.DKMS_POSSIBLE
        if deferred:
            warnings.append(PreflightIssue("module-alternatives", _("PackageKit must resolve the prebuilt/DKMS module alternatives before confirmation.")))
        if uncertain and context.secure_boot_state in (SecureBootState.ENABLED, SecureBootState.UNKNOWN) and not deferred:
            blockers.append(PreflightIssue("secure-boot-dkms", _("This driver may need a DKMS module with Secure Boot active or unknown. "
                "MOK enrollment and module signing cannot be guaranteed by this beta, even with an enrolled key. No changes will be applied.")))
        if dkms in (DkmsState.DKMS_REQUIRED, DkmsState.DKMS_POSSIBLE) and not deferred:
            if context.headers_state != HeadersState.PRESENT:
                blockers.append(PreflightIssue("headers-missing", _("Headers for the running kernel are missing or unverified. Install matching headers through system updates before retrying.")))
        if dkms == DkmsState.UNKNOWN and context.secure_boot_state in (SecureBootState.DISABLED, SecureBootState.UNSUPPORTED):
            warnings.append(PreflightIssue("module-unknown", _("The module build requirements could not be fully verified.")))
        return DriverPreflightResult(context.secure_boot_state, context.uefi, dkms, context.kernel_state,
                                     context.headers_state if uncertain else HeadersState.NOT_REQUIRED,
                                     context.mok_state, tuple(warnings), tuple(blockers), bool(installs))


def assess_activation(plan, context, installed_packages, failed=False, evidence=()):
    """Fresh package state is necessary but never sufficient to claim ACTIVE."""
    results = []
    for selection in plan.selections:
        name = selection.target.package_name
        state = ActivationState.UNKNOWN
        if name and not selection.target.builtin:
            installed = dict(installed_packages).get(name)
            expected = next((ref for ref in plan.installs if ref.name == name), None)
            if installed is False:
                state = ActivationState.FAILED
            elif isinstance(installed, str) and expected and expected.package_id and (
                    installed.split(";")[:3] != expected.package_id.split(";")[:3]):
                state = ActivationState.UNKNOWN
            elif installed:
                if context.mok_state == MokState.PENDING:
                    state = ActivationState.INSTALLED_MOK_REQUIRED
                else:
                    ref = expected
                    check = DriverPreflight(context, evidence).check((ref,) if ref else (), resolved=True)
                    state = (ActivationState.INSTALLED_NOT_ACTIVE if check.blockers or failed else
                             ActivationState.INSTALLED_REBOOT_REQUIRED)
        results.append(DriverActivation(selection.device_id, name or "", state))
    return tuple(results)
