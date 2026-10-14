# SPDX-License-Identifier: GPL-2.0-or-later
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple, Union

from ..models import DriverOption


class TransactionAction(Enum):
    NO_CHANGE = "no_change"
    RESOLVE = "resolve"
    INSTALL = "install"
    REMOVE = "remove"
    SWITCH = "switch"


class TransactionState(Enum):
    WAITING = "waiting"
    PREPARING = "preparing"
    RESOLVING = "resolving"
    DOWNLOADING = "downloading"
    INSTALLING = "installing"
    REMOVING = "removing"
    FINALIZING = "finalizing"
    CANCELLING = "cancelling"
    FINISHED = "finished"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RestartRequirement(Enum):
    UNKNOWN = "unknown"
    NONE = "none"
    POSSIBLE = "possible"
    APPLICATION = "application"
    SESSION = "session"
    SYSTEM = "system"


@dataclass(frozen=True)
class PackageReference:
    name: str
    package_id: Optional[str]


@dataclass(frozen=True)
class DriverSelection:
    device_id: str
    current: DriverOption
    target: DriverOption
    action: TransactionAction


@dataclass(frozen=True)
class TransactionPlan:
    selections: Tuple[DriverSelection, ...]
    installs: Tuple[PackageReference, ...]
    removals: Tuple[PackageReference, ...]
    action: TransactionAction
    restart: RestartRequirement = RestartRequirement.NONE
    preview_only: bool = False


@dataclass(frozen=True)
class TransactionError:
    error_code: Union[int, str]
    details: str
    cancelled: bool = False
    authorization_denied: bool = False


@dataclass(frozen=True)
class TransactionProgress:
    action: TransactionAction
    state: TransactionState = TransactionState.WAITING
    percentage: Optional[int] = None
    package_id: Optional[str] = None
    message: str = ""
    allow_cancel: bool = False
    cancel_requested: bool = False
    restart: RestartRequirement = RestartRequirement.UNKNOWN


@dataclass(frozen=True)
class TransactionResult:
    action: TransactionAction
    state: TransactionState
    exit_code: Optional[int]
    error: Optional[TransactionError]
    restart: RestartRequirement
    packages: Tuple[PackageReference, ...] = ()
    runtime_ms: int = 0
    cancel_requested: bool = False
    secure_boot_attention: Optional[bool] = None

