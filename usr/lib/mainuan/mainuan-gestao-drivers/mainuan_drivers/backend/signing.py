# SPDX-License-Identifier: GPL-2.0-or-later
"""Read-only discovery of the certificate DKMS will actually use.

No private key contents are read, and configuration is never executed.
"""
from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess


class SigningReadiness(Enum):
    NOT_REQUIRED = "not_required"
    READY_ENROLLED = "ready_enrolled"
    CERTIFICATE_NOT_ENROLLED = "certificate_not_enrolled"
    PENDING_ENROLLMENT = "pending_enrollment"
    CERTIFICATE_NOT_FOUND = "certificate_not_found"
    MOKUTIL_UNAVAILABLE = "mokutil_unavailable"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SigningEvidence:
    state: SigningReadiness = SigningReadiness.UNKNOWN
    certificate: str = ""
    fingerprint: str = ""
    reason: str = ""
    key_id: str = ""


def read_command(runner, argv):
    try:
        result = runner(argv, capture_output=True, text=True, timeout=10, check=False,
                        env={**os.environ, "LC_ALL": "C"})
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except FileNotFoundError:
        return None, "", "unavailable"
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return None, "", "unknown"


class DkmsDefaultsAdapter:
    """Only the audited distro package's selection semantics are recognized.

    A new DKMS implementation needs an adapter audit, not a guessed default.
    Explicit configs still need this contract: Ubuntu ignores a certificate
    configured without a signing key. Unknown versions fail closed.
    """
    def read(self):
        code, version, error = read_command(
            subprocess.run, ["dpkg-query", "-W", "-f=${Version}", "dkms"])
        if code != 0 or error or version != "3.2.2-1ubuntu1":
            return None
        try:
            release = platform.freedesktop_os_release()
        except OSError:
            return None
        distro = release.get("ID", "")
        if distro != "ubuntu":
            distro = release.get("ID_LIKE", distro)
        if distro.startswith("ubuntu"):
            return "/var/lib/shim-signed/mok/MOK.priv", "/var/lib/shim-signed/mok/MOK.der"
        if distro.startswith("debian"):
            return "/var/lib/dkms/mok.key", "/var/lib/dkms/mok.pub"
        return None


class DkmsSigningProbe:
    def __init__(self, config_root="/etc/dkms", runner=subprocess.run,
                 defaults_adapter=None, signer_available=None):
        self.config_root = Path(config_root)
        self.runner = runner
        self.defaults = defaults_adapter or DkmsDefaultsAdapter()
        self.signer_available = signer_available or self._signer_available

    @staticmethod
    def _signer_available(kernel):
        if not re.fullmatch(r"[A-Za-z0-9_.+-]+", kernel):
            return False
        build = Path("/lib/modules") / kernel / "build"
        config = build / "include/config/auto.conf"
        try:
            if not config.exists():
                config = build / ".config"
            if not re.search(r'^CONFIG_MODULE_SIG_HASH="?[a-z0-9_]+"?$', config.read_text(), re.M):
                return False
        except (OSError, UnicodeError):
            return False
        if shutil.which("kmodsign"):
            return True
        return any(os.access(path, os.X_OK) and Path(path).is_file() for path in (
            "/usr/src/linux-headers-%s/scripts/sign-file" % kernel,
            "/lib/modules/%s/build/scripts/sign-file" % kernel))

    def _config(self):
        values = {}
        files = [self.config_root / "framework.conf"]
        directory = self.config_root / "framework.conf.d"
        try:
            files += sorted(path for path in directory.iterdir() if path.name.endswith(".conf"))
        except FileNotFoundError:
            pass
        for path in files:
            try:
                text = path.read_text()
            except FileNotFoundError:
                continue
            for line in text.splitlines():
                tokens = shlex.split(line, comments=True)
                if not tokens:
                    continue
                # Reject shell expansion even when quoted. Do not evaluate it.
                if len(tokens) != 1 or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=[^$`;<>|&\\~(){}]*", tokens[0]):
                    raise ValueError("dynamic-config")
                key, value = tokens[0].split("=", 1)
                values[key] = value
        if values.get("sign_tool") or values.get("sign_file"):
            raise ValueError("custom-signer")
        if values.get("install_tree", "/lib/modules") != "/lib/modules":
            raise ValueError("custom-module-tree")
        return values

    def _fingerprints(self, certificate):
        values = {}
        for algorithm, length in (("sha256", 64), ("sha1", 40)):
            code, output, error = read_command(self.runner, [
                "openssl", "x509", "-inform", "DER", "-in", certificate,
                "-noout", "-fingerprint", "-" + algorithm])
            if code == 0 and not error and "=" in output:
                value = output.split("=", 1)[1].replace(":", "").strip().lower()
                if re.fullmatch(r"[a-f0-9]{%d}" % length, value):
                    values[algorithm] = value
        return values

    def _key_id(self, certificate):
        code, output, error = read_command(self.runner, [
            "openssl", "x509", "-inform", "DER", "-in", certificate,
            "-noout", "-ext", "subjectKeyIdentifier"])
        if code == 0 and not error:
            lines = output.splitlines()
            if len(lines) == 2 and lines[0].strip() == "X509v3 Subject Key Identifier:":
                value = lines[1].strip().replace(":", "").lower()
                if re.fullmatch(r"[a-f0-9]{40}", value):
                    return value
        return ""

    def probe(self, kernel=""):
        certificate = ""
        kernel = kernel or os.uname().release
        try:
            values = self._config()
            defaults = self.defaults.read()
            if defaults is None:
                return SigningEvidence(reason="unsupported-dkms-contract")
            key = values.get("mok_signing_key", "")
            if key:
                certificate = values.get("mok_certificate") or "/var/lib/dkms/mok.pub"
            else:
                key, certificate = defaults
            # A missing key can trigger DKMS key regeneration: that is not READY.
            # Only stat private-key metadata; never open it or expose its path.
            if (not Path(key).is_absolute() or not Path(certificate).is_absolute()
                    or Path(key).resolve() == Path(certificate).resolve()):
                return SigningEvidence(reason="signing-infrastructure-unverified")
            public = Path(certificate)
            if not public.is_file() or public.stat().st_size == 0:
                return SigningEvidence(SigningReadiness.CERTIFICATE_NOT_FOUND, reason="certificate-missing")
            if (not Path(key).is_file() or public.samefile(key) or not self.signer_available(kernel)):
                return SigningEvidence(reason="signing-infrastructure-unverified")
            code, output, error = read_command(self.runner, ["mokutil", "--test-key", certificate])
            if code is None and error == "unavailable":
                return SigningEvidence(SigningReadiness.MOKUTIL_UNAVAILABLE, certificate)
            if error:
                return SigningEvidence(certificate=certificate, reason="test-key-error")
            if code == 0 and output == certificate + " is already enrolled":
                return SigningEvidence(SigningReadiness.READY_ENROLLED, certificate,
                                       key_id=self._key_id(certificate))
            if code != 1 or output != certificate + " is not enrolled":
                return SigningEvidence(certificate=certificate, reason="test-key-unknown")
            fingerprints = self._fingerprints(certificate)
            code, pending, error = read_command(self.runner, ["mokutil", "--list-new"])
            if code != 0 or error:
                return SigningEvidence(certificate=certificate, reason="pending-unknown")
            for algorithm, fingerprint in fingerprints.items():
                label = "SHA256" if algorithm == "sha256" else "SHA1"
                matches = re.findall(label + r"\s*Fingerprint:\s*([a-fA-F0-9:]+)", pending, re.I)
                if any(value.replace(":", "").lower() == fingerprint for value in matches):
                    return SigningEvidence(SigningReadiness.PENDING_ENROLLMENT, certificate, fingerprint)
            if pending and not fingerprints:
                return SigningEvidence(certificate=certificate, reason="pending-comparison-unavailable")
            if pending and not re.search(r"SHA(?:1|256)\s*Fingerprint:\s*(?:[a-fA-F0-9]{2}:){19,31}[a-fA-F0-9]{2}\b", pending, re.I):
                return SigningEvidence(certificate=certificate, reason="pending-output-unknown")
            return SigningEvidence(SigningReadiness.CERTIFICATE_NOT_ENROLLED, certificate)
        except (OSError, ValueError, UnicodeError):
            return SigningEvidence(reason="configuration-unverified")
