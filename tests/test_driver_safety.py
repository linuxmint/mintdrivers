import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "usr/lib/mainuan/mainuan-gestao-drivers"))
from test_backend import FakeDependency, FakePackage, make_backend
from mainuan_drivers.backend.transactions.safety import EFI_GUID, SecureBootState, read_secure_boot


class DriverSafetyTests(unittest.TestCase):
    def test_secure_boot_unsupported_on_bios_and_unknown_on_unreadable_efi(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "efi"
            self.assertEqual(read_secure_boot(root), SecureBootState.UNSUPPORTED)
            root.mkdir()
            self.assertEqual(read_secure_boot(root), SecureBootState.UNKNOWN)

    def test_efi_attribute_prefix_and_setup_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            efivars = Path(directory) / "efivars"
            efivars.mkdir()
            secure = efivars / ("SecureBoot-" + EFI_GUID)
            setup = efivars / ("SetupMode-" + EFI_GUID)
            secure.write_bytes(b"\x07\x00\x00\x00\x01")
            setup.write_bytes(b"\x07\x00\x00\x00\x00")
            self.assertEqual(read_secure_boot(directory), SecureBootState.ENABLED)
            setup.write_bytes(b"\x07\x00\x00\x00\x01")
            self.assertEqual(read_secure_boot(directory), SecureBootState.DISABLED)
            secure.write_bytes(b"bad")
            self.assertEqual(read_secure_boot(directory), SecureBootState.UNKNOWN)

    def test_dkms_dependency_graph_and_signed_alternative(self):
        driver = FakePackage("gpu-driver", dependencies=[[FakeDependency("gpu-kernel-dkms")]])
        backend = make_backend({}, {"gpu-driver": driver})
        self.assertTrue(backend.package_requires_dkms("gpu-driver"))
        driver.candidate.dependencies = [[FakeDependency("gpu-kernel-dkms"), FakeDependency("signed-kernel-module")]]
        backend._get_cache()["signed-kernel-module"] = FakePackage("signed-kernel-module")
        self.assertIsNone(backend.package_requires_dkms("gpu-driver"))
        self.assertIsNone(backend.package_requires_dkms("unavailable-driver"))

    def test_nested_dependencies_and_cycles_are_read_only(self):
        root = FakePackage("driver-package", dependencies=[[FakeDependency("driver-library")]])
        library = FakePackage("driver-library", dependencies=[[FakeDependency("driver-package")]])
        backend = make_backend({}, {"driver-package": root, "driver-library": library})
        self.assertFalse(backend.package_requires_dkms("driver-package"))
        library.candidate.dependencies.append([FakeDependency("dkms")])
        self.assertTrue(backend.package_requires_dkms("driver-package"))
