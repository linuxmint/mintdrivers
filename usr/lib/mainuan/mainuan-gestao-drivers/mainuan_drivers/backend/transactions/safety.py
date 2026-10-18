# SPDX-License-Identifier: GPL-2.0-or-later
"""Read-only firmware checks and guards for the beta's unsupported MOK flow."""
import gettext
from pathlib import Path

from ..preflight import SecureBootState

from .planner import PlanningError

_ = gettext.gettext
EFI_GUID = "8be4df61-93ca-11d2-aa0d-00e098032b8c"


def read_secure_boot(efi_root="/sys/firmware/efi"):
    root = Path(efi_root)
    try:
        root.stat()
        secure = (root / "efivars" / ("SecureBoot-" + EFI_GUID)).read_bytes()
        setup = (root / "efivars" / ("SetupMode-" + EFI_GUID)).read_bytes()
        if len(secure) != 5 or len(setup) != 5 or secure[4] not in (0, 1) or setup[4] not in (0, 1):
            return SecureBootState.UNKNOWN
        return SecureBootState.ENABLED if secure[4] == 1 and setup[4] == 0 else SecureBootState.DISABLED
    except FileNotFoundError:
        return SecureBootState.UNSUPPORTED if not root.exists() else SecureBootState.UNKNOWN
    except OSError:
        return SecureBootState.UNKNOWN


def check_secure_boot(plan, state):
    if state not in (SecureBootState.DISABLED, SecureBootState.UNSUPPORTED) and any(ref.requires_dkms is not False for ref in plan.installs):
        raise PlanningError(_("This driver requires a Secure Boot flow that is not supported by this beta. "
                              "No firmware or MOK settings will be changed."))
