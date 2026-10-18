# SPDX-License-Identifier: GPL-2.0-or-later
"""Confirmed driver workflows. All mutations belong to PackageKit transactions."""
import gettext
import logging
from dataclasses import dataclass, replace

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal, pyqtSlot

from ..drivers import DriverBackend, TEST_PACKAGE_OVERRIDES, make_test_devices
from ..models import DriverOptionType
from ..preflight import (
    DriverPreflight, KernelModuleContext, ModuleEvidence, SystemSecurityProbe,
    SecureBootState, DkmsState, HeadersState, KernelState,
)
from ..test_scenarios import scenario_data
from .models import (
    ExecutionResult, PackageReference, PreparedPlan, RestartRequirement, TransactionAction,
    TransactionError, TransactionProgress, TransactionResult, TransactionState,
)
from .packagekit import (
    PackageKitTransaction, QtDBusTransport, ROOT_PATH, SERVICE, PROPERTIES_INTERFACE,
    state_message,
)
from .planner import PlanningError, TransactionPlanner, package_identity
from .safety import check_secure_boot, read_secure_boot

_ = gettext.gettext
logger = logging.getLogger(__name__)
INSTALL_INFO = {11, 12, 19, 27}  # update/install/reinstall and planned install, PackageKit 1.x
REMOVE_INFO = {13, 15, 28, 29}  # removing/obsoleting and planned remove/obsolete
RESTART_RANK = {value: index for index, value in enumerate(RestartRequirement)}


def effect_identity(reference):
    return package_identity(reference.package_id) if reference.package_id else (reference.name, "", "")


@dataclass(frozen=True)
class DriverSnapshot:
    planner: TransactionPlanner
    secure_boot: SecureBootState
    context: object = None
    evidence: tuple = ()
    installed_packages: tuple = ()


class SnapshotSource:
    """Each load creates a backend in its calling worker; no APT objects escape."""

    def __init__(self, test_mode=False, backend_factory=DriverBackend, secure_boot_reader=None,
                 security_probe=None, scenario="default"):
        self.test_mode = test_mode
        self.backend_factory = backend_factory
        self.secure_boot_reader = secure_boot_reader
        self.security_probe = security_probe or SystemSecurityProbe()
        self.scenario = scenario
        self._installed = {}
        self._selected = {}

    @staticmethod
    def option_key(option):
        return option.package_name, option.option_type, option.builtin

    def load(self, inspection_plan=None):
        kwargs = {}
        context, fixture_states = None, {}
        if self.test_mode:
            kwargs = {"devices": {}, "cache": {}, "extra_devices": make_test_devices(),
                      "package_overrides": TEST_PACKAGE_OVERRIDES}
            context = KernelModuleContext(SecureBootState.DISABLED, False, KernelState.CURRENT,
                                          "test-kernel", "", False, HeadersState.PRESENT)
            if self.scenario != "default":
                devices, overrides, context, fixture_states = scenario_data(self.scenario)
                kwargs.update(extra_devices=devices, package_overrides=overrides)
        backend = self.backend_factory(**kwargs)
        devices = backend.get_devices()
        if self.test_mode and self._installed:
            updated = []
            for device in devices:
                options = tuple(replace(option, installed=self._installed.get(option.package_name, option.installed))
                                for option in device.drivers)
                chosen = self._selected.get(device.device_id)
                current = next((option for option in options if self.option_key(option) == chosen), None)
                if current is None:
                    current = next((option for option in options if option.selected and
                                    (option.installed or option.builtin or option.option_type != DriverOptionType.PACKAGE)), None)
                if current is None:
                    current = next((option for option in options if option.builtin or
                                    option.option_type == DriverOptionType.DISABLE), None)
                if current:
                    options = tuple(replace(option, selected=option == current) for option in options)
                    device = replace(device, drivers=options, status=current.status)
                updated.append(device)
            devices = tuple(updated)
        planner = TransactionPlanner.from_backend(backend, devices, preview_only=self.test_mode)
        if self.test_mode:
            packages, facts = {}, []
            for device in devices:
                for option in device.drivers:
                    if not option.package_name or option.builtin:
                        continue
                    state = fixture_states.get(option.package_name, DkmsState.NO_DKMS)
                    package_id = "%s;%s;all;test" % (option.package_name, option.version)
                    requirement = {DkmsState.NO_DKMS: False, DkmsState.DKMS_REQUIRED: True}.get(state)
                    ref = PackageReference(option.package_name, package_id, requirement)
                    packages[(option.package_name, False)] = ref
                    if option.installed:
                        packages[(option.package_name, True)] = ref
                    facts.append(ModuleEvidence(package_id, state))
            planner = TransactionPlanner(devices, packages, preview_only=True)
            evidence = tuple(facts)
        else:
            context = self.security_probe.probe()
            if self.secure_boot_reader:
                context = replace(context, secure_boot_state=self.secure_boot_reader())
            names = {option.package_name for device in devices for option in device.drivers
                     if option.package_name and not option.builtin}
            if inspection_plan:
                names.update(ref.name for ref in inspection_plan.installs + inspection_plan.removals)
            evidence = backend.module_evidence(names, context.running_kernel)
        installed = tuple((option.package_name, option.installed) for device in devices for option in device.drivers
                          if option.package_name and not option.builtin)
        if inspection_plan and not self.test_mode:
            import apt_pkg
            status_cache = apt_pkg.Cache(None)
            installed = tuple((ref.name, backend.get_packagekit_id(ref.name, True)
                               if ref.name in status_cache and
                               status_cache[ref.name].current_state == apt_pkg.CURSTATE_INSTALLED else False)
                              for ref in inspection_plan.installs + inspection_plan.removals)
        return DriverSnapshot(planner, context.secure_boot_state, context, evidence, installed)

    def inspect(self, plan):
        return self.load(plan)

    def set_scenario(self, name):
        if not self.test_mode:
            raise RuntimeError("Scenarios are only available in explicit test mode")
        scenario_data(name) if name != "default" else None
        self.scenario = name
        self._installed.clear()
        self._selected.clear()

    def record_simulation(self, plan, action):
        if not self.test_mode:
            raise RuntimeError("Only test snapshots may be changed in memory")
        for package in plan.removals if action == TransactionAction.REMOVE else plan.installs:
            self._installed[package.name] = action == TransactionAction.INSTALL
        for selection in plan.selections:
            if action == TransactionAction.INSTALL:
                self._selected[selection.device_id] = self.option_key(selection.target)
            elif not plan.installs:
                self._selected[selection.device_id] = self.option_key(selection.target)
            else:
                self._selected.pop(selection.device_id, None)


class SnapshotWorker(QObject):
    loaded = pyqtSignal(object)
    failed = pyqtSignal(object)
    finished = pyqtSignal()

    def __init__(self, source):
        super().__init__()
        self.source = source

    @pyqtSlot()
    def run(self):
        try:
            self.loaded.emit(self.source.load())
        except Exception:
            logger.exception("driver snapshot failed")
            self.failed.emit(TransactionError("snapshot-failed", _("Driver detection failed. No new transaction was started.")))
        finally:
            self.finished.emit()


class PackageKitAvailability(QObject):
    changed = pyqtSignal(bool, str)

    def __init__(self, parent=None, transport_factory=QtDBusTransport):
        super().__init__(parent)
        self.transport = transport_factory(self)
        self._generation = 0
        self._subscriptions = False
        bus = getattr(self.transport, "bus", None)
        if bus:
            bus.connect("org.freedesktop.DBus", "/org/freedesktop/DBus",
                        "org.freedesktop.DBus", "NameOwnerChanged", self._owner_changed)

    def check(self):
        self._generation += 1
        generation = self._generation

        def introspected(args, error):
            if generation != self._generation:
                return
            if error:
                self.changed.emit(False, _("PackageKit is unavailable. Driver detection is still available."))
                return
            self.transport.call(ROOT_PATH, PROPERTIES_INTERFACE, "GetAll", [SERVICE], properties)

        def properties(args, error):
            if generation != self._generation:
                return
            data = args[0] if args and not error else {}
            if error or data.get("VersionMajor") != 1 or data.get("VersionMinor", 0) < 3:
                self.changed.emit(False, _("This PackageKit version is not supported for applying driver changes."))
            elif data.get("Locked", False):
                self.changed.emit(False, _("PackageKit is busy. Wait for the other package operation to finish."))
            else:
                self.changed.emit(True, "")
            bus = getattr(self.transport, "bus", None)
            if bus and not self._subscriptions:
                bus.connect(SERVICE, ROOT_PATH, PROPERTIES_INTERFACE, "PropertiesChanged", self._properties_changed)
                self._subscriptions = True

        self.transport.call(ROOT_PATH, "org.freedesktop.DBus.Introspectable", "Introspect", [], introspected)

    @pyqtSlot(str, 'QVariantMap', 'QStringList')
    def _properties_changed(self, interface, changed, invalidated):
        if interface == SERVICE and ("Locked" in changed or "Locked" in invalidated):
            self.check()

    @pyqtSlot(str, str, str)
    def _owner_changed(self, name, old_owner, new_owner):
        if name == SERVICE:
            if new_owner:
                self.check()
            else:
                self._generation += 1
                self.changed.emit(False, _("The PackageKit service disconnected."))


class SimulatedTransaction(QObject):
    """Visual test runner. This class never constructs a D-Bus transport."""
    progressChanged = pyqtSignal(object)
    errorOccurred = pyqtSignal(object)
    finished = pyqtSignal(object)

    def __init__(self, planner, parent=None, execution_enabled=False):
        super().__init__(parent)
        self.progress = TransactionProgress(TransactionAction.RESOLVE)
        self._done = False
        self._cancelled = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def resolve(self, plan):
        self._start(plan, TransactionAction.RESOLVE, True)

    def simulate(self, plan, action):
        self._start(plan, action, True)

    def install(self, plan):
        self._start(plan, TransactionAction.INSTALL, False)

    def remove(self, plan):
        self._start(plan, TransactionAction.REMOVE, False)

    def _start(self, plan, action, preview):
        self._action, self._preview, self._step = action, preview, 0
        self._packages = plan.installs if action == TransactionAction.INSTALL else plan.removals
        self._timer.start(10 if preview else 180)

    def _tick(self):
        self._step += 1
        if self._cancelled:
            self._finish(TransactionState.CANCELLED)
            return
        if self._step > (1 if self._preview else 5):
            self._finish(TransactionState.FINISHED)
            return
        state = (TransactionState.RESOLVING if self._preview else
                 TransactionState.REMOVING if self._action == TransactionAction.REMOVE else
                 TransactionState.DOWNLOADING if self._step < 3 else TransactionState.INSTALLING)
        package = self._packages[0].name if self._packages else None
        self.progress = TransactionProgress(self._action, state, None if self._preview else self._step * 20,
                                            package, state_message(state), True)
        self.progressChanged.emit(self.progress)

    def _finish(self, state):
        self._timer.stop()
        self._done = True
        info = 27 if self._action == TransactionAction.INSTALL else 28
        self.finished.emit(TransactionResult(self._action, state, 1 if state == TransactionState.FINISHED else 3,
                                             None, RestartRequirement.NONE, self._packages,
                                             effects=tuple((info, ref) for ref in self._packages)))

    def cancel(self):
        if self._done or not self.progress.allow_cancel:
            return False
        self._cancelled = True
        return True


class DriverExecutionController(QObject):
    busyChanged = pyqtSignal(bool)
    progressChanged = pyqtSignal(object)
    prepared = pyqtSignal(object, bool)
    finished = pyqtSignal(object)
    refreshRequested = pyqtSignal()

    def __init__(self, parent=None, test_mode=False, source=None, transaction_factory=None):
        super().__init__(parent)
        self.test_mode = test_mode
        self.source = source or SnapshotSource(test_mode)
        # Even an injected real transport cannot escape the test-mode boundary.
        self._factory = SimulatedTransaction if test_mode else (transaction_factory or PackageKitTransaction)
        self.active = False
        self.available = test_mode
        self.progress = TransactionProgress(TransactionAction.RESOLVE)
        self._thread = None
        self._worker = None
        self._transaction = None
        self._prepared = None
        self._completed = []
        self._cancel_requested = False
        self._restart = RestartRequirement.NONE

    def can_apply(self, planner, plan):
        if self.active or not self.available or not (plan.installs or plan.removals):
            return False
        try:
            planner.validate_plan(plan, executable=not self.test_mode)
            return self.test_mode or not plan.preview_only
        except PlanningError:
            return False

    def prepare(self, planner, plan):
        if not self.can_apply(planner, plan):
            return False
        self._confirmed = None
        self._plan = None
        self._prepared = None
        self._input_plan = plan
        self._completed = []
        self._restart = RestartRequirement.NONE
        self._cancel_requested = False
        self._set_busy(True)
        self._snapshot()
        return True

    def confirm(self, prepared):
        if self.active or prepared is not self._prepared:
            return False
        if prepared.preflight and prepared.preflight.blockers:
            return False
        if not self.available:
            self._finish(TransactionState.FAILED, TransactionError(
                "service-unavailable", _("PackageKit is unavailable. Driver detection is still available.")))
            return False
        self._confirmed = prepared
        self._input_plan = prepared.plan
        self._cancel_requested = False
        self._set_busy(True)
        self._snapshot()
        return True

    def discard(self, prepared):
        if not self.active and prepared is self._prepared:
            self._finish(TransactionState.CANCELLED)

    def _set_busy(self, busy):
        self.active = busy
        self.busyChanged.emit(busy)

    def _snapshot(self):
        self._snapshot_result = None
        self._snapshot_error = None
        self._progress(TransactionProgress(TransactionAction.RESOLVE, TransactionState.PREPARING,
                                          message=_("Preparing driver changes..."), allow_cancel=True))
        self._thread = QThread(self)
        self._worker = SnapshotWorker(self.source)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.loaded.connect(self._store_snapshot)
        self._worker.failed.connect(self._store_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._snapshot_finished)
        self._thread.start()

    @pyqtSlot(object)
    def _store_snapshot(self, snapshot):
        self._snapshot_result = snapshot

    @pyqtSlot(object)
    def _store_error(self, error):
        self._snapshot_error = error

    @pyqtSlot()
    def _snapshot_finished(self):
        self._thread, self._worker = None, None
        if self._cancel_requested:
            self._finish(TransactionState.CANCELLED)
            return
        if self._snapshot_error:
            self._finish(TransactionState.FAILED, self._snapshot_error)
            return
        snapshot = self._snapshot_result
        self._secure_boot = snapshot.secure_boot
        self._context = snapshot.context
        self._evidence = snapshot.evidence
        try:
            self._planner = snapshot.planner
            self._plan = self._planner.rebuild(self._input_plan)
            self._planner.validate_plan(self._plan, executable=not self.test_mode)
            if not self.test_mode and self._context is None:
                check_secure_boot(self._plan, snapshot.secure_boot)
            if not (self._plan.installs or self._plan.removals):
                self._finish(TransactionState.FINISHED)
                return
        except PlanningError as error:
            self._finish(TransactionState.FAILED, TransactionError("invalid-plan", str(error)))
            return
        self._install_effects = {effect_identity(ref): ref for ref in self._plan.installs}
        self._remove_effects = {effect_identity(ref): ref for ref in self._plan.removals}
        self._checks = [("resolve", None)]
        if self._plan.removals:
            self._checks.append(("simulate", TransactionAction.REMOVE))
        if self._plan.installs:
            self._checks.append(("simulate", TransactionAction.INSTALL))
        logger.info("plan created installs=%d removals=%d test=%s", len(self._plan.installs), len(self._plan.removals), self.test_mode)
        self._next_check()

    def _new_transaction(self):
        if self._transaction:
            self._transaction.deleteLater()
        self._transaction = self._factory(self._planner, self, execution_enabled=True)
        self._transaction.progressChanged.connect(self._progress)
        self._transaction.errorOccurred.connect(lambda error: logger.warning("PackageKit error code=%s", error.error_code))
        return self._transaction

    def _next_check(self):
        if self._cancel_requested:
            self._finish(TransactionState.CANCELLED)
        elif self._checks:
            method, action = self._checks.pop(0)
            transaction = self._new_transaction()
            transaction.finished.connect(lambda result: self._checked(result, method, action))
            if method == "resolve":
                transaction.resolve(self._plan)
            else:
                transaction.simulate(self._plan, action)
        else:
            preflight = (DriverPreflight(self._context, self._evidence).check(
                tuple(self._install_effects.values()), resolved=True) if self._context else None)
            candidate = PreparedPlan(self._plan, tuple(sorted(self._install_effects.values(), key=effect_identity)),
                                     tuple(sorted(self._remove_effects.values(), key=effect_identity)), self.test_mode, preflight)
            if preflight and preflight.blockers:
                self._prepared = candidate
                self._set_busy(False)
                self.prepared.emit(candidate, False)
                return
            if self._confirmed and candidate == self._confirmed:
                self._stages = []
                if self._plan.removals:
                    self._stages.append(TransactionAction.REMOVE)
                if self._plan.installs:
                    self._stages.append(TransactionAction.INSTALL)
                self._next_stage()
            else:
                changed = self._confirmed is not None or self._plan != self._input_plan
                self._prepared = candidate
                self._set_busy(False)
                self.prepared.emit(candidate, changed)

    def _checked(self, result, method, action):
        if result.state != TransactionState.FINISHED:
            self._finish(result.state, result.error)
            return
        if method == "simulate":
            try:
                self._verify_effects(result, action)
            except PlanningError as error:
                self._finish(TransactionState.FAILED, TransactionError("unsafe-dependencies", str(error)))
                return
        self._next_check()

    def _verify_effects(self, result, action, after_removal=False):
        if any(info in {20, 30} for info, ref in result.effects):
            raise PlanningError(_("PackageKit proposed a package downgrade. This beta cannot apply this plan safely."))
        if any(info == 23 for info, ref in result.effects):
            raise PlanningError(_("PackageKit reported an untrusted package. No further transaction was started."))
        installs = [ref for info, ref in result.effects if info in INSTALL_INFO]
        removals = [ref for info, ref in result.effects if info in REMOVE_INFO]
        allowed = {ref.name: ref for ref in self._plan.removals}
        for ref in removals:
            if after_removal or ref.name not in allowed:
                raise PlanningError(_("PackageKit proposed additional removals outside the confirmed driver plan."))
            if ref.package_id and allowed[ref.name].package_id and package_identity(ref.package_id) != package_identity(allowed[ref.name].package_id):
                raise PlanningError(_("A package selected for removal changed version. Review the plan again."))
        expected = self._plan.installs if action == TransactionAction.INSTALL else self._plan.removals
        effects = installs if action == TransactionAction.INSTALL else removals
        roots = {ref.name: ref for ref in expected}
        if any(ref.name in roots and ref.package_id and roots[ref.name].package_id and
               package_identity(ref.package_id) != package_identity(roots[ref.name].package_id) for ref in effects):
            raise PlanningError(_("A target package changed version or architecture. Review the detected plan again."))
        if self._context is None and not self.test_mode and self._secure_boot not in (SecureBootState.DISABLED, SecureBootState.UNSUPPORTED) and any(
                ref.name == "dkms" or ref.name.endswith("-dkms") or "-dkms-" in ref.name for ref in installs):
            raise PlanningError(_("This driver requires a Secure Boot flow that is not supported by this beta."))
        if not {ref.name for ref in expected} <= {ref.name for ref in effects}:
            raise PlanningError(_("PackageKit could not safely simulate all planned changes."))
        if action == TransactionAction.REMOVE and installs:
            raise PlanningError(_("The removal simulation requires unexpected package installations."))
        if after_removal:
            if self._context:
                preflight = DriverPreflight(self._context, self._evidence).check(tuple(installs), resolved=True)
                if preflight.blockers:
                    raise PlanningError("\n".join(issue.message for issue in preflight.blockers))
            confirmed = {effect_identity(ref) for ref in self._confirmed.installs}
            if {effect_identity(ref) for ref in installs} != confirmed:
                raise PlanningError(_("Installation dependencies changed after removal. No further change was applied."))
        else:
            for ref in installs:
                self._install_effects.setdefault(effect_identity(ref), ref)
            for ref in removals:
                self._remove_effects.setdefault(effect_identity(ref), ref)

    def _next_stage(self):
        if not self._stages:
            self._finish(TransactionState.FINISHED)
        elif self._cancel_requested:
            self._finish(TransactionState.CANCELLED)
        else:
            action = self._stages.pop(0)
            if action == TransactionAction.INSTALL and self._completed:
                # A fresh simulation now evaluates dependencies without the removed driver.
                transaction = self._new_transaction()
                transaction.finished.connect(self._installation_rechecked)
                transaction.simulate(self._plan, action)
            else:
                self._run_stage(action)

    def _installation_rechecked(self, result):
        if result.state != TransactionState.FINISHED:
            self._finish(result.state, result.error)
            return
        try:
            self._verify_effects(result, TransactionAction.INSTALL, after_removal=True)
        except PlanningError as error:
            self._finish(TransactionState.FAILED, TransactionError("changed-dependencies", str(error)))
            return
        if self._cancel_requested:
            self._finish(TransactionState.CANCELLED)
        else:
            self._run_stage(TransactionAction.INSTALL)

    def _run_stage(self, action):
        transaction = self._new_transaction()
        transaction.finished.connect(self._stage_finished)
        logger.info("driver mutation started role=%s test=%s", action.value, self.test_mode)
        if action == TransactionAction.REMOVE:
            transaction.remove(self._plan)
        else:
            transaction.install(self._plan)

    def _stage_finished(self, result):
        if RESTART_RANK[result.restart] > RESTART_RANK[self._restart]:
            self._restart = result.restart
        if result.state != TransactionState.FINISHED:
            error = result.error
            if result.mutation_observed:
                error = replace(error, outcome_unknown=True) if error else TransactionError(
                    "interrupted-mutation", _("The package operation was interrupted after changes started."), outcome_unknown=True)
            self._finish(result.state, error)
            return
        self._completed.append(result)
        allowed = {effect_identity(ref) for ref in self._confirmed.removals}
        if any(info in REMOVE_INFO and effect_identity(ref) not in allowed for info, ref in result.effects):
            self._finish(TransactionState.PARTIAL_FAILURE, TransactionError(
                "unexpected-removal", _("PackageKit reported an unexpected removal. No further transaction was started.")))
            return
        if self.test_mode:
            self.source.record_simulation(self._plan, result.action)
        self._next_stage()

    @pyqtSlot(object)
    def _progress(self, progress):
        self.progress = progress
        self.progressChanged.emit(progress)

    def cancel(self):
        if not self.active or not self.progress.allow_cancel:
            return False
        if self._thread is not None or (self._transaction and self._transaction.cancel()):
            self._cancel_requested = True
            self._progress(replace(self.progress, cancel_requested=True, allow_cancel=False))
            return True
        return False

    def _finish(self, state, error=None):
        if state == TransactionState.CANCELLED and error is None:
            error = TransactionError("user-cancelled", _("The operation was cancelled."), cancelled=True)
        if state != TransactionState.FINISHED and (self._completed or (error and error.outcome_unknown)):
            state = TransactionState.PARTIAL_FAILURE
        if self._completed and not self.test_mode and RESTART_RANK[self._restart] < RESTART_RANK[self._plan.restart]:
            self._restart = self._plan.restart
        if state == TransactionState.FINISHED and self._completed and any(
                selection.device_id in {device.device_id for device in self._planner.devices if device.icon_key == "broadcom"}
                and selection.target.package_name for selection in self._plan.selections):
            self._restart = RestartRequirement.SYSTEM
        self._prepared = None
        self._set_busy(False)
        logger.info("driver workflow finished state=%s stages=%d error=%s", state.value, len(self._completed),
                    error.error_code if error else None)
        self.finished.emit(ExecutionResult(state, tuple(self._completed), error, self._restart, self.test_mode,
                                          plan=getattr(self, "_plan", None)))
        self.refreshRequested.emit()
