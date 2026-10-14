import re

from .models import DeviceInfo, DeviceStatus, DriverOption, DriverOptionType


class PackageUnavailableError(LookupError):
    """Raised when an APT package or requested version is unavailable."""


class DriverBackend:
    """Toolkit-independent driver detection, classification, and APT queries."""

    def __init__(self, detector=None, cache=None, devices=None,
                 extra_devices=None, package_overrides=None, cpu_info_path="/proc/cpuinfo"):
        self._detector = detector
        self._cache = cache
        self._cache_injected = cache is not None
        self._source_devices = devices
        self._extra_devices = extra_devices or {}
        self._package_overrides = package_overrides or {}
        self._cpu_info_path = cpu_info_path

    def _get_source_devices(self):
        if self._source_devices is None:
            detector = self._detector
            if detector is None:
                import apt_pkg
                from UbuntuDrivers import detect
                apt_pkg.init_config()
                apt_pkg.init_system()
                detector = detect
            if callable(detector):
                self._source_devices = detector()
            else:
                self._source_devices = detector.system_device_drivers()
        return self._source_devices

    def _get_cache(self):
        if self._cache is None:
            import apt
            self._cache = apt.Cache()
        return self._cache

    def refresh_package_cache(self):
        if not self._cache_injected:
            self._cache = None

    def get_devices(self):
        """Return detected devices as immutable, GUI-independent data models."""
        source_devices = dict(self._get_source_devices())
        source_devices.update(self._extra_devices)
        cache = self._get_cache()
        return tuple(
            self._build_device(device_id, source_devices[device_id], cache,
                               device_id in self._extra_devices)
            for device_id in sorted(source_devices)
        )

    def _build_device(self, device_id, source, cache, is_test_device):
        source_drivers = source.get("drivers", {})
        driver_data, recommended_overrides = self._filter_nvidia_drivers(source_drivers)

        manual_install = bool(source.get("manual_install", False))
        options = []
        if manual_install:
            options.append(DriverOption(
                package_name=None, version="", summary="", installed=False,
                selected=True, recommended=False, builtin=False, free=False,
                requires_internet=False, status=DeviceStatus.MANUALLY_INSTALLED,
                option_type=DriverOptionType.MANUAL, selectable=False))

        have_builtin = False
        one_selected = False
        package_options = []
        for package_name, current_driver in driver_data.items():
            recommended = bool(
                recommended_overrides.get(package_name, current_driver.get("recommended", False))
                and current_driver.get("from_distro", False))
            status = DeviceStatus.RECOMMENDED if recommended else DeviceStatus.ALTERNATIVE
            builtin = bool(current_driver.get("builtin", False))
            have_builtin = have_builtin or builtin

            try:
                package = cache[package_name]
                if package.is_installed:
                    version = package.installed.version
                    summary = package.installed.summary
                else:
                    version = package.candidate.version
                    summary = package.candidate.summary
                installed = bool(package.is_installed and not builtin)
            except KeyError:
                override = self._package_overrides.get(package_name)
                if override is None:
                    print("WARNING: a driver ({}) doesn't have any available package associated: {}".format(
                        package_name, current_driver))
                    continue
                version, summary, package_installed = override
                installed = bool(package_installed and not builtin)

            selected = False
            if not builtin and not manual_install:
                selected = installed
                if installed:
                    one_selected = True

            package_options.append(DriverOption(
                package_name=package_name,
                version=version,
                summary=summary,
                installed=installed,
                selected=selected,
                recommended=recommended,
                builtin=builtin,
                free=bool(current_driver.get("free", False)),
                requires_internet=package_name.startswith("firmware-b43"),
                status=status,
                selectable=not is_test_device))

        options.extend(package_options)

        if not have_builtin:
            options.append(DriverOption(
                package_name=None, version="", summary="", installed=False,
                selected=not one_selected, recommended=False, builtin=False, free=False,
                requires_internet=False, status=DeviceStatus.NO_DRIVER,
                option_type=DriverOptionType.DISABLE, selectable=not is_test_device))
        elif not one_selected:
            options = [
                DriverOption(**{**option.__dict__, "selected": True})
                if option.builtin else option
                for option in options
            ]

        status = self._selected_status(options)
        vendor = source.get("vendor")
        model = source.get("model")
        is_cpu = "intel-microcode" in source_drivers or "amd64-microcode" in source_drivers
        if is_cpu:
            display_name = self._get_cpu_name()
        elif vendor is None and model is None:
            display_name = "Unknown"
        elif vendor is None:
            display_name = model
        elif model is None:
            display_name = vendor
        else:
            display_name = "%s: %s" % (vendor, model)
        is_virtual = "vmware" in display_name.lower() or "virtualbox" in display_name.lower()

        return DeviceInfo(
            device_id=device_id,
            modalias=source.get("modalias", ""),
            vendor=vendor,
            model=model,
            display_name=display_name,
            is_cpu=is_cpu,
            is_virtual=is_virtual,
            status=status,
            icon_key=self._get_device_icon(source, source_drivers),
            drivers=tuple(options))

    @staticmethod
    def _filter_nvidia_drivers(source_drivers):
        """Apply the existing Mint NVIDIA visibility and preference rules."""
        ignored = set()
        recommended_overrides = {}

        for package_name, current_driver in source_drivers.items():
            if not package_name.startswith("nvidia-"):
                continue
            if package_name in ignored:
                print("Skipping ignored NVIDIA driver '%s'" % package_name)
                continue
            if package_name.endswith(("-server", "-server-open")):
                print("Ignoring server NVIDIA driver '%s'" % package_name)
                ignored.add(package_name)
                continue

            try:
                version = int(re.search(r"nvidia-driver-([0-9]{3}).*", package_name).groups()[0])
                open_preferred = version >= 560
            except (AttributeError, TypeError, ValueError):
                open_preferred = False

            if package_name.endswith("-open"):
                closed_name = package_name[:-len("-open")]
                if closed_name not in source_drivers:
                    continue
                recommended = current_driver.get("recommended", False) and current_driver.get("from_distro", False)
                if open_preferred:
                    print("Ignoring closed NVIDIA driver '%s' as the open one is preferred." % closed_name)
                    ignored.add(closed_name)
                else:
                    print("Ignoring open NVIDIA driver '%s' as a closed one exists and is preferred." % package_name)
                    if recommended:
                        recommended_overrides[closed_name] = True
                    ignored.add(package_name)

        visible_drivers = {
            package_name: details
            for package_name, details in source_drivers.items()
            if package_name not in ignored
        }
        return visible_drivers, recommended_overrides

    @staticmethod
    def _selected_status(options):
        if any(option.selected and option.option_type == DriverOptionType.MANUAL for option in options):
            return DeviceStatus.MANUALLY_INSTALLED
        status = DeviceStatus.NO_DRIVER
        for category in (
                DeviceStatus.RECOMMENDED,
                DeviceStatus.ALTERNATIVE,
                DeviceStatus.NO_DRIVER):
            if any(option.selected and option.status == category for option in options):
                status = category
        return status

    @staticmethod
    def _get_device_icon(source, source_drivers):
        vendor = source.get("vendor") or ""
        model = source.get("model") or ""
        icon = "generic"
        if "nvidia" in vendor.lower():
            icon = "nvidia"
        elif ("radeon" in vendor.lower() or "radeon" in model.lower()
              or "Advanced Micro Devices" in vendor or "AMD" in vendor or "ATI" in vendor):
            icon = "ati"
        elif "broadcom" in vendor.lower():
            icon = "broadcom"
        elif "virtualbox" in vendor.lower() or "virtualbox" in model.lower():
            icon = "virtualbox"

        if "intel-microcode" in source_drivers:
            icon = "intel"
        elif "amd64-microcode" in source_drivers:
            icon = "amd"
        return icon

    def _get_cpu_name(self):
        try:
            with open(self._cpu_info_path) as cpuinfo:
                for line in cpuinfo:
                    if "model name" in line:
                        return re.sub(r".*model name.*:", "", line, count=1).strip()
        except OSError:
            pass
        return "Processor"

    def is_package_installed(self, package_name):
        try:
            return bool(self._get_cache()[package_name].is_installed)
        except KeyError:
            return False

    def get_packagekit_id(self, package_name, installed):
        try:
            package = self._get_cache()[package_name]
        except KeyError as error:
            raise PackageUnavailableError(package_name) from error
        version = package.installed if installed else package.candidate
        if version is None:
            raise PackageUnavailableError(package_name)
        return "%s;%s;%s;" % (
            version.package.shortname, version.version, version.package.architecture())

    def get_installed_nvidia_dependency_ids(self, package_name):
        try:
            package = self._get_cache()[package_name]
        except KeyError as error:
            raise PackageUnavailableError(package_name) from error
        if package.candidate is None:
            return []
        dependencies = []
        for or_group in package.candidate.dependencies:
            for dependency in or_group:
                if dependency.rawtype in ("Depends", "PreDepends") and "nvidia" in dependency.name:
                    dependencies.append(dependency.name)
        package_ids = []
        for dependency_name in dependencies:
            try:
                dependency = self._get_cache()[dependency_name]
            except KeyError:
                continue
            if dependency.is_installed:
                package_ids.append(self.get_packagekit_id(dependency_name, installed=True))
        return package_ids

    def count_installed_proprietary_drivers(self):
        count = 0
        source_devices = dict(self._get_source_devices())
        source_devices.update(self._extra_devices)
        cache = self._get_cache()
        for device in source_devices.values():
            for package_name, driver in device.get("drivers", {}).items():
                if not driver.get("free", False) or package_name == "broadcom-sta-dkms":
                    try:
                        if cache[package_name].is_installed:
                            count += 1
                    except KeyError:
                        continue
        return count


def make_test_device():
    """Return a display-only fixture used by the legacy GTK test mode."""
    return {
        "modalias": "",
        "vendor": "Linux Mint",
        "model": "Dummy Test Device",
        "drivers": {
            "mint-dev-pkg": {"free": False, "from_distro": True, "recommended": True},
            "mint-dev-pkg-debconf": {"free": False, "from_distro": True, "recommended": False},
            "linux-generic": {"free": True, "builtin": True, "from_distro": True, "recommended": False},
            "mesa-vulkan-drivers": {"free": True, "from_distro": True, "recommended": False},
        },
    }


TEST_PACKAGE_OVERRIDES = {
    "mint-dev-pkg": ("1.0", "Dummy recommended driver", False),
    "mint-dev-pkg-debconf": ("1.0", "Dummy alternative driver", False),
    "linux-generic": ("1.0", "Dummy built-in driver", False),
    "mesa-vulkan-drivers": ("1.0", "Dummy open-source alternative driver", True),
    "intel-microcode": ("1.0", "Dummy processor microcode", True),
}
