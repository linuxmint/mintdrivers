#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Development-only hello probe. Never imported or installed by the application."""
import argparse
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import signal
import sys
from typing import Optional

# The checkout is not a Python installation; this path is confined to the probe.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] /
                       "usr/lib/mainuan/mainuan-gestao-drivers"))

from PyQt6.QtCore import QCoreApplication, QEventLoop, QTimer

from mainuan_drivers.backend import DriverBackend
from mainuan_drivers.backend.transactions.models import (
    PackageReference, TransactionAction, TransactionPlan, TransactionState,
)
from mainuan_drivers.backend.transactions.packagekit import (
    PackageKitTransaction, QtDBusTransport,
)
from mainuan_drivers.backend.transactions.planner import PlanningError, package_identity


NAME = "hello"
log = logging.getLogger("packagekit-mutation-probe")


class ProbeError(RuntimeError):
    pass


@dataclass(frozen=True)
class Snapshot:
    candidate: Optional[PackageReference] = None
    installed: Optional[PackageReference] = None
    present: bool = False


def require_normal_user():
    if os.geteuid() == 0:
        raise ProbeError("Execute como usuario normal, nunca como root ou com sudo.")


def read_snapshot():
    """Fresh read-only APT metadata, including incomplete dpkg installations."""
    import apt
    import apt_pkg

    with apt.Cache() as cache:
        backend = DriverBackend(cache=cache)
        package = cache.get(NAME)
        candidate = (PackageReference(NAME, backend.get_packagekit_id(NAME, False))
                     if package and package.candidate else None)
        installed = (PackageReference(NAME, backend.get_packagekit_id(NAME, True))
                     if package and package.installed else None)
    low_cache = apt_pkg.Cache(None)
    state = low_cache[NAME].current_state if NAME in low_cache else apt_pkg.CURSTATE_NOT_INSTALLED
    present = state not in (apt_pkg.CURSTATE_NOT_INSTALLED, apt_pkg.CURSTATE_CONFIG_FILES)
    return Snapshot(candidate, installed if state == apt_pkg.CURSTATE_INSTALLED else None, present)


def select_package(packages, expected):
    identity = package_identity(expected.package_id)
    matches = {ref for ref in packages if package_identity(ref.package_id) == identity}
    if identity[0] != NAME or len(matches) != 1:
        raise ProbeError("Resolve nao retornou um ID unico para a versao candidata de hello.")
    return matches.pop()


class HelloPlans:
    """Test-only fixed-package plan source, NOT the application's driver planner.

    Production transactions need validate_plan(). Only exact plans issued here
    are accepted; no devices, driver fixtures or arbitrary package input exist.
    """

    def __init__(self):
        self._issued = []

    def issue(self, action, reference):
        if action not in (TransactionAction.INSTALL, TransactionAction.REMOVE):
            raise PlanningError("Only hello installation/removal is supported")
        if reference.name != NAME or package_identity(reference.package_id)[0] != NAME:
            raise PlanningError("Only hello is allowed")
        plan = TransactionPlan((), (reference,) if action == TransactionAction.INSTALL else (),
                               (reference,) if action == TransactionAction.REMOVE else (), action)
        self._issued.append(plan)
        return plan

    def validate_plan(self, plan, executable=False):
        if not any(plan is issued for issued in self._issued):
            raise PlanningError("Plan not issued by this hello probe session")


class LoggingTransport(QtDBusTransport):
    """Observe the real transport without reimplementing its D-Bus protocol."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.eventReceived.connect(lambda name, args: log.info("Signal %s: %r", name, args))

    def call(self, path, interface, method, arguments, callback):
        log.info("D-Bus %s %s", method, path)
        if method in ("InstallPackages", "RemovePackages"):
            log.info("Waiting for authorization via PackageKit / session PolicyKit agent")
        super().call(path, interface, method, arguments, callback)

    def subscribe(self, path):
        log.info("Transaction created: %s", path)
        return super().subscribe(path)


class QtRunner:
    def __init__(self, timeout_seconds=1800, transport_factory=LoggingTransport):
        self.timeout_ms = timeout_seconds * 1000
        self.transport_factory = transport_factory
        self.active = None

    def cancel(self, *_):
        if self.active and self.active.progress.allow_cancel:
            log.info("Cancellation requested: %s", self.active.cancel())
        else:
            log.warning("Cancellation not allowed now; waiting. PackageKit will not be killed.")

    def __call__(self, plans, plan, method):
        transaction = PackageKitTransaction(
            plans, transport_factory=self.transport_factory,
            execution_enabled=method in ("install", "remove"))
        loop = QEventLoop()
        results = []

        def finished(result):
            log.info("Finished: state=%s exit=%s restart=%s", result.state.value,
                     result.exit_code, result.restart.value)
            results.append(result)
            loop.quit()

        def progress(value):
            log.info("Status: %s (%s); Percentage: %s; Package: %s; AllowCancel: %s",
                     value.state.value, value.message,
                     value.percentage if value.percentage is not None else "unknown",
                     value.package_id or "-", value.allow_cancel)

        transaction.progressChanged.connect(progress)
        transaction.errorOccurred.connect(lambda error: log.error(
            "PackageKit error code=%s details=%s cancelled=%s authorization_denied=%s outcome_unknown=%s",
            error.error_code, error.details, error.cancelled,
            error.authorization_denied, error.outcome_unknown))
        transaction.finished.connect(finished)
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        # Let Python dispatch SIGINT while Qt waits for D-Bus; no job polling.
        heartbeat = QTimer()
        heartbeat.timeout.connect(lambda: None)
        previous_handler = signal.signal(signal.SIGINT, self.cancel)
        self.active = transaction
        try:
            timer.start(self.timeout_ms)
            heartbeat.start(250)
            getattr(transaction, method)(plan)
            if not results:
                loop.exec()
        finally:
            timer.stop()
            heartbeat.stop()
            self.active = None
            signal.signal(signal.SIGINT, previous_handler)
        if not results:
            # Do not cancel, retry, remove or kill anything after an uncertain job.
            raise ProbeError("Timeout: PackageKit pode continuar trabalhando. Verifique o estado manualmente.")
        transaction.deleteLater()
        return results[0]


def confirm(action):
    phrase = ("INSTALAR" if action == "install" else "REMOVER") + " hello"
    return input("Confirme digitando '%s': " % phrase).strip() == phrase


class ProbeSession:
    def __init__(self, runner, read=read_snapshot, confirmation=confirm):
        self.runner = runner
        self.read = read
        self.confirmation = confirmation
        self.plans = HelloPlans()
        self.installed_by_probe = False
        self.owned = None
        self.candidate = None

    def precheck(self):
        require_normal_user()
        snapshot = self.read()
        if snapshot.present or snapshot.installed:
            raise ProbeError("O pacote hello ja estava instalado antes do teste. O probe nao ira altera-lo.")
        if not snapshot.candidate:
            raise ProbeError("hello nao possui versao candidata no APT.")
        log.info("Checking PackageKit; resolving hello (read-only)")
        plan = self.plans.issue(TransactionAction.INSTALL, snapshot.candidate)
        result = self.runner(self.plans, plan, "resolve")
        if result.state != TransactionState.FINISHED:
            raise ProbeError("PackageKit / Resolve indisponivel: %s" % (result.error or result.state.value))
        self.candidate = select_package(result.packages, snapshot.candidate)
        log.info("Candidate version: %s; PackageKit ID: %s",
                 package_identity(self.candidate.package_id)[1], self.candidate.package_id)

    def install(self):
        if not self.candidate or self.installed_by_probe:
            raise ProbeError("Execute a pre-checagem antes da instalacao.")
        if not self.confirmation("install"):
            log.info("Instalacao nao confirmada; nenhuma mutacao solicitada.")
            return False
        current = self.read()
        if current.present or current.installed or not current.candidate or (
                package_identity(current.candidate.package_id) != package_identity(self.candidate.package_id)):
            raise ProbeError("O estado/candidato de hello mudou. Reinicie o probe; nenhuma mutacao solicitada.")
        plan = self.plans.issue(TransactionAction.INSTALL, self.candidate)
        result = self.runner(self.plans, plan, "install")
        if result.state == TransactionState.FINISHED:
            self.installed_by_probe = True
            self.owned = self.candidate
        after = self.read()
        if result.error and result.error.authorization_denied and not result.error.outcome_unknown:
            if not after.present and not after.installed:
                log.info("PASS: authorization cancelled")
                log.info("PASS: system unchanged")
                return False
            raise ProbeError("Autorizacao negada, mas o estado mudou; verifique hello manualmente.")
        if result.state == TransactionState.CANCELLED and not (
                result.error and result.error.outcome_unknown) and not after.present and not after.installed:
            log.info("PASS: transaction cancelled")
            log.info("PASS: system unchanged")
            return False
        if result.state != TransactionState.FINISHED:
            raise ProbeError("Instalacao nao concluida: state=%s error=%r" % (result.state.value, result.error))
        if not after.installed or package_identity(after.installed.package_id) != package_identity(self.owned.package_id):
            raise ProbeError("Finished recebido, mas a instalacao esperada nao foi confirmada no APT.")
        log.info("PASS: hello installed through PackageKit")
        return True

    def remove(self):
        if not self.installed_by_probe or not self.owned:
            raise ProbeError("Remocao proibida: hello nao foi instalado por esta mesma execucao. "
                             "Use 'remove' no prompt da sessao de instalacao ainda aberta.")
        if not self.confirmation("remove"):
            log.warning("Remocao nao confirmada. O pacote hello permanece instalado.")
            return False
        current = self.read()
        if not current.installed or package_identity(current.installed.package_id) != package_identity(self.owned.package_id):
            raise ProbeError("Estado de hello mudou desde a instalacao; remocao automatica proibida.")
        plan = self.plans.issue(TransactionAction.REMOVE, current.installed)
        result = self.runner(self.plans, plan, "remove")
        after = self.read()
        if result.state != TransactionState.FINISHED or after.present or after.installed:
            raise ProbeError("Remocao nao concluida: state=%s error=%r; verifique o estado manualmente."
                             % (result.state.value, result.error))
        self.installed_by_probe = False
        self.owned = None
        log.info("PASS: hello removed through PackageKit")
        return True

    def report_state(self):
        try:
            after = self.read()
            if after.present or after.installed:
                log.warning("O pacote hello permanece instalado ou parcialmente instalado. "
                            "Verifique PackageKit antes de qualquer recuperacao manual; consulte README.md.")
            else:
                log.info("Read-only verification: hello nao esta instalado.")
        except Exception as error:
            log.error("Nao foi possivel verificar o estado de hello: %s", error)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("install", "full", "remove", "resolve"))
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    session = None
    try:
        require_normal_user()
        if args.mode != "resolve" and not sys.stdin.isatty():
            raise ProbeError("Este teste exige terminal interativo; nao existe auto-confirmacao.")
        app = QCoreApplication.instance() or QCoreApplication(["mainuan-packagekit-manual-probe"])
        session = ProbeSession(QtRunner())
        if args.mode == "remove":
            session.remove()  # Deliberately refuses ownership from another process.
        session.precheck()
        if args.mode == "resolve":
            return 0
        log.info("Teste real de hello. Ctrl+C solicita cancelamento somente quando AllowCancel=true.")
        if not session.install():
            return 0
        # Keep ownership in memory, never in a forgeable cross-process marker.
        command = input("Teste C: digite 'remove' para remover nesta mesma sessao, ou 'sair': ").strip()
        if command == "remove":
            return 0 if session.remove() else 1
        log.warning("Sessao encerrada sem remocao; nao execute outro probe para remover.")
        return 1
    except (Exception, KeyboardInterrupt) as error:
        log.error("Probe interrompido: %s", error, exc_info=args.debug)
        return 1
    finally:
        if session and args.mode != "resolve":
            session.report_state()


if __name__ == "__main__":
    raise SystemExit(main())
