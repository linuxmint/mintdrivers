# SPDX-License-Identifier: GPL-2.0-or-later
"""Asynchronous PackageKit D-Bus client. No widgets or GLib dependencies."""
import gettext
import re
from dataclasses import replace

from PyQt6.QtCore import QObject, QMetaType, pyqtSignal, pyqtSlot
from PyQt6 import QtDBus

from .models import (
    PackageReference, RestartRequirement, TransactionAction, TransactionError,
    TransactionProgress, TransactionResult, TransactionState,
)
from .planner import PlanningError, package_identity, reboot_required


_ = gettext.gettext
SERVICE = "org.freedesktop.PackageKit"
ROOT_PATH = "/org/freedesktop/PackageKit"
TRANSACTION_INTERFACE = SERVICE + ".Transaction"
PROPERTIES_INTERFACE = "org.freedesktop.DBus.Properties"

# Stable PackageKit 1.x enum values; flags are bitfields, not enum ordinals.
FILTER_NONE = 1 << 1
ONLY_TRUSTED = 1 << 1
STATUS_MAP = {
    0: TransactionState.PREPARING, 1: TransactionState.WAITING,
    2: TransactionState.PREPARING, 3: TransactionState.PREPARING,
    4: TransactionState.RESOLVING, 5: TransactionState.RESOLVING,
    6: TransactionState.REMOVING, 7: TransactionState.PREPARING,
    8: TransactionState.DOWNLOADING, 9: TransactionState.INSTALLING,
    10: TransactionState.INSTALLING, 11: TransactionState.FINALIZING,
    12: TransactionState.REMOVING, 13: TransactionState.RESOLVING,
    14: TransactionState.PREPARING, 15: TransactionState.PREPARING,
    16: TransactionState.FINALIZING, 17: TransactionState.WAITING,
    18: TransactionState.FINALIZING, 19: TransactionState.CANCELLING,
    20: TransactionState.DOWNLOADING, 21: TransactionState.DOWNLOADING,
    22: TransactionState.DOWNLOADING, 23: TransactionState.DOWNLOADING,
    24: TransactionState.DOWNLOADING, 25: TransactionState.PREPARING,
    26: TransactionState.PREPARING, 27: TransactionState.WAITING,
    28: TransactionState.WAITING, 29: TransactionState.INSTALLING,
    30: TransactionState.FINALIZING,
}
RESTART_MAP = {
    0: RestartRequirement.UNKNOWN, 1: RestartRequirement.NONE,
    2: RestartRequirement.APPLICATION, 3: RestartRequirement.SESSION,
    4: RestartRequirement.SYSTEM, 5: RestartRequirement.SESSION,
    6: RestartRequirement.SYSTEM,
}


def state_message(state):
    return {
        TransactionState.WAITING: _("Waiting..."),
        TransactionState.PREPARING: _("Preparing..."),
        TransactionState.RESOLVING: _("Resolving dependencies..."),
        TransactionState.DOWNLOADING: _("Downloading..."),
        TransactionState.INSTALLING: _("Installing..."),
        TransactionState.REMOVING: _("Removing..."),
        TransactionState.FINALIZING: _("Finalizing..."),
        TransactionState.CANCELLING: _("Cancelling..."),
        TransactionState.FINISHED: _("Finished."),
        TransactionState.FAILED: _("Transaction failed."),
        TransactionState.CANCELLED: _("Transaction cancelled."),
    }[state]


class QtDBusTransport(QObject):
    """Small replaceable transport: call(), subscribe(), unsubscribe()."""

    eventReceived = pyqtSignal(str, object)
    serviceLost = pyqtSignal()

    def __init__(self, parent=None, connection=None):
        super().__init__(parent)
        self.bus = connection or QtDBus.QDBusConnection.systemBus()
        self._subscriptions = []
        self._watchers = set()

    def call(self, path, interface, method, arguments, callback):
        if not self.bus.isConnected():
            callback([], TransactionError("service-unavailable", _("The system bus is unavailable.")))
            return
        message = QtDBus.QDBusMessage.createMethodCall(SERVICE, path, interface, method)
        args = list(arguments)
        if method in ("Resolve", "InstallPackages", "RemovePackages"):
            args[0] = QtDBus.QDBusArgument(args[0], QMetaType.Type.ULongLong.value)
            args[1] = QtDBus.QDBusArgument(args[1], QMetaType.Type.QStringList.value)
        elif method == "SetHints":
            args[0] = QtDBus.QDBusArgument(args[0], QMetaType.Type.QStringList.value)
        message.setArguments(args)
        message.setInteractiveAuthorizationAllowed(method in ("InstallPackages", "RemovePackages"))
        watcher = QtDBus.QDBusPendingCallWatcher(self.bus.asyncCall(message, 30000), self)
        self._watchers.add(watcher)

        def completed(pending):
            reply = QtDBus.QDBusPendingReply(pending).reply()
            error = None
            if reply.type() == QtDBus.QDBusMessage.MessageType.ErrorMessage:
                name = reply.errorName()
                error = TransactionError(
                    name, reply.errorMessage(),
                    authorization_denied=name.endswith(("Denied", "NotAuthorized", "AccessDenied")),
                )
            self._watchers.discard(pending)
            pending.deleteLater()
            callback(reply.arguments(), error)

        watcher.finished.connect(completed)

    def subscribe(self, path):
        connections = [
            (SERVICE, path, TRANSACTION_INTERFACE, name, self._event)
            for name in ("Package", "ErrorCode", "Finished", "RequireRestart", "ItemProgress", "Destroy")
        ]
        connections.append((SERVICE, path, PROPERTIES_INTERFACE, "PropertiesChanged", self._event))
        connections.append(("org.freedesktop.DBus", "/org/freedesktop/DBus",
                            "org.freedesktop.DBus", "NameOwnerChanged", self._owner_changed))
        for connection in connections:
            if not self.bus.connect(*connection):
                self.unsubscribe()
                return False
            self._subscriptions.append(connection)
        return True

    def unsubscribe(self):
        for connection in self._subscriptions:
            self.bus.disconnect(*connection)
        self._subscriptions.clear()

    @pyqtSlot(QtDBus.QDBusMessage)
    def _event(self, message):
        self.eventReceived.emit(message.member(), message.arguments())

    @pyqtSlot(str, str, str)
    def _owner_changed(self, name, old_owner, new_owner):
        if name == SERVICE and old_owner and old_owner != new_owner:
            self.serviceLost.emit()


class PackageKitTransaction(QObject):
    """Single-use transaction; modifying methods first resolve the exact plan.

    execution_enabled is deliberately false by default. The current frontend
    never enables it. A fresh daemon object path is used for each operation.
    """

    progressChanged = pyqtSignal(object)
    statusChanged = pyqtSignal(object)
    percentageChanged = pyqtSignal(object)
    packageChanged = pyqtSignal(object)
    errorOccurred = pyqtSignal(object)
    restartRequired = pyqtSignal(object)
    finished = pyqtSignal(object)

    def __init__(self, planner, parent=None, transport_factory=None, execution_enabled=False):
        super().__init__(parent)
        self.planner = planner
        self._transport_factory = transport_factory or QtDBusTransport
        self.transport = self._transport_factory(self)
        self.transport.eventReceived.connect(self._event)
        self.transport.serviceLost.connect(self._service_lost)
        self.execution_enabled = execution_enabled
        self.progress = TransactionProgress(TransactionAction.RESOLVE)
        self._started = False
        self._done = False
        self._error = None
        self._path = None
        self._packages = {}
        self._expected = set()
        self._validator = None

    def resolve(self, plan):
        self._prepare(plan, TransactionAction.RESOLVE)

    def install(self, plan):
        self._prepare(plan, TransactionAction.INSTALL)

    def remove(self, plan):
        self._prepare(plan, TransactionAction.REMOVE)

    def _prepare(self, plan, action):
        if self._started:
            raise RuntimeError("PackageKit transaction objects cannot be reused")
        self._started = True
        self.progress = TransactionProgress(action, message=state_message(TransactionState.WAITING))
        try:
            self.planner.validate_plan(plan, executable=True)
        except PlanningError as error:
            self._fail(TransactionError("invalid-plan", str(error)))
            return
        if action != TransactionAction.RESOLVE and not self.execution_enabled:
            self._fail(TransactionError("execution-disabled", _("Driver changes are not enabled in this interface.")))
            return
        references = (plan.installs if action == TransactionAction.INSTALL else
                      plan.removals if action == TransactionAction.REMOVE else
                      plan.installs + plan.removals)
        if not references:
            self._complete(TransactionState.FINISHED, 1)
            return
        self._expected = {package_identity(ref.package_id) for ref in references}
        if action != TransactionAction.RESOLVE:
            self._validator = PackageKitTransaction(
                self.planner, self, transport_factory=self._transport_factory)
            self._validator.progressChanged.connect(self._validation_progress)
            self._validator.finished.connect(lambda result: self._validated(result, action, references))
            self._validator.resolve(plan)
        else:
            self._begin(action, references)

    def _validation_progress(self, progress):
        self._update(state=progress.state, percentage=progress.percentage,
                     package_id=progress.package_id, message=progress.message,
                     allow_cancel=progress.allow_cancel,
                     cancel_requested=progress.cancel_requested, restart=progress.restart)

    def _validated(self, result, action, references):
        if self._done:
            return
        if result.state != TransactionState.FINISHED:
            self._error = result.error
            if self._error and not self._error.cancelled:
                self.errorOccurred.emit(self._error)
            self._complete(result.state, result.exit_code)
            return
        if result.cancel_requested or self.progress.cancel_requested:
            self._error = TransactionError("cancelled-before-execution",
                                           _("Transaction cancelled."), cancelled=True)
            self._complete(TransactionState.CANCELLED, 3)
            return
        self.progress = TransactionProgress(action)
        self._begin(action, references)

    def _begin(self, action, references):
        self._operation = ("Resolve", [FILTER_NONE, sorted({ref.name for ref in references})])
        if action == TransactionAction.INSTALL:
            self._operation = ("InstallPackages", [ONLY_TRUSTED, [ref.package_id for ref in references]])
        elif action == TransactionAction.REMOVE:
            # No dependent-package removals and no global autoremove.
            self._operation = ("RemovePackages", [0, [ref.package_id for ref in references], False, False])
        self._update(state=TransactionState.PREPARING)
        self.transport.call(ROOT_PATH, "org.freedesktop.DBus.Introspectable", "Introspect", [], self._available)

    def _available(self, args, error):
        if self._done:
            return
        if error:
            self._fail(TransactionError("service-unavailable", error.details, authorization_denied=error.authorization_denied))
            return
        self.transport.call(ROOT_PATH, SERVICE, "CreateTransaction", [], self._created)

    def _created(self, args, error):
        if self._done:
            return
        if error:
            self._fail(error)
            return
        path = args[0] if args else None
        self._path = path.path() if isinstance(path, QtDBus.QDBusObjectPath) else path
        if (not isinstance(self._path, str) or self._path == ROOT_PATH
                or not re.fullmatch(r"(?:/[A-Za-z0-9_]+)+", self._path)):
            self._fail(TransactionError("invalid-path", "PackageKit returned an invalid transaction path"))
            return
        if not self.transport.subscribe(self._path):
            self._fail(TransactionError("signal-connection", "Cannot subscribe to PackageKit signals"))
            return
        self.transport.call(self._path, PROPERTIES_INTERFACE, "GetAll", [TRANSACTION_INTERFACE], self._initial_properties)

    def _initial_properties(self, args, error):
        if self._done:
            return
        if error:
            self._fail(error)
            return
        if args:
            self._properties(args[0])
        hints = ["interactive=" + ("false" if self.progress.action == TransactionAction.RESOLVE else "true"),
                 "cache-age=2147483647"]
        # Omitting supports-plural-signals requests the supported Package signal.
        self.transport.call(self._path, TRANSACTION_INTERFACE, "SetHints", [hints], self._hinted)

    def _hinted(self, args, error):
        if self._done:
            return
        if error:
            self._fail(error)
            return
        method, arguments = self._operation
        self.transport.call(self._path, TRANSACTION_INTERFACE, method, arguments, self._method_reply)

    def _method_reply(self, args, error):
        if error and not self._done:
            self._fail(error)

    @pyqtSlot(str, object)
    def _event(self, name, args):
        if self._done:
            return
        if name == "PropertiesChanged" and args[0] == TRANSACTION_INTERFACE:
            self._properties(args[1])
            if args[2]:
                self.transport.call(self._path, PROPERTIES_INTERFACE, "GetAll", [TRANSACTION_INTERFACE], self._refresh_properties)
        elif name == "Package":
            info, package_id, summary = args
            try:
                identity = package_identity(package_id)
            except PlanningError:
                self._fail(TransactionError("invalid-package-id", str(package_id)))
                return
            self._packages[identity] = PackageReference(identity[0], package_id)
            self._update(package_id=package_id)
        elif name == "ItemProgress":
            package_id, status, percentage = args
            # Item percentage is not the overall transaction percentage.
            self._update(package_id=package_id, state=STATUS_MAP.get(status, TransactionState.PREPARING))
        elif name == "ErrorCode":
            code, details = args
            self._error = TransactionError(code, details, cancelled=code in (17, 61), authorization_denied=code == 46)
            if not self._error.cancelled:
                self.errorOccurred.emit(self._error)
        elif name == "RequireRestart":
            restart = RESTART_MAP.get(args[0], RestartRequirement.UNKNOWN)
            rank = list(RestartRequirement)
            if rank.index(restart) > rank.index(self.progress.restart):
                self._update(restart=restart)
                self.restartRequired.emit(restart)
        elif name == "Finished":
            exit_code, runtime = args
            if exit_code in (3, 8) or (self._error and self._error.cancelled):
                self._complete(TransactionState.CANCELLED, exit_code, runtime)
            elif exit_code == 1 and not self._error:
                if self.progress.action == TransactionAction.RESOLVE and not self._expected <= set(self._packages):
                    self._fail(TransactionError("package-unavailable", _("The planned package version is no longer available.")), exit_code)
                else:
                    self._complete(TransactionState.FINISHED, exit_code, runtime)
            else:
                if self._error is None:
                    self._error = TransactionError("packagekit-exit-" + str(exit_code), _("PackageKit did not complete the transaction."))
                    self.errorOccurred.emit(self._error)
                self._complete(TransactionState.FAILED, exit_code, runtime)
        elif name == "Destroy":
            self._fail(TransactionError("transaction-destroyed", "PackageKit destroyed the transaction before Finished"))

    def _refresh_properties(self, args, error):
        if not self._done and not error and args:
            self._properties(args[0])

    def _properties(self, properties):
        changes = {}
        if "Status" in properties:
            changes["state"] = STATUS_MAP.get(properties["Status"], TransactionState.PREPARING)
        if "Percentage" in properties:
            percentage = properties["Percentage"]
            changes["percentage"] = percentage if 0 <= percentage <= 100 else None
        if "LastPackage" in properties:
            changes["package_id"] = properties["LastPackage"] or None
        if "AllowCancel" in properties:
            changes["allow_cancel"] = properties["AllowCancel"]
        self._update(**changes)

    def _update(self, **changes):
        if "state" in changes:
            changes["message"] = state_message(changes["state"])
        previous = self.progress
        self.progress = replace(previous, **changes)
        if previous.state != self.progress.state:
            self.statusChanged.emit(self.progress.state)
        if previous.percentage != self.progress.percentage:
            self.percentageChanged.emit(self.progress.percentage)
        if previous.package_id != self.progress.package_id:
            self.packageChanged.emit(self.progress.package_id)
        self.progressChanged.emit(self.progress)

    def cancel(self):
        if self._done or not self._started:
            return False
        if self._validator and not self._validator._done:
            accepted = self._validator.cancel()
            if accepted:
                self._update(cancel_requested=True)
            return accepted
        if not self._path or not self.progress.allow_cancel or self.progress.cancel_requested:
            return False
        self._update(cancel_requested=True)
        self.transport.call(self._path, TRANSACTION_INTERFACE, "Cancel", [], self._cancel_reply)
        return True

    def _cancel_reply(self, args, error):
        if error and not self._done:
            self._update(cancel_requested=False)
            self.errorOccurred.emit(error)

    @pyqtSlot()
    def _service_lost(self):
        if not self._done:
            self._fail(TransactionError("service-lost", _("The PackageKit service disconnected.")))

    def _fail(self, error, exit_code=None):
        self._error = error
        if not error.cancelled:
            self.errorOccurred.emit(error)
        self._complete(TransactionState.CANCELLED if error.cancelled else TransactionState.FAILED, exit_code)

    def _complete(self, state, exit_code, runtime=0):
        if self._done:
            return
        self._done = True
        self.transport.unsubscribe()
        # Resolution alone never causes or newly reports a reboot requirement.
        if self.progress.action != TransactionAction.RESOLVE and reboot_required():
            self._update(restart=RestartRequirement.SYSTEM)
            self.restartRequired.emit(RestartRequirement.SYSTEM)
        self._update(state=state, allow_cancel=False)
        self.finished.emit(TransactionResult(
            self.progress.action, state, exit_code, self._error, self.progress.restart,
            tuple(self._packages.values()), runtime, self.progress.cancel_requested,
        ))


class DriverTransactionController(QObject):
    """Driver selections and transaction signals, without D-Bus in widgets."""

    planChanged = pyqtSignal(object)
    progressChanged = pyqtSignal(object)
    errorOccurred = pyqtSignal(object)
    finished = pyqtSignal(object)

    def __init__(self, planner, parent=None, transport_factory=None, execution_enabled=False):
        super().__init__(parent)
        self.planner = planner
        self.desired = {}
        self._transaction = None
        self._transport_factory = transport_factory
        self.execution_enabled = execution_enabled

    def select(self, device, option):
        if device not in self.planner.devices:
            raise PlanningError("Unknown backend device")
        desired = {**self.desired, device.device_id: option}
        plan = self.planner.build(desired)
        self.desired = desired
        self.planChanged.emit(plan)
        return plan

    def plan(self):
        return self.planner.build(self.desired)

    def resolve(self, plan):
        return self._start(plan, "resolve")

    def install(self, plan):
        return self._start(plan, "install")

    def remove(self, plan):
        return self._start(plan, "remove")

    def _start(self, plan, method):
        if self._transaction and not self._transaction._done:
            raise RuntimeError("A driver transaction is already running")
        if self._transaction:
            self._transaction.deleteLater()
        self._transaction = PackageKitTransaction(
            self.planner, self, self._transport_factory, self.execution_enabled)
        self._transaction.progressChanged.connect(self.progressChanged)
        self._transaction.errorOccurred.connect(self.errorOccurred)
        self._transaction.finished.connect(self.finished)
        getattr(self._transaction, method)(plan)
        return self._transaction

    def cancel(self):
        return bool(self._transaction and self._transaction.cancel())
