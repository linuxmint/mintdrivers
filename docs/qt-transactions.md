# Mainuan Qt driver transactions (beta 0.3)

Valid changes can now be applied after explicit confirmation. Preview alone
never executes a plan. GTK remains temporary development reference, not fallback.

## Architecture and API

`TransactionPlanner.from_backend(backend, devices)` captures package IDs,
installed NVIDIA dependencies and DKMS dependency information in the detection
worker. No APT cache crosses threads. `build()`, `validate_plan()` and `rebuild()`
operate on Python models. Manual/arbitrary choices are rejected; shared packages
still selected by another device are retained.

`DriverExecutionController.prepare(planner, plan)` locks immediately, loads a
fresh `DriverSnapshot` in QThread, rebuilds selections, resolves exact IDs and
simulates PackageKit dependency effects. `prepared` carries a `PreparedPlan`
including additional installation dependencies. Unrelated removals, downgrades
and untrusted packages are blocked. `confirm(prepared)` accepts only the exact
prepared object, takes a new snapshot and repeats preflight. Changed plans or
effects require new confirmation. Every terminal outcome requests fresh detection.
Dependencies with identical names but different versions/architectures remain
distinct, and duplicate names in confirmation include architecture labels.

Removal precedes installation, preserving the inherited Mint switch sequence.
After removal, installation is simulated again; changed dependencies stop the
workflow. `PackageKitTransaction` resolves the relevant IDs immediately before
each real stage; removals require INSTALLED IDs. Each transaction is single-use.
Execution stays disabled by default in the low-level class; only the confirmed
coordinator enables it.

Separate remove/install transactions are not atomic. A failed second stage
stops execution, records completed stages and returns `PARTIAL_FAILURE`, without
automatic restoration. Interrupted mutation/daemon loss may have an uncertain
outcome even within one stage. Simulation does not hold a lock across confirmation
and execution: external package operations can still race. Conservative flags
and revalidation mitigate this but cannot guarantee atomicity or rollback.
If a mutation method acknowledgement times out, the coordinator stays active
until Finished, Destroy or daemon disconnection, rather than abandoning a job
that could still execute. A known final success supersedes that transient timeout.

`ExecutionResult` carries completed stages, structured error/uncertainty, restart
and simulation status. Widgets consume semantic signals only on the GUI thread.
Selection, refresh and apply are locked while busy. Closing an active operation
is prevented; cancellation is requested only when PackageKit allows it.

## D-Bus Contract

- System bus service/manager interface: `org.freedesktop.PackageKit`.
- Manager path: `/org/freedesktop/PackageKit`.
- Transaction interface: `org.freedesktop.PackageKit.Transaction` at the fresh
  path returned by `CreateTransaction`.
- Properties/introspection: `org.freedesktop.DBus.Properties` and
  `org.freedesktop.DBus.Introspectable`.
- Async methods: `Introspect`, `GetAll`, `CreateTransaction`, `SetHints`,
  `Resolve(t, as)`, `InstallPackages(t, as)`, `RemovePackages(t, as, b, b)`, `Cancel`.
- QtDBus explicitly marshals unsigned 64-bit flags/QStringList; pending-call
  watchers integrate with Qt's event loop without blocking polling.
- Install flags: ONLY_TRUSTED (2), plus SIMULATE (4) in preflight. Remove flags:
  0, or 4 for simulation. Both booleans are always false: `allow_deps=false`,
  `autoremove=false`. Purge/global autoremove are not implemented.
- Only real install/remove permit interactive authorization in message and hints.
  PackageKit, PolicyKit and the Plasma session agent handle authorization.
- Signals: `PropertiesChanged`, `Package`, `ErrorCode`, `Finished`,
  `RequireRestart`, `ItemProgress`, `Destroy`, manager owner loss/lock changes.
- PackageKit 1.3.x is supported. Missing/unsupported/locked service disables Apply
  while driver detection continues. No command-line package fallback exists.

Waiting/preparing/resolving/downloading/installing/removing/finalizing/cancelling
map to semantic states. Only Finished establishes success. Percentage outside
0..100 becomes None; item progress does not replace overall progress. Errors
preserve numeric/D-Bus codes, authorization denial and cancellation. Cancel
requests do not themselves establish cancellation and never kill the daemon.
Restart signals preserve application/session/system requirements and combine
with `/var/run/reboot-required` after successful real stages. No restart is run.
A plan's possible-restart advisory is retained after completed real stages when
PackageKit did not establish a stronger requirement.

## Secure Boot and Test Mode

`SystemSecurityProbe` produces a GUI-independent `KernelModuleContext` in the
snapshot worker. Secure Boot has ENABLED/DISABLED/UNSUPPORTED/UNKNOWN states;
EFI presence is independent of its enabled state. Bounded, LC_ALL=C mokutil
queries use only --sb-state, --list-new and --test-key. The last requires an
explicit static certificate configuration; dynamic shell configuration is
never executed, private keys are never read and default certificate paths are
not guessed. MOK has ENROLLED/NOT_ENROLLED/PENDING/UNKNOWN states. Enrollment is
not implemented. The older efivarfs reader remains a compatibility function.

`KernelDetectionAdapter` isolates the installed UDC tuple API; failures or
changed contracts become UNKNOWN. Outdated kernels are warnings, not an upgrade
request. Headers require a Makefile and a matching include/config/kernel.release
under the running kernel build directory. No headers are implicitly installed.

`DriverPreflight` uses candidate dependency groups, actual solver effects and
versioned APT providers to distinguish NO_DKMS/REQUIRED/POSSIBLE/UNKNOWN. A
prebuilt proof needs the same running kernel, trusted Ubuntu origin, restricted
module source metadata and a dependency relationship to the selected driver;
mere availability or an unrelated installed module is insufficient. This is
repository/ABI evidence, not cryptographic verification of a loaded module.
Actual DKMS effects cannot hide behind a prebuilt alternative. Secure Boot
enabled/unknown blocks DKMS without guaranteed signing, even with an enrolled
key. Missing/unverified matching headers also block DKMS. Removal-only plans
remain possible. `PreparedPlan.preflight` exposes separate warnings/blockers;
confirmation and the coordinator both reject blockers before mutation.

After terminal PackageKit results, the GUI withholds any activation claim until
a fresh snapshot inspects configured dpkg state, installed package ID and
security context. `assess_activation` separates installed/reboot, installed/MOK,
not verified, missing and unknown. ACTIVE is reserved for future hardware
evidence; Finished alone never produces it. If detection fails, no successful
activation is claimed. No reboot or MOK modification is performed.

`mainuan-gestao-drivers test` unconditionally uses `SimulatedTransaction`, even
if a real factory is injected. No D-Bus transport is constructed. Only an in-memory
overlay on shared backend fixtures changes; simulated redetection reflects the
choices. A test-only selector exposes 13 security/NVIDIA/Broadcom scenarios in
addition to the general devices. No APT/firmware/host CPU data is read for these
fixtures. Restarting the app discards them. Window/confirmation identify test mode.

Qt recommends restart after Broadcom installation rather than using the legacy
GTK module helper. NVIDIA naming, open/closed/server selection and installed
dependency enumeration stay in the shared backend. No new root helper, sudoers,
PolicyKit action or reboot action exists.

## Verification

Run `python3 -m unittest discover -s tests -v` and
`python3 tests/probe_packagekit_readonly.py`. The probe permits only introspection,
creation, properties, hints and Resolve, never InstallPackages/RemovePackages
(not even simulated). Tests use fakes/offscreen. Real changes and Plasma PolicyKit
authorization require the [manual VM procedure](beta-0.3-testing.md).

References: distribution `/usr/share/dbus-1/interfaces/` XMLs,
[PackageKit enums](https://github.com/PackageKit/PackageKit/blob/v1.3.4/lib/packagekit-glib2/pk-enum.h),
[APT simulation/commit](https://github.com/PackageKit/PackageKit/blob/v1.3.4/backends/apt/apt-job.cpp),
[efivarfs format](https://www.kernel.org/doc/html/latest/filesystems/efivarfs.html).
Identity/domain remain `org.mainuan.GestaoDrivers`/`mainuan-gestao-drivers`.
GPL-2.0-or-later and Linux Mint copyrights/credits are preserved.
