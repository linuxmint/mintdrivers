# SPDX-License-Identifier: GPL-2.0-or-later
"""One primary presentation state, derived from independent system evidence."""
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from ..backend.session import SessionState


class ViewState(Enum):
    LOADING = "loading"
    READY_NO_DRIVERS = "ready_no_drivers"
    READY_WITH_DRIVERS = "ready_with_drivers"
    OFFLINE = "offline"  # Only a reported transaction network error, never a ping.
    BACKEND_ERROR = "backend_error"
    BACKEND_UNAVAILABLE = "backend_unavailable"
    PACKAGEKIT_UNAVAILABLE = "packagekit_unavailable"
    LIVE_SESSION = "live_session"
    SESSION_UNKNOWN = "session_unknown"
    TRANSACTION_RUNNING = "transaction_running"
    TRANSACTION_SUCCESS = "transaction_success"
    TRANSACTION_FAILURE = "transaction_failure"
    REBOOT_REQUIRED = "reboot_required"
    MOK_REQUIRED = "mok_required"


@dataclass
class ViewModel:
    loading: bool = False
    ready: bool = False
    devices: int = 0
    session: SessionState = SessionState.INSTALLED_SYSTEM
    packagekit: Optional[bool] = None
    backend_error: Optional[ViewState] = None
    running: bool = False
    outcome: Optional[ViewState] = None

    @property
    def state(self):
        if self.running:
            return ViewState.TRANSACTION_RUNNING
        if self.loading:
            return ViewState.LOADING
        if self.backend_error:
            return self.backend_error
        if not self.ready:
            return ViewState.LOADING
        if self.session == SessionState.LIVE_SESSION:
            return ViewState.LIVE_SESSION
        if self.session == SessionState.UNKNOWN:
            return ViewState.SESSION_UNKNOWN
        if self.packagekit is False:
            return ViewState.PACKAGEKIT_UNAVAILABLE
        if self.outcome:
            return self.outcome
        return ViewState.READY_WITH_DRIVERS if self.devices else ViewState.READY_NO_DRIVERS


@dataclass(frozen=True)
class DetectionFailure:
    state: ViewState
    message: str
