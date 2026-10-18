from dataclasses import replace
from types import SimpleNamespace
import unittest

from test_backend import FakePackage, FakeDependency, driver, make_backend
from test_preflight import context, reference
from mainuan_drivers.backend.models import DriverSource
from mainuan_drivers.backend.preflight import DriverPreflight, DkmsState, SecureBootState
from mainuan_drivers.backend.transactions.planner import TransactionPlanner
from mainuan_drivers.qt.widgets import driver_option_presentation


class ThirdPartyTests(unittest.TestCase):
    def backend(self, metadata=None, installed=False, candidate="580.1", origin="Vendor Archive", dependencies=()):
        metadata = metadata if metadata is not None else {"source": "third-party", "recommended": True}
        package = FakePackage("nvidia-driver-580", installed, dependencies)
        package.candidate.version = candidate
        package.candidate.origins = [SimpleNamespace(origin=origin, label="Graphics", archive="resolute",
                                                     site="https://user:secret@example.invalid/path?token=secret", trusted=True)]
        package.versions = [SimpleNamespace(version="999.99"), package.candidate]
        return make_backend({"device": {"vendor": "NVIDIA", "drivers": {package.shortname: metadata}}},
                            {package.shortname: package}), package

    def option(self, backend):
        return next(option for option in backend.get_devices()[0].drivers if option.package_name)

    def test_explicit_distro_source(self):
        backend, _ = self.backend({"source": "distro", "recommended": True})
        self.assertEqual(self.option(backend).source, DriverSource.DISTRIBUTION)

    def test_explicit_third_party_source(self):
        backend, _ = self.backend()
        self.assertEqual(self.option(backend).source, DriverSource.THIRD_PARTY)

    def test_old_api_from_distro_true_false(self):
        for value, source in ((True, DriverSource.DISTRIBUTION), (False, DriverSource.THIRD_PARTY)):
            backend, _ = self.backend({"from_distro": value})
            self.assertEqual(self.option(backend).source, source)

    def test_missing_or_unknown_source_does_not_guess_from_site(self):
        for metadata in ({}, {"source": "unknown"}, {"source": []}, {"from_distro": "false"}):
            with self.subTest(metadata=metadata):
                backend, _ = self.backend(metadata)
                self.assertEqual(self.option(backend).source, DriverSource.UNKNOWN)

    def test_recommended_third_party_is_not_rewritten(self):
        backend, _ = self.backend()
        self.assertTrue(self.option(backend).recommended)

    def test_alternative_third_party_is_not_promoted(self):
        backend, _ = self.backend({"source": "third-party", "recommended": False})
        self.assertFalse(self.option(backend).recommended)

    def test_candidate_not_numerically_highest_version(self):
        backend, _ = self.backend(candidate="570.8")
        self.assertEqual(self.option(backend).candidate_version, "570.8")
        devices = backend.get_devices()
        plan = TransactionPlanner.from_backend(backend, devices).build({"device": self.option(backend)})
        self.assertEqual(plan.installs[0].package_id, "nvidia-driver-580;570.8;amd64;")

    def test_pinning_can_favor_distribution_candidate(self):
        backend, _ = self.backend({"from_distro": True, "recommended": True}, candidate="570.1", origin="Ubuntu")
        self.assertEqual(self.option(backend).origins[0].origin, "Ubuntu")
        self.assertEqual(self.option(backend).candidate_version, "570.1")

    def test_pinning_can_favor_third_party_candidate(self):
        backend, _ = self.backend(candidate="580.2")
        self.assertEqual(self.option(backend).origins[0].origin, "Vendor Archive")
        self.assertEqual(self.option(backend).candidate_version, "580.2")

    def test_installed_and_candidate_versions_are_distinct(self):
        backend, _ = self.backend(installed=True, candidate="580.3")
        option = self.option(backend)
        self.assertEqual(option.version, "1.0-installed")
        self.assertEqual(option.candidate_version, "580.3")

    def test_origins_are_structured_and_site_credentials_removed(self):
        backend, _ = self.backend()
        origin = self.option(backend).origins[0]
        self.assertEqual((origin.origin, origin.label, origin.archive, origin.site),
                         ("Vendor Archive", "Graphics", "resolute", "example.invalid"))
        self.assertNotIn("secret", repr(origin))

    def test_third_party_is_not_automatically_dkms(self):
        backend, _ = self.backend()
        self.assertEqual(backend.package_dkms_state("nvidia-driver-580"), DkmsState.NO_DKMS)

    def test_third_party_dkms_uses_dependencies(self):
        backend, _ = self.backend(dependencies=[[FakeDependency("nvidia-dkms-580")]])
        self.assertEqual(backend.package_dkms_state("nvidia-driver-580"), DkmsState.DKMS_REQUIRED)

    def test_third_party_badge_and_recommendation_coexist(self):
        backend, _ = self.backend()
        badges = driver_option_presentation(self.option(backend)).badges
        self.assertIn("Recommended", badges)
        self.assertIn("Source: third-party repository", badges)

    def test_third_party_prebuilt_compatibility_and_firmware_trust_are_separate(self):
        name = "linux-modules-nvidia-580-6.20.0-1-generic"
        package = FakePackage(name)
        package.candidate.source_name = "linux-restricted-modules"
        package.candidate.origins = [SimpleNamespace(origin="Vendor Archive", trusted=True)]
        backend = make_backend({}, {name: package})
        facts = backend.module_evidence([name], "6.20.0-1-generic")
        self.assertTrue(facts[0].prebuilt_compatible)
        self.assertFalse(facts[0].prebuilt_firmware_trusted)
        ref = reference(name, False)
        ref = replace(ref, package_id=backend.get_packagekit_id(name, False))
        self.assertFalse(DriverPreflight(context(), facts).check([ref], True).blockers)
        secure = context(secure_boot_state=SecureBootState.ENABLED)
        self.assertIn("prebuilt-signing", [issue.code for issue in DriverPreflight(secure, facts).check([ref], True).blockers])

    def test_mesa_is_not_discovered_by_apt_cache_enumeration(self):
        backend = make_backend({}, {"mesa-vulkan-drivers": FakePackage("mesa-vulkan-drivers")})
        self.assertEqual(backend.get_devices(), ())

    def test_multiple_series_keep_udc_recommendation_from_either_origin(self):
        packages = {name: FakePackage(name) for name in ("nvidia-driver-570", "nvidia-driver-580")}
        for third_recommended in (True, False):
            backend = make_backend({"device": {"drivers": {
                "nvidia-driver-570": {"source": "distro", "recommended": not third_recommended},
                "nvidia-driver-580": {"source": "third-party", "recommended": third_recommended}}}}, packages)
            selected = [option.package_name for option in backend.get_devices()[0].drivers if option.recommended]
            self.assertEqual(selected, ["nvidia-driver-580" if third_recommended else "nvidia-driver-570"])
