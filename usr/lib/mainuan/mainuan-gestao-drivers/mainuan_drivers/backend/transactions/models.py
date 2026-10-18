# SPDX-License-Identifier: GPL-2.0-or-later
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple, Union

from ..models import DriverOption
from ..preflight import DriverPreflightResult


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
    PARTIAL_FAILURE = "partial_failure"


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
    requires_dkms: Optional[bool] = None


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
    outcome_unknown: bool = False


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
    effects: Tuple[Tuple[int, PackageReference], ...] = ()
    mutation_observed: bool = False


@dataclass(frozen=True)
class PreparedPlan:
    plan: TransactionPlan
    installs: Tuple[PackageReference, ...]
    removals: Tuple[PackageReference, ...]
    simulated: bool = False
    preflight: Optional[DriverPreflightResult] = None


@dataclass(frozen=True)
class ExecutionResult:
    state: TransactionState
    completed: Tuple[TransactionResult, ...]
    error: Optional[TransactionError]
    restart: RestartRequirement
    simulated: bool = False
    refresh_required: bool = True
    plan: Optional[TransactionPlan] = None
    activations: tuple = ()
    bindings_before: tuple = ()
