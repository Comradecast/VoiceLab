import dataclasses
import os
import unittest
from unittest.mock import patch

import numpy as np

from PySide6.QtWidgets import QApplication

from voice_lab.app.service import ApplicationService
from voice_lab.config.input_processing import CompressorSettings, InputProcessingSettings, LimiterSettings
from voice_lab.config.service import ConfigurationService
from voice_lab.engine.audio_engine import AudioEngine
from voice_lab.execution import (
    KNOWN_UNSUPPORTED_CAPABILITIES,
    SUPPORTED_CAPABILITIES,
    CompressorExecutionSnapshot,
    LimiterExecutionSnapshot,
    PitchFormantBackendHealth,
    TransformationExecutionRuntime,
    TransformationExecutionTarget,
    TransformationExecutor,
)
from voice_lab.effects.signalsmith_backend import SignalsmithBackendStatus
from voice_lab.mixer import Mixer
from voice_lab.planner import DEFAULT_TARGET_PROFILE, HIGHER_BRIGHTER_REFERENCE, LOWER_WEIGHTIER_REFERENCE, TransformationPlanner
from voice_lab.plugins import PluginManager
from voice_lab.tests.test_m6_3_device_failure_recovery import FakeHotkeys, FakeRouter, FakeSoundboard
from voice_lab.tests.test_m6_5_operator_settings import SettingsAudioIO
from voice_lab.tests.test_m7_2_custom_voice_management import PresetStore, SettingsStore
from voice_lab.tests.test_m9_1_target_planner import source_snapshot
from voice_lab.ui.main_window import App


def qt_application():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def make_service(**modes):
    preset_store = PresetStore()
    settings_store = SettingsStore()
    config = ConfigurationService(
        load_func=preset_store.load,
        save_func=preset_store.save,
        settings_load_func=settings_store.load,
        settings_save_func=settings_store.save,
    )
    return ApplicationService(
        config=config,
        plugins=PluginManager(),
        engine=AudioEngine(),
        mixer=Mixer(),
        audio_io=SettingsAudioIO(),
        router=FakeRouter(),
        hotkeys=FakeHotkeys(),
        soundboard=FakeSoundboard(),
        **modes,
    )


def ready_plan(target=HIGHER_BRIGHTER_REFERENCE, strength=1.0):
    return TransformationPlanner(clock=lambda: 20.0).plan(source_snapshot(), target, strength)


def available_status():
    return SignalsmithBackendStatus(True, "signalsmith", "active")


def missing_status():
    return SignalsmithBackendStatus(
        False,
        "signalsmith",
        "native_module_missing",
        "test native module missing",
    )


def activate_execution_service(target=HIGHER_BRIGHTER_REFERENCE, strength=1.0):
    service = make_service(transformation_execution_lab=True)
    service.transformation_execution_controller.source_snapshot_getter = lambda: source_snapshot()
    service.current_target_profile = target
    service.target_planner_strength = strength
    service.execution_enabled = True
    return service


class FailingSignalsmithBackend:
    def __init__(self, sample_rate, block_size, channels=1):
        self.sample_rate = sample_rate
        self.block_size = block_size

    def set_semitones(self, semitones):
        self.semitones = semitones

    def set_formant_semitones(self, semitones):
        self.formant = semitones

    def process(self, samples):
        raise RuntimeError("deterministic backend failure")

    def reset(self):
        pass

    def latency_frames(self):
        return 0

    def input_latency_frames(self):
        return 0

    def output_latency_frames(self):
        return 0

    def close(self):
        pass


class M92ExecutionContractTests(unittest.TestCase):
    def test_execution_contracts_are_immutable_scalar_visible_contracts(self):
        target = TransformationExecutionTarget(
            requested_supported_capabilities=("adaptive_pitch_center",),
            requested_unsupported_capabilities=("parametric_eq",),
            warnings=("diagnostic",),
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            target.target_pitch_semitones = 1.0
        self.assertIsInstance(target.requested_supported_capabilities, tuple)
        self.assertIsInstance(target.requested_unsupported_capabilities, tuple)
        self.assertIsInstance(target.warnings, tuple)
        snapshot = TransformationExecutionRuntime().snapshot().asdict()
        forbidden = ("numpy", "Effect", "Planner", "TargetVoiceProfile")
        self.assertFalse(any(any(word in type(value).__name__ for word in forbidden) for value in snapshot.values()))

    def test_application_snapshot_is_frozen_and_nested_contracts_are_not_dicts(self):
        service = make_service(transformation_execution_lab=True)
        snapshot = service.transformation_execution_snapshot()
        self.assertTrue(dataclasses.is_dataclass(snapshot))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            snapshot.status = "mutated"
        self.assertIsInstance(snapshot.current_compressor, CompressorExecutionSnapshot)
        self.assertIsInstance(snapshot.current_limiter, LimiterExecutionSnapshot)
        self.assertIsInstance(snapshot.backend_health, PitchFormantBackendHealth)
        self.assertNotIsInstance(snapshot.current_compressor, dict)
        self.assertNotIsInstance(snapshot.current_limiter, dict)
        self.assertNotIsInstance(snapshot.backend_health, dict)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            snapshot.current_compressor.enabled = True
        with self.assertRaises(dataclasses.FrozenInstanceError):
            snapshot.backend_health.failed = True
        old = snapshot
        service.transformation_execution_runtime.publish_backend_health(
            snapshot.backend_health.with_updates(failed=True, failure_code="test")
        )
        new = service.transformation_execution_snapshot()
        self.assertFalse(old.backend_health.failed)
        self.assertTrue(new.backend_health.failed)

    def test_executor_maps_only_supported_capabilities_and_reports_unsupported(self):
        plan = ready_plan(HIGHER_BRIGHTER_REFERENCE, 1.0)
        target, status = TransformationExecutor().map_plan(
            plan,
            enabled=True,
            baseline_settings=InputProcessingSettings(),
        )
        self.assertEqual(status, "active_partial")
        self.assertIn("adaptive_pitch_center", target.requested_supported_capabilities)
        self.assertIn("formant_shift", target.requested_supported_capabilities)
        self.assertEqual(target.target_pitch_semitones, plan.pitch.applied_pitch_shift_st)
        self.assertEqual(target.target_formant_semitones, plan.formant.applied_formant_shift_st)
        self.assertTrue(set(target.requested_unsupported_capabilities).issubset(set(KNOWN_UNSUPPORTED_CAPABILITIES)))
        self.assertNotIn("parametric_eq", target.requested_supported_capabilities)

    def test_unknown_future_capability_is_reported_not_executed(self):
        plan = dataclasses.replace(
            ready_plan(HIGHER_BRIGHTER_REFERENCE, 1.0),
            required_capabilities=("adaptive_pitch_center", "formant_shift", "future_magic"),
        )
        target, status = TransformationExecutor().map_plan(plan, enabled=True, baseline_settings=InputProcessingSettings())
        self.assertEqual(status, "active_partial")
        self.assertEqual(target.requested_supported_capabilities, ("adaptive_pitch_center", "formant_shift"))
        self.assertEqual(target.requested_unsupported_capabilities, ("future_magic",))

    def test_neutrality_disabled_and_zero_strength_preserve_baseline_dynamics(self):
        baseline = InputProcessingSettings(
            compressor=CompressorSettings(enabled=True, threshold_dbfs=-24.0, ratio=2.0),
            limiter=LimiterSettings(enabled=True, ceiling_dbfs=-3.0),
        )
        executor = TransformationExecutor()
        for target_profile in (DEFAULT_TARGET_PROFILE, HIGHER_BRIGHTER_REFERENCE, LOWER_WEIGHTIER_REFERENCE):
            plan = ready_plan(target_profile, 0.0)
            disabled, disabled_status = executor.map_plan(plan, enabled=False, baseline_settings=baseline)
            zero, zero_status = executor.map_plan(plan, enabled=True, baseline_settings=baseline)
            self.assertEqual(disabled_status, "disabled")
            self.assertEqual(zero_status, "ready_neutral")
            self.assertEqual(disabled.target_pitch_semitones, 0.0)
            self.assertEqual(zero.target_formant_semitones, 0.0)
            self.assertFalse(disabled.compressor_override_active)
            self.assertFalse(zero.limiter_override_active)
            self.assertEqual(disabled.compressor_target, baseline.compressor)
            self.assertEqual(zero.limiter_target, baseline.limiter)

    def test_lower_weightier_dynamics_are_session_only_overlays(self):
        baseline = InputProcessingSettings(
            compressor=CompressorSettings(enabled=True, threshold_dbfs=-30.0, ratio=2.0),
            limiter=LimiterSettings(enabled=True, ceiling_dbfs=-6.0),
        )
        plan = ready_plan(LOWER_WEIGHTIER_REFERENCE, 1.0)
        target, status = TransformationExecutor().map_plan(plan, enabled=True, baseline_settings=baseline)
        self.assertEqual(status, "active_partial")
        self.assertTrue(target.compressor_override_active)
        self.assertTrue(target.limiter_override_active)
        self.assertEqual(baseline.compressor.threshold_dbfs, -30.0)
        disabled, _ = TransformationExecutor().map_plan(plan, enabled=False, baseline_settings=baseline)
        self.assertFalse(disabled.compressor_override_active)
        self.assertEqual(disabled.compressor_target, baseline.compressor)


class M92RuntimeAndModeTests(unittest.TestCase):
    def test_runtime_smoothing_is_bounded_and_returns_to_neutral(self):
        runtime = TransformationExecutionRuntime()
        target = TransformationExecutionTarget(
            execution_generation=1,
            user_enabled=True,
            target_pitch_semitones=4.0,
            target_formant_semitones=1.0,
        )
        runtime.publish_target(target, "active")
        first = runtime.formant_parameters_for_block(1024, 48000)
        second = runtime.formant_parameters_for_block(1024, 48000)
        self.assertGreater(first.pitch_semitones, 0.0)
        self.assertGreater(second.pitch_semitones, first.pitch_semitones)
        self.assertLessEqual(second.pitch_semitones, 4.0)
        runtime.reset()
        neutral = runtime.formant_parameters_for_block(1024, 48000)
        self.assertLess(abs(neutral.pitch_semitones), abs(second.pitch_semitones))

    def test_mode_isolation_and_execution_chain(self):
        normal = make_service()
        formant = make_service(formant_lab=True)
        analysis = make_service(voice_analysis_lab=True)
        planner = make_service(target_planner_lab=True)
        execution = make_service(transformation_execution_lab=True)
        self.assertIsNone(normal.execution_lab_state())
        self.assertIsNone(formant.execution_lab_state())
        self.assertIsNone(analysis.execution_lab_state())
        self.assertIsNone(planner.execution_lab_state())
        self.assertIsNotNone(execution.execution_lab_state())
        self.assertEqual(normal.engine.effect_chain.effect_names()[3], "Pitch Shift")
        self.assertEqual(formant.engine.effect_chain.effect_names()[3], "Experimental Pitch/Formant")
        self.assertEqual(execution.engine.effect_chain.effect_names()[3], "Experimental Pitch/Formant")
        self.assertFalse(execution.execution_enabled)
        self.assertEqual(execution._processing_state, "stopped")

    def test_service_commands_rejected_outside_execution_mode(self):
        normal = make_service()
        self.assertFalse(normal.set_plan_execution_enabled(True).success)
        self.assertFalse(normal.return_transformation_to_neutral().success)

    def test_execution_ui_is_guarded_to_execution_mode(self):
        app = qt_application()
        normal = make_service()
        execution = make_service(transformation_execution_lab=True)
        normal_window = App(normal)
        execution_window = App(execution)
        try:
            self.assertFalse(normal_window.execution_lab_enabled)
            self.assertFalse(hasattr(normal_window, "execution_enable"))
            self.assertTrue(execution_window.execution_lab_enabled)
            self.assertTrue(hasattr(execution_window, "execution_enable"))
        finally:
            normal_window.close()
            execution_window.close()
            app.processEvents()

    def test_controller_probe_is_bounded_latest_state_only(self):
        service = make_service(transformation_execution_lab=True)
        service.source_analysis_snapshot = lambda: source_snapshot()
        for index in range(1000):
            service.current_target_profile = HIGHER_BRIGHTER_REFERENCE if index % 2 else LOWER_WEIGHTIER_REFERENCE
            service.target_planner_strength = (index % 101) / 100.0
            service.execution_enabled = index % 3 != 0
            service._refresh_execution_target()
        counts = service.transformation_execution_controller.retained_counts()
        self.assertLessEqual(counts["plans"], 1)
        self.assertLessEqual(counts["targets"], 1)
        self.assertEqual(service.transformation_execution_controller.recalculation_count, 1000)
        self.assertEqual(service.transformation_execution_controller.retained_counts(), {"plans": 1, "targets": 1})

    def test_backend_unavailable_neutralizes_pitch_formant_without_false_support(self):
        with patch("voice_lab.effects.formant_lab.signalsmith_status", missing_status):
            service = activate_execution_service(HIGHER_BRIGHTER_REFERENCE, 1.0)
            snapshot = service.transformation_execution_snapshot()
            self.assertEqual(snapshot.status, "backend_unavailable")
            self.assertEqual(snapshot.backend_health.backend_status, "native_module_missing")
            self.assertFalse(snapshot.backend_health.pitch_available)
            self.assertFalse(snapshot.backend_health.formant_available)
            self.assertEqual(snapshot.target_pitch_semitones, 0.0)
            self.assertEqual(snapshot.target_formant_semitones, 0.0)
            self.assertNotIn("adaptive_pitch_center", snapshot.actively_executing_capabilities)
            self.assertNotIn("formant_shift", snapshot.actively_executing_capabilities)
            self.assertEqual(
                snapshot.backend_unavailable_capabilities,
                ("adaptive_pitch_center", "formant_shift"),
            )
            audio = np.linspace(-0.1, 0.1, 1024, dtype=np.float32)
            output = service.engine.process_voice(audio.copy(), 1024)
            self.assertTrue(np.all(np.isfinite(output)))
            self.assertEqual(
                service.engine.effect_chain.effect_names().count("Experimental Pitch/Formant"),
                1,
            )

    def test_runtime_backend_failure_is_reported_and_pitch_formant_stop_claiming_active(self):
        with (
            patch("voice_lab.effects.formant_lab.signalsmith_status", available_status),
            patch("voice_lab.effects.pitch_shift.SignalsmithPitchBackend", FailingSignalsmithBackend),
        ):
            service = activate_execution_service(HIGHER_BRIGHTER_REFERENCE, 1.0)
            before = service.transformation_execution_snapshot()
            self.assertIn("adaptive_pitch_center", before.actively_executing_capabilities)
            audio = np.linspace(-0.1, 0.1, 1024, dtype=np.float32)
            output = service.engine.process_voice(audio.copy(), 1024)
            self.assertTrue(np.all(np.isfinite(output)))
            chain_status = service.engine.effect_chain.status()
            self.assertIn("Experimental Pitch/Formant", chain_status.runtime_bypassed_effects)
            after = service.transformation_execution_snapshot()
            self.assertEqual(after.status, "runtime_backend_failure")
            self.assertTrue(after.backend_health.failed)
            self.assertTrue(after.backend_health.runtime_bypassed)
            self.assertEqual(after.backend_health.failure_code, "pitch_formant_runtime_bypassed")
            self.assertEqual(after.target_pitch_semitones, 0.0)
            self.assertEqual(after.target_formant_semitones, 0.0)
            self.assertNotIn("adaptive_pitch_center", after.actively_executing_capabilities)
            self.assertNotIn("formant_shift", after.actively_executing_capabilities)
            self.assertIn("runtime-bypassed", after.last_failure)

    def test_dynamics_continue_when_pitch_formant_backend_fails(self):
        with patch("voice_lab.effects.formant_lab.signalsmith_status", missing_status):
            service = activate_execution_service(LOWER_WEIGHTIER_REFERENCE, 1.0)
            snapshot = service.transformation_execution_snapshot()
            self.assertEqual(snapshot.status, "backend_degraded")
            self.assertEqual(snapshot.target_pitch_semitones, 0.0)
            self.assertEqual(snapshot.target_formant_semitones, 0.0)
            self.assertTrue(snapshot.compressor_override_active)
            self.assertTrue(snapshot.limiter_override_active)
            self.assertEqual(
                snapshot.actively_executing_capabilities,
                ("compressor", "limiter"),
            )

    def test_global_bypass_is_not_backend_failure(self):
        service = activate_execution_service(HIGHER_BRIGHTER_REFERENCE, 1.0)
        result = service.set_effects_bypassed(True)
        self.assertTrue(result.success)
        snapshot = service.transformation_execution_snapshot()
        self.assertEqual(snapshot.status, "bypassed")
        self.assertTrue(snapshot.bypassed)
        self.assertFalse(snapshot.backend_health.failed)
        self.assertEqual(snapshot.backend_health.failure_code, "")
        self.assertEqual(snapshot.actively_executing_capabilities, ())

    def test_stop_start_recovery_clears_runtime_bypass_without_worker_growth(self):
        with (
            patch("voice_lab.effects.formant_lab.signalsmith_status", available_status),
            patch("voice_lab.effects.pitch_shift.SignalsmithPitchBackend", FailingSignalsmithBackend),
        ):
            service = activate_execution_service(HIGHER_BRIGHTER_REFERENCE, 1.0)
            audio = np.linspace(-0.1, 0.1, 1024, dtype=np.float32)
            service.engine.process_voice(audio.copy(), 1024)
            self.assertIn("Experimental Pitch/Formant", service.engine.effect_chain.status().runtime_bypassed_effects)
            service.stop_audio()
            self.assertEqual(service.engine.effect_chain.status().runtime_bypassed_effects, ())
            self.assertEqual(service.transformation_execution_controller.retained_counts()["targets"], 0)

    def test_capability_reconciliation_backend_support_combinations(self):
        plan = ready_plan(HIGHER_BRIGHTER_REFERENCE, 1.0)
        executor = TransformationExecutor()
        pitch_only = PitchFormantBackendHealth(
            backend_name="test-fallback",
            backend_status="fallback_active",
            backend_available=True,
            pitch_available=True,
            formant_available=False,
            fallback_active=True,
            fallback_capabilities=("adaptive_pitch_center",),
        )
        target, status = executor.map_plan(
            plan,
            enabled=True,
            baseline_settings=InputProcessingSettings(),
            backend_health=pitch_only,
        )
        self.assertEqual(status, "backend_degraded")
        self.assertIn("adaptive_pitch_center", target.actively_executing_capabilities)
        self.assertNotIn("formant_shift", target.actively_executing_capabilities)
        self.assertEqual(target.target_formant_semitones, 0.0)
        self.assertEqual(target.backend_unavailable_capabilities, ("formant_shift",))
        neither = dataclasses.replace(pitch_only, pitch_available=False)
        target, status = executor.map_plan(
            plan,
            enabled=True,
            baseline_settings=InputProcessingSettings(),
            backend_health=neither,
        )
        self.assertEqual(status, "backend_unavailable")
        self.assertEqual(target.actively_executing_capabilities, ())
        self.assertEqual(target.backend_unavailable_capabilities, ("adaptive_pitch_center", "formant_shift"))


if __name__ == "__main__":
    unittest.main()
