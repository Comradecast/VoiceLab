import dataclasses
import os
import unittest

from PySide6.QtWidgets import QApplication

from voice_lab.app.service import ApplicationService
from voice_lab.config.input_processing import CompressorSettings, InputProcessingSettings, LimiterSettings
from voice_lab.config.service import ConfigurationService
from voice_lab.engine.audio_engine import AudioEngine
from voice_lab.execution import (
    KNOWN_UNSUPPORTED_CAPABILITIES,
    SUPPORTED_CAPABILITIES,
    TransformationExecutionRuntime,
    TransformationExecutionTarget,
    TransformationExecutor,
)
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


if __name__ == "__main__":
    unittest.main()
