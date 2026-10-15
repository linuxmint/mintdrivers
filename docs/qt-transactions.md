# Mainuan Qt driver transaction infrastructure

The official frontend of beta 0.1 remains read-only. Radio buttons build a desired
selection and the preview dialog lists changes. It has only a Close button.
No frontend callback starts a PackageKit operation, and execution is disabled
by default in both the controller and transaction classes.

## Architecture and API

`backend.transactions` imports only the standard library and backend models.
`TransactionPlanner.from_backend(backend, devices)` captures package IDs and
installed NVIDIA dependencies in the detection worker. No APT cache crosses
threads. `build({device_id: DriverOption})` and `validate_plan(plan)` then work
without I/O. Driver choices must belong to the captured devices. Each device
must have exactly one current option. Manual installations cannot be switched
automatically. Shared packages still selected by another device are retained.
Unknown IDs and fictitious plans can be previewed but cannot be executed.

`backend.transactions.packagekit` imports PyQt6.QtCore and PyQt6.QtDBus, without
widgets, gi, GLib, Gio or PackageKitGlib. `DriverTransactionController` exposes
`select(device, option)`, `plan()`, `resolve(plan)`, `install(plan)`, `remove(plan)`
and `cancel()`. `PackageKitTransaction` exposes the last four methods and is
single-use. Modifying methods require explicitly enabling execution internally;
the Qt frontend does not do this. They first run a separate read-only resolution
transaction and verify exact name/version/architecture identities. Forged plans
are rejected by rebuilding them against the backend snapshot.

The transport is replaceable with a small fake implementing `call`, `subscribe`,
`unsubscribe`, `eventReceived` and `serviceLost`. QtDBus uses the system bus and
`QDBusPendingCallWatcher`, with no blocking calls or polling in the GUI.

## D-Bus contract

- Service and manager interface: `org.freedesktop.PackageKit`.
- Manager path: `/org/freedesktop/PackageKit`.
- Transaction path: whatever object path `CreateTransaction` returns; it need
  not be a child of the manager path.
- Transaction interface: `org.freedesktop.PackageKit.Transaction`.
- Properties: `org.freedesktop.DBus.Properties`.
- Availability check: `org.freedesktop.DBus.Introspectable.Introspect`.
- Flow: introspect, create, subscribe, read properties, set hints, call method.
- Methods: `Resolve(t, as)`, `InstallPackages(t, as)`,
  `RemovePackages(t, as, b, b)`, `Cancel()`.
- PackageKit 1.x flags use unsigned 64-bit bitfields (`t`); string arrays use
  QStringList (`as`), not Python lists marshalled as variant arrays (`av`).
- Installations require trusted packages. Removal uses `allow_deps=false` and
  `autoremove=false`. Purge and global autoremove are not implemented.
- Hints keep existing metadata and request the singular `Package` signal.
  Mutation permits interactive authorization; resolution does not request it.
- Signals: `PropertiesChanged`, `Package`, `ErrorCode`, `Finished`,
  `RequireRestart`, `ItemProgress`, `Destroy`; daemon owner loss is also handled.

Status values map to waiting, preparing, resolving, downloading, installing,
removing, finalizing and cancelling. Only `Finished` establishes the final
result. Percentage 101 (or any value outside 0..100) becomes None. Item progress
never replaces the overall percentage. Runtime from `Finished` is milliseconds.
Errors retain numeric PackageKit codes or D-Bus error names, details,
authorization denial and cancellation. Requesting cancellation is separate
from receiving a cancelled result. Failed cancellation does not terminate a
running transaction. Restart severity preserves session/system requirements,
including security variants. `/var/run/reboot-required` is read after modifying
operations, but no restart is performed. Secure Boot attention is an optional
result field reserved for later validation, not a detected condition today.

PolicyKit and the session agent handle authorization. There is no password
dialog, sudo, pkexec, root helper, new policy or command-line package fallback.

## Verification

Run `python3 -m unittest discover -s tests -v` for fake transaction tests and
planner/Qt tests. GUI tests use offscreen only in their test environment.

Run `python3 tests/probe_packagekit_readonly.py` for a manual integration probe.
It uses a CPU fixture with real APT versions to work even when detection returns
no devices. The transport permits only introspection, creation, properties,
hints and Resolve; installation/removal methods are forbidden. It verifies
PackageKit signals, exact IDs and absence of forbidden Python imports.

Application identity is established before QApplication initializes Plasma
settings using organization Mainuan and application mainuan-gestao-drivers.
`org.mainuan.GestaoDrivers.desktop` is the visible Qt launcher and matches the
desktop file name. Its installed Exec must exist for the portal to recognize it.
GTK has no desktop launcher and is available only through the temporary
`mainuan-gestao-drivers-gtk-legacy` entry point.

## Next Phase

Real execution remains unvalidated. Before enabling it: review/confirm a fresh
plan, simulate dependency effects (especially shared NVIDIA libraries), define
the sequencing and recovery of remove/install phases, validate authorization
with the Plasma agent, refresh detection after completion, and handle session
shutdown during an operation. D-Bus timeout/disconnection may leave the outcome
unknown and must trigger reconciliation before retrying.

The inherited Broadcom module reload helper (`load-broadcom-modules`) remains in GTK and
is pending a separate migration. MOK/Secure Boot handling is also pending.
The existing NVIDIA dependency query is reused unchanged, including its use of
candidate Depends/PreDepends; this preview is not a full dependency simulation.
GTK retains its PackageKitGlib implementation. No driver changes are made by
the integration probe or the current Qt frontend.

API references: the distribution's `/usr/share/dbus-1/interfaces/` XMLs and
[PackageKit 1.3.4 enums](https://github.com/PackageKit/PackageKit/blob/v1.3.4/lib/packagekit-glib2/pk-enum.h).
License remains GPL-2.0-or-later; Linux Mint credits are preserved.
