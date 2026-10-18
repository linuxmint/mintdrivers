# SPDX-License-Identifier: GPL-2.0-or-later
"""Read-only boot/root evidence. Never inspect users, mount or modify a target."""
from enum import Enum
import gettext
from pathlib import Path
import shlex

_ = gettext.gettext


class SessionState(Enum):
    LIVE_SESSION = "live_session"
    INSTALLED_SYSTEM = "installed_system"
    UNKNOWN = "unknown"


def session_message(state):
    if state == SessionState.LIVE_SESSION:
        return _("Driver changes are unavailable in the Live Session. Install Mainuan to manage this computer's drivers.")
    if state == SessionState.UNKNOWN:
        return _("The system session could not be verified. Driver changes are blocked; viewing remains available.")
    return ""


class SystemSessionProbe:
    def __init__(self, cmdline="/proc/cmdline", mountinfo="/proc/self/mountinfo"):
        self.cmdline = Path(cmdline)
        self.mountinfo = Path(mountinfo)

    @staticmethod
    def _read(path):
        with path.open() as stream:
            value = stream.read(1024 * 1024 + 1)
        if len(value) > 1024 * 1024:
            raise ValueError("Unexpected proc size")
        return value

    def probe(self):
        try:
            options = shlex.split(self._read(self.cmdline))
            if any(value in ("boot=casper", "boot=live") for value in options):
                return SessionState.LIVE_SESSION
            roots = []
            for line in self._read(self.mountinfo).splitlines():
                left, separator, right = line.partition(" - ")
                fields, filesystem = left.split(), right.split()
                if separator and len(fields) >= 6 and fields[4] == "/" and len(filesystem) >= 3:
                    roots.append(filesystem)
            if len(roots) != 1:
                return SessionState.UNKNOWN
            filesystem, source, options_root = roots[0][:3]
            if filesystem == "overlay" and any(value.startswith(("upperdir=/cow/", "workdir=/cow/"))
                                                for value in options_root.split(",")):
                return SessionState.LIVE_SESSION
            if (not any(value.startswith("boot=") for value in options)
                    and filesystem in ("ext4", "ext3", "ext2", "btrfs", "xfs", "f2fs", "zfs")
                    and (source.startswith("/dev/") or filesystem == "zfs")):
                return SessionState.INSTALLED_SYSTEM
        except (OSError, UnicodeError, ValueError):
            pass
        return SessionState.UNKNOWN
