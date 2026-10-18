from dataclasses import replace
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from test_preflight import context
from test_transaction_planner import scenario, target
from mainuan_drivers.backend.activation import DeviceBinding, DriverActivationProbe, activation_state
from mainuan_drivers.backend.preflight import (
    ActivationState, DkmsState, SecureBootState, assess_activation,
)
from mainuan_drivers.backend.signing import SigningEvidence, SigningReadiness
from mainuan_drivers.backend.transactions.execution import SnapshotSource


class SysfsBindingTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.device = self.root / "devices/pci/device"
        self.driver = self.root / "bus/pci/drivers/nvidia"
        self.module = self.root / "module/nvidia"
        for directory in (self.device, self.driver, self.module):
            directory.mkdir(parents=True)
        (self.device / "driver").symlink_to(self.driver, target_is_directory=True)
        (self.driver / "module").symlink_to(self.module, target_is_directory=True)
        self.runner = Mock(return_value=subprocess.CompletedProcess([], 0,
            "filename: /lib/modules/test/nvidia.ko\nsigner: Signing B\nsig_key: BB\nsig_hashalgo: sha256\n", ""))
        self.probe = DriverActivationProbe(self.root, self.runner)

    def test_driver_module_and_signature_evidence(self):
        result = self.probe.probe(str(self.device))
        self.assertEqual((result.driver, result.module, result.verified), ("nvidia", "nvidia", True))
        self.assertEqual(result.signer, "Signing B")
        self.assertEqual(result.sig_hashalgo, "sha256")
        argv = self.runner.call_args.args[0]
        self.assertEqual(argv, ["modinfo", "nvidia"])
        self.assertEqual(self.runner.call_args.kwargs["env"]["LC_ALL"], "C")

    def test_module_link_absent_preserves_driver_evidence(self):
        (self.driver / "module").unlink()
        result = self.probe.probe(str(self.device))
        self.assertTrue(result.verified)
        self.assertEqual(result.driver, "nvidia")
        self.assertEqual(result.module, "")
        self.runner.assert_not_called()

    def test_missing_driver_is_unknown(self):
        (self.device / "driver").unlink()
        self.assertFalse(self.probe.probe(str(self.device)).verified)

    def test_broken_driver_symlink_is_unknown(self):
        (self.driver / "module").unlink()
        self.driver.rmdir()
        self.assertFalse(self.probe.probe(str(self.device)).verified)

    def test_broken_module_symlink_is_unknown(self):
        self.module.rmdir()
        self.assertFalse(self.probe.probe(str(self.device)).verified)

    def test_missing_and_absent_path(self):
        for path in (None, "", str(self.root / "missing")):
            self.assertFalse(self.probe.probe(path).verified)

    def test_path_outside_sysfs_rejected(self):
        self.assertFalse(self.probe.probe("/tmp").verified)

    def test_driver_link_outside_sysfs_rejected(self):
        (self.device / "driver").unlink()
        (self.device / "driver").symlink_to("/tmp", target_is_directory=True)
        self.assertFalse(self.probe.probe(str(self.device)).verified)

    def test_permission_denied_is_unknown(self):
        with patch.object(Path, "resolve", side_effect=PermissionError()):
            self.assertFalse(self.probe.probe(str(self.device)).verified)

    def test_modinfo_absent_and_unsigned_preserve_binding(self):
        for result in (FileNotFoundError(), subprocess.CompletedProcess([], 0, "filename: module.ko\n", "")):
            with self.subTest(result=result):
                self.runner.side_effect = result if isinstance(result, Exception) else None
                self.runner.return_value = result
                binding = self.probe.probe(str(self.device))
                self.assertTrue(binding.verified)
                self.assertEqual(binding.signer, "")

    def test_driver_binding_changed_between_reads(self):
        before = self.probe.probe(str(self.device))
        nouveau = self.driver.parent / "nouveau"
        nouveau.mkdir()
        (self.device / "driver").unlink()
        (self.device / "driver").symlink_to(nouveau, target_is_directory=True)
        after = self.probe.probe(str(self.device))
        self.assertNotEqual(before.driver, after.driver)

    def test_driver_binding_unchanged(self):
        self.assertEqual(self.probe.probe(str(self.device)), self.probe.probe(str(self.device)))


class ActivationPolicyTests(unittest.TestCase):
    def state(self, package="nvidia-driver-580", binding=None, before=None, security=None,
              dkms=DkmsState.NO_DKMS, changing=False):
        return activation_state(package, binding, before, security or context(), dkms, changing)

    def test_nvidia_bound_is_active_confirmed(self):
        self.assertEqual(self.state(binding=DeviceBinding("nvidia", "nvidia", True)), ActivationState.ACTIVE_CONFIRMED)

    def test_nvidia_old_driver_requires_reboot(self):
        self.assertEqual(self.state(binding=DeviceBinding("nouveau", "nouveau", True)), ActivationState.INSTALLED_REBOOT_REQUIRED)

    def test_nvidia_same_module_cannot_prove_new_open_closed_variant(self):
        binding = DeviceBinding("nvidia", "nvidia", True)
        self.assertEqual(self.state(binding=binding, before=binding, changing=True), ActivationState.INSTALLED_REBOOT_REQUIRED)

    def test_nvidia_no_binding_is_unverified(self):
        self.assertEqual(self.state(), ActivationState.INSTALLED_ACTIVATION_UNVERIFIED)

    def test_broadcom_wl_bound_is_active_confirmed(self):
        self.assertEqual(self.state("broadcom-sta-dkms", DeviceBinding("wl", "wl", True)), ActivationState.ACTIVE_CONFIRMED)

    def test_broadcom_old_binding_requires_reboot(self):
        self.assertEqual(self.state("broadcom-sta-dkms", DeviceBinding("b43", "b43", True)), ActivationState.INSTALLED_REBOOT_REQUIRED)

    def test_generic_package_does_not_invent_module_mapping(self):
        self.assertEqual(self.state("generic-driver", DeviceBinding("generic", "generic", True)), ActivationState.INSTALLED_ACTIVATION_UNVERIFIED)

    def test_signed_module_and_correct_enrolled_certificate(self):
        security = context(secure_boot_state=SecureBootState.ENABLED,
                           signing=SigningEvidence(SigningReadiness.READY_ENROLLED, key_id="bb"))
        binding = DeviceBinding("nvidia", "nvidia", True, signer="B", sig_key="BB", sig_hashalgo="sha256")
        self.assertEqual(self.state(binding=binding, security=security, dkms=DkmsState.DKMS_REQUIRED), ActivationState.ACTIVE_CONFIRMED)

    def test_module_signed_by_different_key_is_unverified(self):
        security = context(secure_boot_state=SecureBootState.ENABLED,
                           signing=SigningEvidence(SigningReadiness.READY_ENROLLED, key_id="bb"))
        binding = DeviceBinding("nvidia", "nvidia", True, signer="A", sig_key="AA", sig_hashalgo="sha256")
        self.assertEqual(self.state(binding=binding, security=security, dkms=DkmsState.DKMS_REQUIRED),
                         ActivationState.INSTALLED_ACTIVATION_UNVERIFIED)

    def test_unsigned_module_with_secure_boot_is_not_confirmed(self):
        security = context(secure_boot_state=SecureBootState.ENABLED,
                           signing=SigningEvidence(SigningReadiness.READY_ENROLLED))
        self.assertEqual(self.state(binding=DeviceBinding("nvidia", "nvidia", True), security=security,
                                   dkms=DkmsState.DKMS_REQUIRED), ActivationState.INSTALLED_ACTIVATION_UNVERIFIED)

    def test_signer_alone_is_not_trust(self):
        binding = DeviceBinding("nvidia", "nvidia", True, signer="unrelated", sig_key="AA", sig_hashalgo="sha256")
        self.assertEqual(self.state(binding=binding, security=context(secure_boot_state=SecureBootState.ENABLED),
                                   dkms=DkmsState.DKMS_REQUIRED), ActivationState.INSTALLED_ACTIVATION_UNVERIFIED)

    def test_matching_pending_result_requires_mokmanager(self):
        _, device, planner = scenario(False)
        plan = planner.build({device.device_id: target(device, "new-driver")})
        plan = replace(plan, installs=tuple(replace(ref, requires_dkms=True) for ref in plan.installs))
        security = context(signing=SigningEvidence(SigningReadiness.PENDING_ENROLLMENT))
        self.assertEqual(assess_activation(plan, security, (("new-driver", True),))[0].state,
                         ActivationState.INSTALLED_MOK_REQUIRED)

    def test_unrelated_pending_mok_does_not_affect_prebuilt_activation(self):
        _, device, planner = scenario(False)
        plan = planner.build({device.device_id: target(device, "new-driver")})
        security = context(signing=SigningEvidence(SigningReadiness.PENDING_ENROLLMENT))
        self.assertEqual(assess_activation(plan, security, (("new-driver", True),))[0].state,
                         ActivationState.INSTALLED_ACTIVATION_UNVERIFIED)

    def test_missing_before_evidence_cannot_prove_changed_variant_active(self):
        self.assertEqual(self.state(binding=DeviceBinding("nvidia", "nvidia", True), changing=True),
                         ActivationState.INSTALLED_ACTIVATION_UNVERIFIED)

    def test_startup_test_scenarios_refresh_activation_without_host_reads(self):
        expected = {"activation-active": ActivationState.ACTIVE_CONFIRMED,
                    "activation-reboot": ActivationState.INSTALLED_REBOOT_REQUIRED,
                    "activation-mok": ActivationState.INSTALLED_MOK_REQUIRED,
                    "activation-unverified": ActivationState.INSTALLED_ACTIVATION_UNVERIFIED,
                    "activation-old-driver": ActivationState.INSTALLED_REBOOT_REQUIRED}
        with patch.object(DriverActivationProbe, "probe", side_effect=AssertionError("Host read")):
            for name, state in expected.items():
                with self.subTest(name=name):
                    snapshot = SnapshotSource(test_mode=True, scenario=name).load()
                    self.assertEqual(snapshot.activations[0].state, state)
