from dataclasses import replace
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

from PyQt6.QtTest import QSignalSpy
from PyQt6.QtWidgets import QDialogButtonBox, QLabel

from test_driver_execution import FakeSource, FakeWorkflowFactory, await_signal
from test_qt_frontend import app
from test_transaction_planner import scenario, target
from test_preflight import context, reference
from mainuan_drivers.backend.preflight import (
    ActivationState, DkmsState, DriverPreflight, ModuleEvidence, MokState,
    SecureBootState, HeadersState, KernelState, assess_activation,
)
from mainuan_drivers.backend.test_scenarios import SCENARIOS
from mainuan_drivers.backend.transactions.execution import DriverExecutionController, DriverSnapshot, SnapshotSource
from mainuan_drivers.backend.transactions.models import (
    ExecutionResult, PackageReference, PreparedPlan, RestartRequirement, TransactionAction,
    TransactionState,
)
from mainuan_drivers.qt.main_window import DriverDetectionWorker, MainWindow, PlanDialog, execution_message


class ContextSource(FakeSource):
    def __init__(self, planner, security, evidence=()):
        super().__init__(planner)
        self.security = security
        self.evidence = evidence

    def load(self):
        snapshot = super().load()
        return replace(snapshot, context=self.security, secure_boot=self.security.secure_boot_state,
                       evidence=self.evidence)


class PreflightWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app().setQuitOnLastWindowClosed(False)

    def build(self, security, factory=None, installed=True):
        _, device, planner = scenario(installed=installed)
        plan = planner.build({device.device_id: target(device, "new-driver")})
        source = ContextSource(planner, security,
                               (ModuleEvidence(plan.installs[0].package_id, DkmsState.DKMS_REQUIRED),))
        factory = factory or FakeWorkflowFactory()
        controller = DriverExecutionController(source=source, transaction_factory=factory)
        controller.available = True
        self.addCleanup(controller.deleteLater)
        return controller, planner, plan, source, factory

    def prepare(self, controller, planner, plan):
        spy = QSignalSpy(controller.prepared)
        self.assertTrue(controller.prepare(planner, plan))
        return await_signal(spy)[0]

    def test_secure_boot_blocker_stops_switch_before_removal_and_confirm(self):
        controller, planner, plan, source, factory = self.build(context(secure_boot_state=SecureBootState.ENABLED))
        prepared = self.prepare(controller, planner, plan)
        self.assertTrue(prepared.preflight.blockers)
        self.assertFalse(controller.confirm(prepared))
        self.assertFalse(any(method in ("install", "remove") for method, action in factory.calls))

    def test_enrolled_mok_does_not_silently_bypass_signing_protection(self):
        controller, planner, plan, source, factory = self.build(context(
            secure_boot_state=SecureBootState.ENABLED, mok_state=MokState.ENROLLED))
        prepared = self.prepare(controller, planner, plan)
        self.assertTrue(prepared.preflight.blockers)
        self.assertFalse(controller.confirm(prepared))

    def test_missing_headers_blocks_even_with_secure_boot_disabled(self):
        controller, planner, plan, source, factory = self.build(context(headers_state=HeadersState.MISSING))
        prepared = self.prepare(controller, planner, plan)
        self.assertIn("headers-missing", [issue.code for issue in prepared.preflight.blockers])
        self.assertFalse(controller.confirm(prepared))

    def test_new_blocker_after_confirmation_is_shown_before_any_mutation(self):
        controller, planner, plan, source, factory = self.build(context())
        prepared = self.prepare(controller, planner, plan)
        source.security = context(secure_boot_state=SecureBootState.ENABLED)
        changed = QSignalSpy(controller.prepared)
        self.assertTrue(controller.confirm(prepared))
        updated = await_signal(changed)[0]
        self.assertTrue(updated.preflight.blockers)
        self.assertFalse(any(method in ("install", "remove") for method, action in factory.calls))

    def test_dkms_discovered_in_packagekit_effects_blocks_plain_root_plan(self):
        dependency = reference("nvidia-dkms-580", requires=None)
        factory = FakeWorkflowFactory(extra_installs=(dependency,))
        controller, planner, plan, source, factory = self.build(context(secure_boot_state=SecureBootState.ENABLED), factory)
        source.evidence = (replace(source.evidence[0], dkms_state=DkmsState.NO_DKMS),)
        prepared = self.prepare(controller, planner, plan)
        self.assertTrue(prepared.preflight.blockers)
        self.assertFalse(controller.confirm(prepared))

    def test_kernel_warning_does_not_block_permitted_dkms_install(self):
        controller, planner, plan, source, factory = self.build(context(kernel_state=KernelState.OUTDATED), installed=False)
        prepared = self.prepare(controller, planner, plan)
        self.assertFalse(prepared.preflight.blockers)
        self.assertTrue(prepared.preflight.warnings)
        done = QSignalSpy(controller.finished)
        self.assertTrue(controller.confirm(prepared))
        result = await_signal(done)[0]
        self.assertEqual(result.state, TransactionState.FINISHED)
        self.assertEqual(result.plan, plan)

    def test_visual_scenarios_never_read_host_apt_or_security(self):
        with patch("mainuan_drivers.backend.transactions.execution.SystemSecurityProbe") as security, \
                patch("mainuan_drivers.backend.transactions.packagekit.QtDBusTransport") as transport:
            security.return_value.probe.side_effect = AssertionError("Host security must not be read")
            source = SnapshotSource(test_mode=True)
            for key, label in SCENARIOS:
                with self.subTest(scenario=key):
                    source.set_scenario(key)
                    snapshot = source.load()
                    self.assertTrue(snapshot.planner.preview_only)
                    self.assertTrue(snapshot.planner.devices)
                    self.assertIsNotNone(snapshot.context)
            transport.assert_not_called()
            security.return_value.probe.assert_not_called()

    def test_real_source_refuses_visual_scenarios(self):
        with self.assertRaises(RuntimeError):
            SnapshotSource().set_scenario("broadcom")

    def test_broadcom_detection_plan_simulation_and_reboot(self):
        source = SnapshotSource(test_mode=True, scenario="broadcom")
        snapshot = source.load()
        device = snapshot.planner.devices[0]
        self.assertEqual(device.icon_key, "broadcom")
        desired = next(option for option in device.drivers if option.package_name == "broadcom-sta-dkms")
        plan = snapshot.planner.build({device.device_id: desired})
        self.assertEqual([ref.name for ref in plan.installs], ["broadcom-sta-dkms"])
        self.assertEqual(DriverPreflight(snapshot.context, snapshot.evidence).check(plan.installs, True).dkms_state,
                         DkmsState.DKMS_REQUIRED)
        controller = DriverExecutionController(test_mode=True, source=source,
                                               transaction_factory=Mock(side_effect=AssertionError("real transaction")))
        self.addCleanup(controller.deleteLater)
        prepared = self.prepare(controller, snapshot.planner, plan)
        done = QSignalSpy(controller.finished)
        self.assertTrue(controller.confirm(prepared))
        result = await_signal(done)[0]
        self.assertTrue(result.simulated)
        self.assertEqual(result.restart, RestartRequirement.SYSTEM)
        current = source.inspect(plan)
        activation = assess_activation(plan, current.context, current.installed_packages)
        self.assertEqual(activation[0].state, ActivationState.INSTALLED_REBOOT_REQUIRED)
        secure = replace(snapshot.context, secure_boot_state=SecureBootState.ENABLED)
        self.assertTrue(DriverPreflight(secure, snapshot.evidence).check(plan.installs, True).blockers)

    def test_confirmation_distinguishes_warning_from_blocker_and_disables_apply(self):
        for security, blocked in ((context(kernel_state=KernelState.OUTDATED), False),
                                  (context(secure_boot_state=SecureBootState.ENABLED), True)):
            with self.subTest(blocked=blocked):
                controller, planner, plan, source, factory = self.build(security)
                prepared = self.prepare(controller, planner, plan)
                dialog = PlanDialog(prepared, confirmation=True)
                self.addCleanup(dialog.deleteLater)
                buttons = dialog.findChild(QDialogButtonBox)
                self.assertEqual(buttons.button(QDialogButtonBox.StandardButton.Apply).isEnabled(), not blocked)
                text = "\n".join(label.text() for label in dialog.findChildren(QLabel))
                self.assertIn("System verification", text)
                self.assertIn("Blocked:" if blocked else "Warning:", text)

    def test_main_window_apply_disabled_but_preview_available_for_blocker(self):
        source = SnapshotSource(test_mode=True, scenario="headers-missing")
        snapshot = source.load()
        executor = DriverExecutionController(test_mode=True, source=source)
        window = MainWindow(test_mode=True, auto_start=False, executor=executor)
        self.addCleanup(window.deleteLater)
        window._receive_snapshot(snapshot)
        window._set_planner(snapshot.planner)
        device = snapshot.planner.devices[0]
        window._select(device, next(option for option in device.drivers if option.recommended))
        self.assertFalse(window.apply_button.isEnabled())
        self.assertTrue(window.plan_button.isEnabled())
        self.assertIn("Headers", window.preflight_label.text())

    def test_post_transaction_worker_uses_fresh_inspection(self):
        source = SnapshotSource(test_mode=True, scenario="mok-pending")
        snapshot = source.load()
        source = Mock()
        source.inspect.return_value = snapshot
        plan = Mock()
        worker = DriverDetectionWorker(source=source, inspection_plan=plan)
        received = QSignalSpy(worker.snapshotReady)
        worker.run()
        source.inspect.assert_called_once_with(plan)
        source.load.assert_not_called()
        self.assertEqual(received[0][0], snapshot)

    def test_post_inspection_does_not_accept_half_configured_package_as_installed(self):
        backend = Mock()
        backend.get_devices.return_value = ()
        backend.module_evidence.return_value = ()
        backend.get_packagekit_id.return_value = "driver-package;1.0;amd64;installed"
        security = Mock()
        security.probe.return_value = context()
        source = SnapshotSource(backend_factory=lambda: backend, security_probe=security)
        plan = SimpleNamespace(installs=(reference(),), removals=())
        apt = SimpleNamespace(Cache=Mock(), CURSTATE_INSTALLED=6)
        for state, expected in ((2, False), (6, backend.get_packagekit_id.return_value)):
            with self.subTest(state=state), patch.dict("sys.modules", {"apt_pkg": apt}):
                apt.Cache.return_value = {"driver-package": SimpleNamespace(current_state=state)}
                result = source.inspect(plan)
                self.assertEqual(dict(result.installed_packages)["driver-package"], expected)

    def test_installed_mok_pending_is_not_reported_as_driver_ready(self):
        _, device, planner = scenario(installed=False)
        plan = planner.build({device.device_id: target(device, "new-driver")})
        activation = assess_activation(plan, context(mok_state=MokState.PENDING), (("new-driver", True),))
        result = ExecutionResult(TransactionState.FINISHED, (), None, RestartRequirement.NONE,
                                 plan=plan, activations=activation)
        message = execution_message(result)
        self.assertIn("MokManager", message)
        self.assertNotIn("applied successfully", message)

    def test_pending_result_waits_for_fresh_package_inspection(self):
        source = SnapshotSource(test_mode=True)
        snapshot = source.load()
        device = snapshot.planner.devices[0]
        plan = snapshot.planner.build({device.device_id: next(option for option in device.drivers if option.recommended)})
        window = MainWindow(test_mode=True, auto_start=False)
        self.addCleanup(window.deleteLater)
        result = ExecutionResult(TransactionState.FINISHED, (), None, RestartRequirement.NONE, plan=plan)
        window._execution_finished(result)
        self.assertIsNotNone(window._pending_result)
        window._receive_snapshot(snapshot)
        self.assertIsNone(window._pending_result)
        self.assertIn("not installed", window.result_label.text())
