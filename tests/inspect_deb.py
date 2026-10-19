"""Read-only package gate: python3 tests/inspect_deb.py ../PACKAGE.deb."""
import argparse
from email.parser import Parser
import io
from pathlib import PurePosixPath
import re
import shlex
import subprocess
import tarfile

PACKAGE = "mainuan-gestao-drivers"
OBSOLETE_CONFFILE = "/etc/sudoers.d/" + PACKAGE + "-gtk-legacy"
FORBIDDEN_DEPENDENCIES = {
    "python3-gi", "python3-psutil", "gir1.2-xapp-1.0",
    "gir1.2-packagekitglib-1.0", "gir1.2-gtk-3.0",
}


class PackageAuditError(ValueError):
    pass


def dependency_names(value):
    return {item.strip().split()[0] for item in re.split(r"[,|]", value) if item.strip()}


def audit_package(control, members, scripts, conffiles=""):
    metadata = Parser().parsestr(control)
    if (metadata["Package"], metadata["Version"], metadata["Architecture"]) != (PACKAGE, "1.0~rc1", "all"):
        raise PackageAuditError("Unexpected package identity/version/architecture")
    depends = dependency_names(metadata["Depends"] or "")
    required = {"python3", "python3-pyqt6", "python3-apt", "ubuntu-drivers-common", "packagekit"}
    if not required <= depends or depends & FORBIDDEN_DEPENDENCIES:
        raise PackageAuditError("Missing Qt/backend dependency or remaining legacy dependency")
    if dependency_names(metadata["Recommends"] or "") != {"mokutil", "openssl", "kmod"}:
        raise PackageAuditError("Unexpected read-only probe recommendations")
    bins, desktops, manuals = [], [], []
    for member in members:
        path = PurePosixPath(member.name)
        name = str(path)
        lower = name.lower()
        if member.mode & 0o6000:
            raise PackageAuditError("setuid/setgid payload: " + name)
        if (path.is_absolute() or ".." in path.parts or any(part.startswith("sudoers") for part in path.parts)
                or "gtk" in lower or "xapp" in lower
                or "load-broadcom" in lower or "mintdrivers" in lower
                or set(path.parts) & {"tests", "tools", ".git", ".github", ".pytest_cache", "__pycache__"}
                or path.name in {"qt_ux_probe.py", "probe_packagekit_readonly.py", "inspect_deb.py", "makepot", "Makefile"}
                or name.endswith((".deb", ".buildinfo", ".changes", ".dsc"))
                or name.endswith((".pyc", ".pyo")) or "packagekit_mutation_probe" in name
                or name.startswith("usr/share/polkit-1/actions")):
            raise PackageAuditError("Forbidden payload path: " + name)
        if member.issym() and any(word in member.linkname.lower() for word in ("gtk", "load-broadcom", "mintdrivers")):
            raise PackageAuditError("Legacy symlink target: " + name)
        if name.startswith("usr/bin/") and not member.isdir():
            bins.append(path.name)
        if name.endswith(".desktop"):
            desktops.append(path.name)
        if name.startswith("usr/share/man/") and not member.isdir():
            manuals.append(path.name)
        if name.endswith(".mo") and path.name != PACKAGE + ".mo":
            raise PackageAuditError("Unexpected gettext domain: " + name)
    if bins != [PACKAGE] or desktops != ["org.mainuan.GestaoDrivers.desktop"]:
        raise PackageAuditError("Expected exactly one official Qt launcher/desktop")
    if manuals != [PACKAGE + ".1.gz"]:
        raise PackageAuditError("Expected only the official manpage")
    # Migration references belong in control scripts/metadata, never payload.
    if "remove-on-upgrade " + OBSOLETE_CONFFILE not in conffiles:
        for script in ("preinst", "postinst", "postrm"):
            text = scripts.get(script, "")
            expected = ["dpkg-maintscript-helper", "rm_conffile", OBSOLETE_CONFFILE,
                        "0.5~", PACKAGE, "--", "$@"]
            try:
                commands = [shlex.split(line, comments=True) for line in text.splitlines()]
            except ValueError as error:
                raise PackageAuditError("Unrecognized maintainer script syntax") from error
            if expected not in commands:
                raise PackageAuditError("Missing coordinated conffile migration in " + script)
    return metadata


def inspect_deb(path):
    data = subprocess.run(["dpkg-deb", "--fsys-tarfile", str(path)], check=True, capture_output=True).stdout
    control = subprocess.run(["dpkg-deb", "--ctrl-tarfile", str(path)], check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        members = archive.getmembers()
    files = {}
    with tarfile.open(fileobj=io.BytesIO(control), mode="r:") as archive:
        for member in archive.getmembers():
            if member.isfile():
                files[PurePosixPath(member.name).name] = archive.extractfile(member).read().decode("utf-8")
    return audit_package(files.get("control", ""), members, files, files.get("conffiles", ""))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("deb")
    args = parser.parse_args()
    try:
        result = inspect_deb(args.deb)
    except (PackageAuditError, OSError, subprocess.SubprocessError, tarfile.TarError, UnicodeError) as error:
        parser.exit(1, "FAIL: %s\n" % error)
    print("PASS: %s %s %s; Qt-only payload; safe obsolete conffile migration" % (
        result["Package"], result["Version"], result["Architecture"]))


if __name__ == "__main__":
    main()
