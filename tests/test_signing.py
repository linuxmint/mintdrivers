from pathlib import Path
import os
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from test_preflight import context, reference
from mainuan_drivers.backend.signing import (
    DkmsDefaultsAdapter, DkmsSigningProbe, SigningEvidence, SigningReadiness,
)
from mainuan_drivers.backend.preflight import DriverPreflight, SecureBootState, MokState, HeadersState


class SigningProbeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.config = self.root / "config"
        self.config.mkdir()
        self.cert = self.root / "B.der"
        self.cert.write_bytes(b"public certificate B")
        self.key = self.root / "key"
        self.key.touch()  # Existence is enough; no code may read key contents.
        self.defaults = Mock()
        self.defaults.read.return_value = (str(self.key), str(self.cert))
        self.enrolled = True
        self.pending = ""
        self.runner = Mock(side_effect=self.command)
        self.probe = DkmsSigningProbe(self.config, self.runner, self.defaults, lambda kernel: True)

    def command(self, argv, **kwargs):
        self.assertNotIn(str(self.key), argv)
        self.assertEqual(kwargs["env"]["LC_ALL"], "C")
        self.assertNotIn("shell", kwargs)
        self.assertEqual(kwargs["timeout"], 10)
        if argv[:2] == ["mokutil", "--test-key"]:
            self.assertEqual(argv[2], str(self.cert))
            return subprocess.CompletedProcess(argv, 0 if self.enrolled else 1,
                str(self.cert) + (" is already enrolled" if self.enrolled else " is not enrolled"), "")
        if argv[:2] == ["mokutil", "--list-new"]:
            return subprocess.CompletedProcess(argv, 0, self.pending, "")
        self.assertEqual(argv[:2], ["openssl", "x509"])
        if argv[-1] == "subjectKeyIdentifier":
            return subprocess.CompletedProcess(argv, 0, "X509v3 Subject Key Identifier:\n    " + ":".join(["bb"] * 20), "")
        size = 32 if argv[-1] == "-sha256" else 20
        return subprocess.CompletedProcess(argv, 0, "Fingerprint=" + ":".join(["bb"] * size), "")

    def config_text(self, text):
        (self.config / "framework.conf").write_text(text)

    def test_missing_framework_and_dropins_use_audited_default(self):
        self.assertEqual(self.probe.probe().state, SigningReadiness.READY_ENROLLED)

    def test_simple_explicit_assignment(self):
        self.config_text('mok_signing_key="%s"\nmok_certificate="%s"\n' % (self.key, self.cert))
        self.assertEqual(self.probe.probe().state, SigningReadiness.READY_ENROLLED)

    def test_comments_and_whitespace(self):
        self.config_text('  # comment\n  mok_signing_key="%s" # comment\n\tmok_certificate=%s\n' % (self.key, self.cert))
        self.assertEqual(self.probe.probe().state, SigningReadiness.READY_ENROLLED)

    def test_dropin_override_order(self):
        directory = self.config / "framework.conf.d"
        directory.mkdir()
        self.config_text('mok_signing_key="%s"\nmok_certificate=/missing\n' % self.key)
        (directory / "10-first.conf").write_text('mok_certificate=/missing\n')
        (directory / "99-last.conf").write_text('mok_certificate="%s"\n' % self.cert)
        self.assertEqual(self.probe.probe().state, SigningReadiness.READY_ENROLLED)

    def test_certificate_only_does_not_override_ubuntu_default(self):
        self.config_text('mok_certificate=/unrelated-A.der\n')
        result = self.probe.probe()
        self.assertEqual(result.certificate, str(self.cert))
        self.assertEqual(result.state, SigningReadiness.READY_ENROLLED)

    def test_mok_a_enrolled_b_used_is_not_ready(self):
        # --test-key is asked specifically about B, never --list-enrolled.
        self.enrolled = False
        self.pending = "SHA256 Fingerprint: " + ":".join(["aa"] * 32)
        self.assertEqual(self.probe.probe().state, SigningReadiness.CERTIFICATE_NOT_ENROLLED)
        self.assertFalse(any("--list-enrolled" in call.args[0] for call in self.runner.call_args_list))

    def test_mok_b_enrolled_b_used_is_ready(self):
        result = self.probe.probe()
        self.assertEqual(result.state, SigningReadiness.READY_ENROLLED)
        self.assertEqual(result.key_id, "bb" * 20)
        self.assertIn(["mokutil", "--test-key", str(self.cert)], [call.args[0] for call in self.runner.call_args_list])

    def test_matching_pending_sha256(self):
        self.enrolled = False
        self.pending = "SHA256 Fingerprint: " + ":".join(["bb"] * 32)
        self.assertEqual(self.probe.probe().state, SigningReadiness.PENDING_ENROLLMENT)

    def test_matching_pending_sha1(self):
        self.enrolled = False
        self.pending = "SHA1 Fingerprint: " + ":".join(["bb"] * 20)
        self.assertEqual(self.probe.probe().state, SigningReadiness.PENDING_ENROLLMENT)

    def test_truncated_pending_fingerprint_does_not_match(self):
        self.enrolled = False
        self.pending = "SHA1 Fingerprint: bb:bb:bb"
        self.assertNotEqual(self.probe.probe().state, SigningReadiness.PENDING_ENROLLMENT)

    def test_pending_comparison_unavailable_is_unknown(self):
        self.enrolled = False
        self.pending = "SHA1 Fingerprint: " + ":".join(["bb"] * 20)
        original = self.command
        self.runner.side_effect = lambda argv, **kw: (
            subprocess.CompletedProcess(argv, 1, "", "unavailable") if argv[0] == "openssl"
            else original(argv, **kw))
        self.assertEqual(self.probe.probe().state, SigningReadiness.UNKNOWN)

    def test_certificate_absent(self):
        self.cert.unlink()
        self.assertEqual(self.probe.probe().state, SigningReadiness.CERTIFICATE_NOT_FOUND)

    def test_missing_private_key_is_not_ready(self):
        self.key.unlink()
        self.assertEqual(self.probe.probe().state, SigningReadiness.UNKNOWN)
        self.runner.assert_not_called()

    def test_private_key_is_never_opened(self):
        original = Path.open
        def guarded(path, *args, **kwargs):
            if path.resolve() == self.key.resolve():
                raise AssertionError("Private key opened")
            return original(path, *args, **kwargs)
        with patch.object(Path, "open", guarded):
            result = self.probe.probe()
        self.assertEqual(result.state, SigningReadiness.READY_ENROLLED)
        self.assertNotIn(str(self.key), repr(result))

    def test_certificate_same_as_key_is_rejected(self):
        self.defaults.read.return_value = (str(self.key), str(self.key))
        self.assertEqual(self.probe.probe().state, SigningReadiness.UNKNOWN)
        self.runner.assert_not_called()

    def test_hardlink_to_private_key_is_rejected_without_opening(self):
        self.cert.unlink()
        os.link(self.key, self.cert)
        self.assertEqual(self.probe.probe().state, SigningReadiness.CERTIFICATE_NOT_FOUND)
        self.key.write_bytes(b"not read")
        self.assertEqual(self.probe.probe().state, SigningReadiness.UNKNOWN)
        self.runner.assert_not_called()

    def test_unreadable_dropin_directory_does_not_fall_back_to_defaults(self):
        with patch.object(Path, "iterdir", side_effect=PermissionError()):
            self.assertEqual(self.probe.probe().state, SigningReadiness.UNKNOWN)

    def test_kernel_signing_facility_and_tool_are_required(self):
        for text, expected in (("CONFIG_MODULE_SIG_HASH=sha512\n", True),
                               ('CONFIG_MODULE_SIG_HASH="sha256"\n', True), ("", False)):
            with self.subTest(text=text), patch.object(Path, "read_text", return_value=text), \
                    patch.object(Path, "exists", return_value=True), patch("shutil.which", return_value="/tool"):
                self.assertEqual(DkmsSigningProbe._signer_available("test-kernel"), expected)

    def test_missing_kernel_signing_configuration_is_not_ready(self):
        with patch.object(Path, "read_text", side_effect=FileNotFoundError()), patch.object(Path, "exists", return_value=False):
            self.assertFalse(DkmsSigningProbe._signer_available("test-kernel"))

    def test_custom_module_tree_is_not_guessed(self):
        self.config_text("install_tree=/custom/modules")
        self.assertEqual(self.probe.probe().state, SigningReadiness.UNKNOWN)

    def test_dynamic_config_is_never_executed(self):
        for text in ('mok_certificate="$(touch /tmp/forbidden)"', 'source /tmp/config',
                     'mok_certificate="$kernelver"', 'mok_certificate=`command`',
                     'if true; then\nfi', 'mok_certificate=~/key', 'mok_certificate = /tmp/key'):
            with self.subTest(text=text):
                self.config_text(text)
                self.assertNotEqual(self.probe.probe().state, SigningReadiness.READY_ENROLLED)

    def test_custom_signing_tools_and_pkcs11_are_unverified(self):
        for text in ('sign_file=/custom/tool', 'sign_tool=/custom/tool', 'mok_signing_key=pkcs11:token'):
            with self.subTest(text=text):
                self.config_text(text)
                self.assertEqual(self.probe.probe().state, SigningReadiness.UNKNOWN)

    def test_relative_certificate_is_invalid(self):
        self.config_text('mok_signing_key="%s"\nmok_certificate=relative.der' % self.key)
        self.assertEqual(self.probe.probe().state, SigningReadiness.UNKNOWN)

    def test_unknown_dkms_contract_is_not_guessed(self):
        self.defaults.read.return_value = None
        self.assertEqual(self.probe.probe().state, SigningReadiness.UNKNOWN)

    def test_signer_missing(self):
        self.probe.signer_available = lambda kernel: False
        self.assertEqual(self.probe.probe().state, SigningReadiness.UNKNOWN)

    def test_mokutil_missing(self):
        self.runner.side_effect = FileNotFoundError()
        self.assertEqual(self.probe.probe().state, SigningReadiness.MOKUTIL_UNAVAILABLE)

    def test_mokutil_error_timeout_unexpected_and_stderr(self):
        for outcome in (PermissionError(), subprocess.TimeoutExpired("mokutil", 10),
                        subprocess.CompletedProcess([], 5, str(self.cert) + " is already enrolled", ""),
                        subprocess.CompletedProcess([], 0, "unexpected", ""),
                        subprocess.CompletedProcess([], 0, str(self.cert) + " is already enrolled", "warning")):
            with self.subTest(outcome=outcome):
                self.runner.side_effect = outcome if isinstance(outcome, Exception) else None
                self.runner.return_value = outcome
                self.assertEqual(self.probe.probe().state, SigningReadiness.UNKNOWN)

    def test_unreadable_config_is_unknown(self):
        with patch.object(Path, "read_text", side_effect=PermissionError()):
            self.assertEqual(self.probe.probe().state, SigningReadiness.UNKNOWN)

    def test_audited_defaults_adapter_and_unknown_version(self):
        for version, distro, expected in (("3.2.2-1ubuntu1", {"ID": "ubuntu"}, "shim-signed"),
                                         ("3.2.2-1ubuntu1", {"ID": "mainuan", "ID_LIKE": "ubuntu debian"}, "shim-signed"),
                                         ("3.2.2-1ubuntu1", {"ID": "debian"}, "dkms"),
                                         ("future", {"ID": "ubuntu"}, None)):
            with self.subTest(version=version, distro=distro), \
                    patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, version, "")), \
                    patch("platform.freedesktop_os_release", return_value=distro):
                value = DkmsDefaultsAdapter().read()
                self.assertEqual(None if value is None else expected in value[1], None if expected is None else True)


class SigningPolicyTests(unittest.TestCase):
    def test_only_correct_enrolled_signing_evidence_allows_secure_dkms(self):
        for state in SigningReadiness:
            with self.subTest(state=state):
                security = context(secure_boot_state=SecureBootState.ENABLED, mok_state=MokState.ENROLLED,
                                   signing=SigningEvidence(state, "/public/B.der"))
                self.assertEqual(bool(DriverPreflight(security).check([reference()], True).blockers),
                                 state != SigningReadiness.READY_ENROLLED)

    def test_unknown_secure_boot_still_blocks_with_ready_certificate(self):
        security = context(secure_boot_state=SecureBootState.UNKNOWN,
                           signing=SigningEvidence(SigningReadiness.READY_ENROLLED))
        self.assertTrue(DriverPreflight(security).check([reference()], True).blockers)

    def test_ready_signing_does_not_bypass_headers(self):
        security = context(secure_boot_state=SecureBootState.ENABLED, headers_state=HeadersState.MISSING,
                           signing=SigningEvidence(SigningReadiness.READY_ENROLLED))
        self.assertTrue(DriverPreflight(security).check([reference()], True).blockers)
