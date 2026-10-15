"""Manual, non-destructive integration probe: python3 tests/probe_packagekit_readonly.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "usr/lib/mainuan/mainuan-gestao-drivers"))

from PyQt6.QtCore import QCoreApplication, QTimer
from mainuan_drivers.backend import DriverBackend, DriverOptionType
from mainuan_drivers.backend.transactions import TransactionPlanner, TransactionState
from mainuan_drivers.backend.transactions.packagekit import PackageKitTransaction, QtDBusTransport


class ReadOnlyTransport(QtDBusTransport):
    def call(self, path, interface, method, arguments, callback):
        if method not in ("Introspect", "CreateTransaction", "GetAll", "SetHints", "Resolve"):
            raise RuntimeError("A modifying call is forbidden in this probe")
        print("D-Bus:", method, path, flush=True)
        super().call(path, interface, method, arguments, callback)


def main():
    app = QCoreApplication(["mainuan-gestao-drivers-readonly-probe"])
    # This explicit CPU fixture lets the probe run on systems with no additional
    # drivers. Versions and IDs still come exclusively from the real APT cache.
    backend = DriverBackend(devices={"microcode-probe": {"drivers": {
        "intel-microcode": {"free": False, "from_distro": True, "recommended": True},
    }}})
    devices = backend.get_devices()
    device = devices[0]
    package = next(option for option in device.drivers if option.package_name)
    disabled = next(option for option in device.drivers if option.option_type == DriverOptionType.DISABLE)
    planner = TransactionPlanner.from_backend(backend, devices)
    plan = planner.build({device.device_id: disabled if package.installed else package})
    transaction = PackageKitTransaction(planner, transport_factory=ReadOnlyTransport)
    transaction.progressChanged.connect(lambda progress: print(
        "Progress:", progress.state.value, progress.percentage, progress.package_id, flush=True))
    transaction.errorOccurred.connect(lambda error: print("Error:", error, flush=True))
    transaction.transport.eventReceived.connect(lambda name, args: print("Signal:", name, args, flush=True))

    def finished(result):
        print("Result:", result, flush=True)
        blocked = {"Gtk", "Gdk", "GdkPixbuf", "XApp", "PackageKitGlib", "GLib", "Gio"}
        assert "gi" not in sys.modules
        assert not any(name.rsplit(".", 1)[-1] in blocked for name in sys.modules)
        print("Forbidden imports: none", flush=True)
        app.exit(0 if result.state == TransactionState.FINISHED else 1)

    transaction.finished.connect(finished)
    QTimer.singleShot(0, lambda: transaction.resolve(plan))
    QTimer.singleShot(30000, lambda: app.exit(2))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
