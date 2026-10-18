from dataclasses import replace
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from test_backend import FakeCache, FakeDependency, FakePackage, make_backend
from mainuan_drivers.backend import DriverBackend
from test_transaction_planner import scenario, target
from mainuan_drivers.backend.preflight import (
    ActivationState, DkmsState, DriverPreflight, HeadersState, KernelDetectionAdapter,
    KernelModuleContext, KernelState, ModuleEvidence, MokState, SecureBootState,
    SystemSecurityProbe, analyze_dkms, assess_activation,
)
from mainuan_drivers.backend.transactions.models import PackageReference


def context(**kwargs):
    return replace(KernelModuleContext(SecureBootState.DISABLED, True, KernelState.CURRENT,
                                      "6.20.0-1-generic", "", False, HeadersState.PRESENT), **kwargs)


def reference(name="driver-package", requires=True):
    return PackageReference(name, "%s;1.0;amd64;test" % name, requires)


class SecurityProbeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.efi = self.root / "efi"
        self.efi.mkdir()
        self.config = self.root / "dkms"
        self.config.mkdir()
        self.runner = Mock(side_effect=self.command)
        self.secure_output = "SecureBoot enabled"
        self.pending_output = ""
        self.test_key_code = 0
        self.test_key_message = " is already enrolled"
        self.adapter = Mock()
        self.adapter.read.return_value = (KernelState.CURRENT, "6.20.0-1-generic", "", False)

    def command(self, argv, **kwargs):
        self.assertEqual(argv[0], "mokutil")
        self.assertIn(argv[1], ("--sb-state", "--list-new", "--test-key"))
        self.assertNotIn("shell", kwargs)
        self.assertEqual(kwargs["env"]["LC_ALL"], "C")
        self.assertEqual(kwargs["timeout"], 10)
        code, output = 0, self.secure_output
        if argv[1] == "--list-new":
            output = self.pending_output
        if argv[1] == "--test-key":
            code, output = self.test_key_code, argv[2] + self.test_key_message
        return subprocess.CompletedProcess(argv, code, output, "")

    def probe(self):
        return SystemSecurityProbe(self.efi, self.root / "modules", self.config,
                                   self.runner, self.adapter).probe()

    def certificate(self):
        certificate = self.root / "signing.der"
        certificate.write_bytes(b"fake certificate (never passed to real mokutil)")
        (self.config / "framework.conf").write_text('mok_certificate="%s"\n' % certificate)
        return certificate

    def test_secure_boot_enabled_and_disabled(self):
        for output, expected in (("SecureBoot enabled", SecureBootState.ENABLED),
                                 ("SecureBoot disabled", SecureBootState.DISABLED)):
            with self.subTest(output=output):
                self.secure_output = output
                self.assertEqual(self.probe().secure_boot_state, expected)

    def test_bios_is_unsupported_and_never_calls_mokutil(self):
        self.efi.rmdir()
        self.assertEqual(self.probe().secure_boot_state, SecureBootState.UNSUPPORTED)
        self.runner.assert_not_called()

    def test_mokutil_missing_error_and_timeout_are_unknown(self):
        for failure in (FileNotFoundError(), PermissionError(), subprocess.TimeoutExpired("mokutil", 10),
                        UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid")):
            with self.subTest(failure=failure):
                self.runner.side_effect = failure
                result = self.probe()
                self.assertEqual(result.secure_boot_state, SecureBootState.UNKNOWN)
                self.assertEqual(result.mok_state, MokState.UNKNOWN)

    def test_mokutil_failure_returncode_does_not_parse_success_text(self):
        self.runner.side_effect = None
        self.runner.return_value = subprocess.CompletedProcess([], 1, "SecureBoot enabled", "error")
        self.assertEqual(self.probe().secure_boot_state, SecureBootState.UNKNOWN)

    def test_unexpected_output_is_unknown(self):
        self.secure_output = "Firmware response not understood"
        self.pending_output = "unexpected"
        self.assertEqual(self.probe().secure_boot_state, SecureBootState.UNKNOWN)
        self.assertEqual(self.probe().mok_state, MokState.UNKNOWN)

    def test_pending_mok_detected_without_guessing_a_certificate(self):
        self.pending_output = "SHA1 Fingerprint: aa:bb:cc"
        self.assertEqual(self.probe().mok_state, MokState.PENDING)
        self.assertFalse(any(call.args[0][1] == "--test-key" for call in self.runner.call_args_list))

    def test_enrolled_certificate_must_be_explicitly_identified(self):
        certificate = self.certificate()
        result = self.probe()
        self.assertEqual(result.mok_state, MokState.ENROLLED)
        self.assertEqual(result.certificate, str(certificate))

    def test_not_enrolled_certificate(self):
        self.certificate()
        self.test_key_code, self.test_key_message = 1, " is not enrolled"
        self.assertEqual(self.probe().mok_state, MokState.NOT_ENROLLED)

    def test_certificate_missing_and_unknown_test_key_output(self):
        self.assertEqual(self.probe().mok_state, MokState.UNKNOWN)
        certificate = self.certificate()
        self.test_key_message = " unrecognized response"
        self.assertEqual(self.probe().mok_state, MokState.UNKNOWN)
        certificate.unlink()
        self.assertEqual(self.probe().mok_state, MokState.UNKNOWN)

    def test_config_shell_is_never_executed_or_guessed(self):
        for text in ('mok_certificate="$(touch /tmp/forbidden)"',
                     'if true; then\nmok_certificate="/tmp/example"\nfi',
                     'mok_certificate="$kernelver.der"', 'source /tmp/other.conf'):
            with self.subTest(text=text):
                (self.config / "framework.conf").write_text(text)
                self.assertEqual(self.probe().mok_state, MokState.UNKNOWN)

    def test_config_dropin_override_is_respected(self):
        self.certificate()
        dropin = self.config / "framework.conf.d"
        dropin.mkdir()
        (dropin / "99-local.conf").write_text('mok_certificate="/missing.der"\n')
        self.assertEqual(self.probe().mok_state, MokState.UNKNOWN)

    def test_running_kernel_headers_present_missing(self):
        self.assertEqual(self.probe().headers_state, HeadersState.MISSING)
        build = self.root / "modules/6.20.0-1-generic/build"
        build.mkdir(parents=True)
        (build / "Makefile").write_text("# fake headers\n")
        (build / "include/config").mkdir(parents=True)
        release = build / "include/config/kernel.release"
        release.write_text("6.20.0-1-generic\n")
        self.assertEqual(self.probe().headers_state, HeadersState.PRESENT)
        release.write_text("wrong-kernel\n")
        self.assertEqual(self.probe().headers_state, HeadersState.MISSING)
        release.write_bytes(b"\xff")
        self.assertEqual(self.probe().headers_state, HeadersState.UNKNOWN)

    def test_unreadable_efi_is_unknown_not_unsupported(self):
        original = Path.stat

        def read(path, *args, **kwargs):
            if path == self.efi:
                raise PermissionError()
            return original(path, *args, **kwargs)

        with patch.object(Path, "stat", read):
            self.assertEqual(self.probe().secure_boot_state, SecureBootState.UNKNOWN)


class KernelAdapterTests(unittest.TestCase):
    def test_installed_udc_tuple_contract(self):
        detector = Mock()
        detector.is_running_kernel_outdated.return_value = (True, "6.20.0-1-generic", "6.20.0-2-generic", False)
        result = KernelDetectionAdapter(lambda: detector).read()
        self.assertEqual(result, (KernelState.OUTDATED, "6.20.0-1-generic", "6.20.0-2-generic", False))
        detector.get_kernel_update_warning.assert_not_called()

    def test_missing_changed_and_failed_api_fall_back_to_unknown(self):
        for value in (None, (), (False, "../../invalid", None, False), (False, "kernel", None, "false")):
            with self.subTest(value=value):
                factory = Mock()
                factory.return_value.is_running_kernel_outdated.return_value = value
                with patch("os.uname", return_value=SimpleNamespace(release="fallback-kernel")):
                    self.assertEqual(KernelDetectionAdapter(factory).read()[0], KernelState.UNKNOWN)
        with patch("os.uname", return_value=SimpleNamespace(release="fallback-kernel")):
            self.assertEqual(KernelDetectionAdapter(Mock(side_effect=ImportError())).read()[0], KernelState.UNKNOWN)

    def test_nonstandard_kernel_requires_dkms_hint_retained(self):
        factory = Mock()
        factory.return_value.is_running_kernel_outdated.return_value = (False, "custom-kernel", None, True)
        self.assertTrue(KernelDetectionAdapter(factory).read()[3])


class DkmsEvidenceTests(unittest.TestCase):
    def test_explicit_dkms_and_transitive_dependencies(self):
        driver = FakePackage("driver-package", dependencies=[[FakeDependency("library")]])
        library = FakePackage("library", dependencies=[[FakeDependency("broadcom-sta-dkms")]])
        cache = FakeCache({"driver-package": driver, "library": library})
        self.assertEqual(analyze_dkms(cache, "broadcom-sta-dkms"), DkmsState.DKMS_REQUIRED)
        self.assertEqual(analyze_dkms(cache, "driver-package"), DkmsState.DKMS_REQUIRED)

    def test_nvidia_name_alone_is_not_dkms(self):
        self.assertEqual(analyze_dkms({"nvidia-driver-580": FakePackage("nvidia-driver-580")},
                                      "nvidia-driver-580"), DkmsState.NO_DKMS)

    def test_bcmwl_transitional_package_uses_its_real_dkms_dependency(self):
        package = FakePackage("bcmwl-kernel-source", dependencies=[[FakeDependency("broadcom-sta-dkms")]])
        self.assertEqual(analyze_dkms({"bcmwl-kernel-source": package}, "bcmwl-kernel-source"),
                         DkmsState.DKMS_REQUIRED)

    def test_alternatives_are_possible_not_falsely_no_dkms(self):
        driver = FakePackage("driver-package", dependencies=[[FakeDependency("nvidia-dkms-580"), FakeDependency("prebuilt")]])
        self.assertEqual(analyze_dkms({"driver-package": driver, "prebuilt": FakePackage("prebuilt")},
                                      "driver-package"), DkmsState.DKMS_POSSIBLE)

    def test_unknown_dependency_and_missing_candidate(self):
        driver = FakePackage("driver-package", dependencies=[[FakeDependency("missing")]])
        self.assertEqual(analyze_dkms({"driver-package": driver}, "driver-package"), DkmsState.UNKNOWN)
        driver.candidate = None
        self.assertEqual(analyze_dkms({"driver-package": driver}, "driver-package"), DkmsState.UNKNOWN)

    def test_versioned_prebuilt_provider_of_dkms_is_not_ignored(self):
        root = FakePackage("driver-package", dependencies=[[FakeDependency("nvidia-dkms-580")]])
        module = FakePackage("linux-modules-nvidia-580-6.20.0-1-generic", installed=True)
        module.candidate.source_name = "linux-restricted-modules"
        module.installed.source_name = "linux-restricted-modules"
        module.candidate.origins = module.installed.origins = [SimpleNamespace(origin="Ubuntu", trusted=True)]

        class Cache(FakeCache):
            def get_providing_packages(self, name, include_nonvirtual=False):
                return [module] if name == "nvidia-dkms-580" else []

        cache = Cache({"driver-package": root, module.shortname: module})
        backend = DriverBackend(devices={}, cache=cache)
        self.assertEqual(backend.package_dkms_state("driver-package"), DkmsState.DKMS_POSSIBLE)
        evidence = backend.module_evidence(["driver-package"], "6.20.0-1-generic")
        self.assertTrue(any(item.installed and item.prebuilt_compatible and "driver-package" in item.roots for item in evidence))

    def test_prebuilt_requires_matching_kernel_and_package_source(self):
        name = "linux-modules-nvidia-580-6.20.0-1-generic"
        module = FakePackage(name)
        module.candidate.source_name = "linux-restricted-modules"
        module.candidate.origins = [SimpleNamespace(origin="Ubuntu", trusted=True)]
        backend = make_backend({}, {name: module})
        self.assertTrue(backend.module_evidence([name], "6.20.0-1-generic")[0].prebuilt_compatible)
        self.assertFalse(backend.module_evidence([name], "different-kernel")[0].prebuilt_compatible)
        module.candidate.origins = [SimpleNamespace(origin="Ubuntu", trusted=False)]
        self.assertFalse(backend.module_evidence([name], "6.20.0-1-generic")[0].prebuilt_compatible)
        module.candidate.origins = [SimpleNamespace(origin="Ubuntu", trusted=True)]
        module.candidate.source_name = "third-party-unsigned"
        self.assertFalse(backend.module_evidence([name], "6.20.0-1-generic")[0].prebuilt_compatible)


class PreflightPolicyTests(unittest.TestCase):
    def test_secure_boot_dkms_matrix(self):
        for secure in SecureBootState:
            for mok in MokState:
                with self.subTest(secure=secure, mok=mok):
                    result = DriverPreflight(context(secure_boot_state=secure, mok_state=mok)).check([reference()], True)
                    self.assertEqual(bool(result.blockers), secure in (SecureBootState.ENABLED, SecureBootState.UNKNOWN))

    def test_prebuilt_does_not_get_a_dkms_warning_with_secure_boot(self):
        for secure in SecureBootState:
            with self.subTest(secure=secure):
                result = DriverPreflight(context(secure_boot_state=secure, headers_state=HeadersState.MISSING)).check(
                    [reference(requires=False)], True)
                self.assertFalse(result.blockers)
                self.assertEqual(result.headers_state, HeadersState.NOT_REQUIRED)

    def test_missing_or_unknown_headers_block_dkms_even_without_secure_boot(self):
        for headers in (HeadersState.MISSING, HeadersState.UNKNOWN):
            with self.subTest(headers=headers):
                result = DriverPreflight(context(headers_state=headers)).check([reference()], True)
                self.assertIn("headers-missing", [issue.code for issue in result.blockers])

    def test_kernel_outdated_is_warning_not_automatic_upgrade(self):
        result = DriverPreflight(context(kernel_state=KernelState.OUTDATED)).check([reference()], True)
        self.assertFalse(result.blockers)
        self.assertIn("kernel-outdated", [issue.code for issue in result.warnings])

    def test_unknown_requirement_is_conservative_when_secure_boot_unknown(self):
        result = DriverPreflight(context(secure_boot_state=SecureBootState.UNKNOWN)).check([reference(requires=None)], True)
        self.assertTrue(result.blockers)

    def test_removal_only_has_no_dkms_or_headers_blocker(self):
        result = DriverPreflight(context(secure_boot_state=SecureBootState.ENABLED,
                                        headers_state=HeadersState.MISSING)).check([], True)
        self.assertFalse(result.blockers)

    def test_alternatives_need_actual_related_prebuilt_not_merely_available(self):
        ref = reference(requires=None)
        module = reference("linux-modules-nvidia-580-6.20.0-1-generic", False)
        facts = [ModuleEvidence(ref.package_id, DkmsState.DKMS_POSSIBLE),
                 ModuleEvidence(module.package_id, DkmsState.NO_DKMS, True, False, (ref.name,))]
        policy = DriverPreflight(context(secure_boot_state=SecureBootState.ENABLED), facts)
        self.assertFalse(policy.check([ref], False).blockers)
        self.assertTrue(policy.check([ref], True).blockers)
        self.assertFalse(policy.check([ref, module], True).blockers)
        facts[1] = replace(facts[1], installed=True, roots=("unrelated-driver",))
        self.assertTrue(DriverPreflight(policy.context, facts).check([ref], True).blockers)

    def test_actual_dkms_dependency_blocks_even_if_prebuilt_is_also_present(self):
        module = reference("nvidia-dkms-580", None)
        facts = [ModuleEvidence(module.package_id, DkmsState.DKMS_POSSIBLE, True, True)]
        result = DriverPreflight(context(secure_boot_state=SecureBootState.ENABLED), facts).check([module], True)
        self.assertEqual(result.dkms_state, DkmsState.DKMS_REQUIRED)
        self.assertTrue(result.blockers)

    def test_incompatible_prebuilt_package_is_blocked(self):
        module = reference("linux-modules-nvidia-580-6.20.0-9-generic", False)
        evidence = (ModuleEvidence(module.package_id, DkmsState.NO_DKMS, prebuilt_module=True),)
        result = DriverPreflight(context(), evidence).check([module], True)
        self.assertIn("prebuilt-incompatible", [issue.code for issue in result.blockers])

    def test_kernel_dkms_hint_is_preserved_as_warning_not_a_gpu_rule(self):
        result = DriverPreflight(context(kernel_requires_dkms=True)).check([reference(requires=False)], True)
        self.assertIn("kernel-dkms-hint", [issue.code for issue in result.warnings])
        self.assertEqual(result.dkms_state, DkmsState.NO_DKMS)

    def test_mok_pending_warns_and_requires_reboot_without_modifying_it(self):
        result = DriverPreflight(context(mok_state=MokState.PENDING)).check([reference(requires=False)], True)
        self.assertTrue(result.requires_reboot)
        self.assertIn("mok-pending", [issue.code for issue in result.warnings])

    def test_activation_never_infers_active_from_installed_package(self):
        _, device, planner = scenario(installed=False)
        plan = planner.build({device.device_id: target(device, "new-driver")})
        for mok, expected in ((MokState.UNKNOWN, ActivationState.INSTALLED_REBOOT_REQUIRED),
                              (MokState.PENDING, ActivationState.INSTALLED_MOK_REQUIRED)):
            with self.subTest(mok=mok):
                actual = assess_activation(plan, context(mok_state=mok), (("new-driver", True),))
                self.assertEqual(actual[0].state, expected)
        self.assertEqual(assess_activation(plan, context(), (("new-driver", False),))[0].state, ActivationState.FAILED)
        self.assertEqual(assess_activation(plan, context(), ())[0].state, ActivationState.UNKNOWN)
        self.assertEqual(assess_activation(plan, context(), (("new-driver", True),), failed=True)[0].state,
                         ActivationState.INSTALLED_NOT_ACTIVE)

    def test_changed_installed_package_version_is_not_reported_as_requested_driver(self):
        _, device, planner = scenario(installed=False)
        plan = planner.build({device.device_id: target(device, "new-driver")})
        actual = assess_activation(plan, context(), (("new-driver", "new-driver;other;amd64;installed"),))
        self.assertEqual(actual[0].state, ActivationState.UNKNOWN)
