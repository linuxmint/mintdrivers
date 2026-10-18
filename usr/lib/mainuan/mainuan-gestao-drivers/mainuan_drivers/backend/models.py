from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple


class DeviceStatus(Enum):
    RECOMMENDED = "recommended"
    ALTERNATIVE = "alternative"
    MANUALLY_INSTALLED = "manually_installed"
    NO_DRIVER = "no_driver"


class DriverOptionType(Enum):
    PACKAGE = "package"
    MANUAL = "manual"
    DISABLE = "disable"


@dataclass(frozen=True)
class DriverOption:
    package_name: Optional[str]
    version: str
    summary: str
    installed: bool
    selected: bool
    recommended: bool
    builtin: bool
    free: bool
    requires_internet: bool
    status: DeviceStatus
    option_type: DriverOptionType = DriverOptionType.PACKAGE
    selectable: bool = True
    packages: Optional[Tuple[str, ...]] = None


@dataclass(frozen=True)
class DeviceInfo:
    device_id: str
    modalias: str
    vendor: Optional[str]
    model: Optional[str]
    display_name: str
    is_cpu: bool
    is_virtual: bool
    status: DeviceStatus
    icon_key: str
    drivers: Tuple[DriverOption, ...]
    sys_path: Optional[str] = None
