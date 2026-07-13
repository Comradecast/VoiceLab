import dataclasses
import os
import unittest

import numpy as np
from PySide6.QtWidgets import QApplication

from voice_lab.app.service import ApplicationService
from voice_lab.calibrate_lock import (
    ADAPTIVE_CONTINUOUS,
    ADAPTIVE_OFF,
    CalibrationSourceProfile,
    LockedTransformationSnapshot,
    ManualTransformationTrim,
    StableTransformationControlSnapshot,
    SuggestedTransformationSnapshot,
)
from voice_lab.config.service import ConfigurationService
from voice_lab.engine.audio_engine import AudioEngine
from voice_lab.mixer import Mixer
from voice_lab.planner import DEFAULT_TARGET_PROFILE, HIGHER_BRIGHTER_REFERENCE, LOWER_WEIGHTIER_REFERENCE
from voice_lab.plugins import PluginManager
from voice_lab.tests.test_m6_3_device_failure_recovery import FakeHotkeys, FakeRouter, FakeSoundboard
from voice_lab.tests.test_m6_5_operator_settings import SettingsAudioIO
from voice_lab.tests.test_m7_2_custom_voice_management import PresetStore, SettingsStore
from voice_lab.tests.test_m9_1_target_planner import source_snapshot
from voice_lab.ui.main_window import App


SAMPLE_RATE = 48000


def qt_application():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def make_service(**modes):
    config = ConfigurationService(
        load_func=PresetStore().load,
        save_func=PresetStore().save,
        settings_load_func=SettingsStore().load,
        settings_save_func=SettingsStore().save,
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


def ready_source(**changes):
    snapshot = source_snapshot(**changes)
    snapshot["status"] = {
        "active": True,
        "latest_snapshot_age_seconds": 0.1,
        "last_failure": "",
    }
    return snapshot


def calibrate_and_lock(service, source=None, target=HIGHER_BRIGHTER_REFERENCE, strength=100):
    service.source_analysis_snapshot = lambda: source or ready_source()
    service.current_target_profile = target
    service.set_target_planner_strength(strength)
    assert service.capture_calibration().success
    assert service.lock_suggested_transformation().success
    return service.stable_control_snapshot()


def process_blocks(service, samples, block=1024):
    chunks = []
    for index in range(0, len(samples), block):
        chunk = samples[index : index + block]
        chunks.append(service.engine.process_voice(chunk.copy(), len(chunk)))
    return np.concatenate(chunks)


class M93ContractAndCalibrationTests(unittest.TestCase):
    def test_launch_defaults_and_immutable_contracts(self):
        service = make_service(calibrate_lock_lab=True)
        state = service.stable_control_snapshot()
        self.assertIsInstance(state, StableTransformationControlSnapshot)
        self.assertEqual(state.adaptive_mode, ADAPTIVE_OFF)
        self.assertIsNone(state.calibration)
        self.assertIsNone(state.suggestion)
        self.assertIsNone(state.locked)
        self.assertIsInstance(state.trim, ManualTransformationTrim)
        self.assertEqual(state.trim.applied_pitch_trim_st, 0.0)
        self.assertFalse(service.execution_enabled)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            state.adaptive_mode = ADAPTIVE_CONTINUOUS
        with self.assertRaises(dataclasses.FrozenInstanceError):
            state.trim.applied_pitch_trim_st = 1.0

    def test_calibration_capture_rules_and_snapshot_copy(self):
        service = make_service(calibrate_lock_lab=True)
        service.source_analysis_snapshot = lambda: ready_source(median_f0_hz=120.0)
        self.assertTrue(service.capture_calibration().success)
        calibration = service.stable_control_snapshot().calibration
        self.assertIsInstance(calibration, CalibrationSourceProfile)
        self.assertEqual(calibration.median_f0_hz, 120.0)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            calibration.median_f0_hz = 200.0
        service.source_analysis_snapshot = lambda: ready_source(median_f0_hz=220.0)
        self.assertEqual(calibration.median_f0_hz, 120.0)

        cases = (
            ("inactive", {**ready_source(), "status": {"active": False, "latest_snapshot_age_seconds": 0.1, "last_failure": ""}}),
            ("collecting", ready_source(ready=False, reliability="collecting")),
            ("stale", {**ready_source(), "status": {"active": True, "latest_snapshot_age_seconds": 99.0, "last_failure": ""}}),
            ("missing_f0", ready_source(median_f0_hz=None)),
            ("failure", {**ready_source(), "status": {"active": True, "latest_snapshot_age_seconds": 0.1, "last_failure": "boom"}}),
        )
        preserved = service.stable_control_snapshot().calibration
        for _label, snapshot in cases:
            service.source_analysis_snapshot = lambda snapshot=snapshot: snapshot
            self.assertFalse(service.capture_calibration().success)
            self.assertEqual(service.stable_control_snapshot().calibration, preserved)

    def test_suggestion_uses_frozen_calibration_and_target_strength_dirty_state(self):
        service = make_service(calibrate_lock_lab=True)
        calibrate_and_lock(service, source=ready_source(median_f0_hz=110.0), strength=50)
        locked = service.stable_control_snapshot().locked
        base_pitch = locked.plan.pitch.applied_pitch_shift_st
        service.source_analysis_snapshot = lambda: ready_source(median_f0_hz=220.0)
        self.assertEqual(service.stable_control_snapshot().locked.plan.pitch.applied_pitch_shift_st, base_pitch)
        service.load_target_reference("lower_weightier")
        state = service.stable_control_snapshot()
        self.assertTrue(state.suggestion_differs_from_lock)
        self.assertTrue(state.target_changed_after_lock)
        self.assertEqual(state.locked.plan.pitch.applied_pitch_shift_st, base_pitch)
        service.set_target_planner_strength(25)
        self.assertTrue(service.stable_control_snapshot().strength_changed_after_lock)
        self.assertTrue(service.lock_suggested_transformation().success)
        self.assertFalse(service.stable_control_snapshot().newer_suggestion_available)

    def test_manual_trim_projection_and_return_to_suggested_plan(self):
        service = make_service(calibrate_lock_lab=True)
        calibrate_and_lock(service, source=ready_source(), target=DEFAULT_TARGET_PROFILE)
        base = service.stable_control_snapshot().locked.plan
        self.assertTrue(np.isfinite(base.pitch.applied_pitch_shift_st))
        self.assertTrue(np.isfinite(base.formant.applied_formant_shift_st))
        self.assertTrue(service.set_pitch_trim(2.0).success)
        self.assertTrue(service.set_formant_trim(-0.5).success)
        state = service.stable_control_snapshot()
        self.assertEqual(state.final_pitch_target_st, base.pitch.applied_pitch_shift_st + 2.0)
        self.assertEqual(state.final_formant_target_st, base.formant.applied_formant_shift_st - 0.5)
        self.assertEqual(state.locked.plan.pitch.applied_pitch_shift_st, base.pitch.applied_pitch_shift_st)
        self.assertEqual(state.locked.plan.formant.applied_formant_shift_st, base.formant.applied_formant_shift_st)
        self.assertFalse(state.locked.plan.dynamics.compressor.compressor_enabled)
        self.assertTrue(service.set_pitch_trim(99.0).success)
        self.assertEqual(service.stable_control_snapshot().applied_pitch_trim_st, 4.0)
        self.assertTrue(service.stable_control_snapshot().trim.pitch_trim_clamped)
        self.assertTrue(service.return_to_suggested_plan().success)
        restored = service.stable_control_snapshot()
        self.assertEqual(restored.final_pitch_target_st, base.pitch.applied_pitch_shift_st)
        self.assertEqual(restored.final_formant_target_st, base.formant.applied_formant_shift_st)


class M93ExecutionAndModeTests(unittest.TestCase):
    def test_locked_execution_ignores_live_source_collecting_stale_and_target_edits(self):
        service = make_service(calibrate_lock_lab=True)
        calibrate_and_lock(service, source=ready_source(median_f0_hz=110.0), target=HIGHER_BRIGHTER_REFERENCE)
        locked_pitch = service.stable_control_snapshot().locked.plan.pitch.applied_pitch_shift_st
        service.execution_enabled = True
        first = service.transformation_execution_snapshot()
        service.source_analysis_snapshot = lambda: ready_source(ready=False, reliability="collecting", median_f0_hz=300.0)
        service.load_target_reference("lower_weightier")
        service.set_target_planner_strength(10)
        second = service.transformation_execution_snapshot()
        self.assertEqual(first.target_pitch_semitones, locked_pitch)
        self.assertEqual(second.target_pitch_semitones, locked_pitch)
        self.assertEqual(second.status, "active_partial")

    def test_adaptive_mode_switching(self):
        service = make_service(calibrate_lock_lab=True)
        calibrate_and_lock(service, source=ready_source(median_f0_hz=110.0), target=HIGHER_BRIGHTER_REFERENCE)
        service.execution_enabled = True
        off_pitch = service.transformation_execution_snapshot().target_pitch_semitones
        service.source_analysis_snapshot = lambda: ready_source(median_f0_hz=220.0)
        self.assertTrue(service.set_adaptive_updating_mode(ADAPTIVE_CONTINUOUS).success)
        continuous_pitch = service.transformation_execution_snapshot().target_pitch_semitones
        self.assertNotEqual(off_pitch, continuous_pitch)
        service.source_analysis_snapshot = lambda: ready_source(ready=False, reliability="collecting")
        self.assertEqual(service.transformation_execution_snapshot().status, "collecting_source")
        self.assertTrue(service.set_adaptive_updating_mode(ADAPTIVE_OFF).success)
        self.assertEqual(service.transformation_execution_snapshot().target_pitch_semitones, off_pitch)

    def test_dynamics_are_locked_until_relock_and_disable_restores_baseline(self):
        service = make_service(calibrate_lock_lab=True)
        calibrate_and_lock(service, target=LOWER_WEIGHTIER_REFERENCE, strength=100)
        service.execution_enabled = True
        first = service.transformation_execution_snapshot()
        self.assertTrue(first.compressor_override_active)
        service.load_target_reference("higher_brighter")
        service.set_target_planner_strength(10)
        second = service.transformation_execution_snapshot()
        self.assertEqual(second.plan_compressor, first.plan_compressor)
        service.return_transformation_to_neutral()
        neutral = service.transformation_execution_snapshot()
        self.assertFalse(neutral.compressor_override_active)

    def test_mode_isolation_ui_and_chains(self):
        app = qt_application()
        normal = make_service()
        formant = make_service(formant_lab=True)
        execution = make_service(transformation_execution_lab=True)
        stable = make_service(calibrate_lock_lab=True)
        windows = []
        try:
            normal_window = App(normal)
            formant_window = App(formant)
            execution_window = App(execution)
            stable_window = App(stable)
            windows = [normal_window, formant_window, execution_window, stable_window]
            self.assertFalse(getattr(normal_window, "calibrate_lock_enabled", False))
            self.assertFalse(getattr(formant_window, "calibrate_lock_enabled", False))
            self.assertFalse(getattr(execution_window, "calibrate_lock_enabled", False))
            self.assertTrue(stable_window.calibrate_lock_enabled)
            titles = [stable_window.tabs.tabText(i) for i in range(stable_window.tabs.count())]
            self.assertIn("Source Analysis", titles)
            self.assertIn("Target Planner", titles)
            self.assertIn("Plan Execution", titles)
            self.assertIn("Calibrate & Lock", titles)
        finally:
            for window in windows:
                window.close()
            app.processEvents()
        self.assertEqual(normal.engine.effect_chain.effect_names()[3], "Pitch Shift")
        self.assertEqual(formant.engine.effect_chain.effect_names()[3], "Experimental Pitch/Formant")
        self.assertEqual(stable.engine.effect_chain.effect_names()[3], "Experimental Pitch/Formant")
        self.assertEqual(stable.engine.effect_chain.effect_names().count("Experimental Pitch/Formant"), 1)

    def test_audio_locked_stability_manual_trim_and_disabled_equivalence(self):
        execution = make_service(transformation_execution_lab=True)
        stable = make_service(calibrate_lock_lab=True)
        x = (np.sin(np.linspace(0, 6 * np.pi, 8192, endpoint=False)) * 0.2).astype(np.float32)
        np.testing.assert_allclose(process_blocks(execution, x), process_blocks(stable, x), atol=0.0)
        calibrate_and_lock(stable, source=ready_source(median_f0_hz=110.0), target=HIGHER_BRIGHTER_REFERENCE)
        stable.execution_enabled = True
        base = process_blocks(stable, x)
        stable.source_analysis_snapshot = lambda: ready_source(median_f0_hz=300.0)
        changed_live = process_blocks(stable, x)
        np.testing.assert_allclose(base, changed_live, atol=1e-6)
        stable.set_pitch_trim(-2.0)
        trimmed = process_blocks(stable, x)
        self.assertTrue(np.all(np.isfinite(trimmed)))
        self.assertEqual(trimmed.shape, x.shape)
        self.assertGreater(float(np.max(np.abs(trimmed - base))), 0.0)

    def test_bounded_operations_do_not_grow_retained_state_or_mutate_preferences(self):
        service = make_service(calibrate_lock_lab=True)
        preferences = service.operator_preferences()
        preset_names = service.custom_preset_names()
        service.source_analysis_snapshot = lambda: ready_source()
        for index in range(1000):
            if index % 5 == 0:
                service.capture_calibration()
            if index % 7 == 0:
                service.lock_suggested_transformation()
            if index % 3 == 0:
                service.set_pitch_trim((index % 9) - 4)
            if index % 4 == 0:
                service.set_formant_trim(((index % 5) - 2) * 0.25)
            if index % 11 == 0:
                service.set_adaptive_updating_mode(ADAPTIVE_CONTINUOUS if index % 22 == 0 else ADAPTIVE_OFF)
            service.execution_enabled = index % 2 == 0
            service.transformation_execution_snapshot()
        state = service.stable_control_snapshot()
        self.assertIsNotNone(state.calibration)
        self.assertIsNotNone(state.suggestion)
        self.assertIsNotNone(state.locked)
        self.assertIsInstance(state.trim, ManualTransformationTrim)
        self.assertEqual(service.operator_preferences(), preferences)
        self.assertEqual(service.custom_preset_names(), preset_names)


if __name__ == "__main__":
    unittest.main()
