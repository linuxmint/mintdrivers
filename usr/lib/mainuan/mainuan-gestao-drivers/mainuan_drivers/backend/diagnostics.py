# SPDX-License-Identifier: GPL-2.0-or-later
"""Explicit allowlist for locally copied diagnostics; no I/O or upload."""
import json
from .. import VERSION


def diagnostic_text(snapshot, packagekit, view_state, simulated=False):
    context = snapshot.context if snapshot else None
    data = {
        "application": "Mainuan Gestao de Drivers", "version": VERSION,
        "test_mode": simulated, "view_state": view_state.value,
        "packagekit_available": packagekit,
        "ubuntu_drivers_common": snapshot.udc_version if snapshot else "unknown",
        "session": snapshot.session.value if snapshot else "unknown",
        "kernel": context.running_kernel if context else "unknown",
        "secure_boot": context.secure_boot_state.value if context else "unknown",
        "mok": context.mok_state.value if context else "unknown",
        "signing": context.signing.state.value if context else "unknown",
        "devices": [],
    }
    if snapshot:
        for device in snapshot.planner.devices:
            data["devices"].append({"type": device.icon_key, "drivers": [
                {"package": option.package_name, "candidate": option.candidate_version,
                 "installed": option.installed, "recommended": option.recommended,
                 "source": option.source.value, "origins": [origin.__dict__ for origin in option.origins]}
                for option in device.drivers if option.package_name and not option.builtin]})
    return json.dumps(data, ensure_ascii=False, indent=2)
