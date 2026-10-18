import unittest
from copy import deepcopy

from test_backend import FakePackage, driver, find_device, make_backend


class UpstreamNvidiaTests(unittest.TestCase):
    def options(self, recommendations, installed=()):
        raw = {"device": {"vendor": "NVIDIA", "drivers": {
            name: driver(recommended=value) for name, value in recommendations.items()}}}
        before = deepcopy(raw)
        result = find_device(make_backend(raw, {name: FakePackage(name, name in installed)
                                               for name in recommendations}))
        self.assertEqual(raw, before)
        return {option.package_name: option for option in result.drivers if option.package_name}

    def test_open_recommendation_from_udc_is_authoritative(self):
        options = self.options({"nvidia-driver-580": False, "nvidia-driver-580-open": True})
        self.assertTrue(options["nvidia-driver-580-open"].recommended)
        self.assertFalse(options["nvidia-driver-580"].recommended)

    def test_closed_recommendation_after_560_is_authoritative(self):
        options = self.options({"nvidia-driver-580": True, "nvidia-driver-580-open": False})
        self.assertTrue(options["nvidia-driver-580"].recommended)
        self.assertFalse(options["nvidia-driver-580-open"].recommended)

    def test_custom_closed_pin_older_series_is_not_overridden(self):
        options = self.options({"nvidia-driver-580": True, "nvidia-driver-580-open": False,
                                "nvidia-driver-590-open": False})
        self.assertEqual([name for name, option in options.items() if option.recommended], ["nvidia-driver-580"])

    def test_custom_open_pin_and_point_release_preserved(self):
        name = "nvidia-driver-580.1234-open"
        options = self.options({name: True, "nvidia-driver-590": False})
        self.assertEqual([key for key, option in options.items() if option.recommended], [name])

    def test_nonrecommended_server_hidden_only_with_desktop_alternative(self):
        options = self.options({"nvidia-driver-580": True, "nvidia-driver-580-server": False})
        self.assertNotIn("nvidia-driver-580-server", options)

    def test_recommended_server_is_never_hidden(self):
        options = self.options({"nvidia-driver-535": False, "nvidia-driver-470-server": True})
        self.assertTrue(options["nvidia-driver-470-server"].recommended)

    def test_only_server_options_remain_visible(self):
        names = {"nvidia-driver-470-server": False, "nvidia-driver-580-server-open": False}
        self.assertEqual(set(self.options(names)), set(names))

    def test_unavailable_desktop_does_not_hide_the_only_usable_server(self):
        names = {"nvidia-driver-535": driver(), "nvidia-driver-470-server": driver()}
        unavailable = FakePackage("nvidia-driver-535")
        unavailable.candidate = None
        device = find_device(make_backend({"device": {"drivers": names}}, {
            "nvidia-driver-535": unavailable, "nvidia-driver-470-server": FakePackage("nvidia-driver-470-server")}))
        self.assertEqual([option.package_name for option in device.drivers if option.package_name],
                         ["nvidia-driver-470-server"])

    def test_installed_server_remains_visible_with_desktop_alternative(self):
        options = self.options({"nvidia-driver-580": True, "nvidia-driver-470-server": False},
                               installed=("nvidia-driver-470-server",))
        self.assertTrue(options["nvidia-driver-470-server"].installed)
        self.assertTrue(options["nvidia-driver-470-server"].selected)

    def test_installed_closed_is_not_hidden_when_open_recommended(self):
        options = self.options({"nvidia-driver-580": False, "nvidia-driver-580-open": True},
                               installed=("nvidia-driver-580",))
        self.assertTrue(options["nvidia-driver-580"].selected)

    def test_no_recommendation_does_not_invent_fallback_by_branch(self):
        options = self.options({"nvidia-driver-550-open": False, "nvidia-driver-580": False})
        self.assertFalse(any(option.recommended for option in options.values()))

    def test_udc_recommendation_does_not_require_mainuan_to_reclassify_origin(self):
        name = "nvidia-driver-580"
        device = find_device(make_backend({"device": {"drivers": {
            name: driver(recommended=True, from_distro=False)}}}, {name: FakePackage(name)}))
        self.assertTrue(next(option for option in device.drivers if option.package_name == name).recommended)
