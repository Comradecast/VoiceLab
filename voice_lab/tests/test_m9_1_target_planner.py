import dataclasses
import math
import os
import unittest
from pathlib import Path

import numpy as np
from PySide6.QtWidgets import QApplication

from voice_lab.app.service import ApplicationService
from voice_lab.config.service import ConfigurationService
from voice_lab.engine.audio_engine import AudioEngine
from voice_lab.mixer import Mixer
from voice_lab.planner import (
    DEFAULT_TARGET_PROFILE,
    HIGHER_BRIGHTER_REFERENCE,
    LARGE_CAVERNOUS_REFERENCE,
    LOWER_WEIGHTIER_REFERENCE,
    TARGET_REFERENCE_ORDER,
    TargetVoiceProfile,
    TransformationPlan,
    TransformationPlanner,
    replace_target,
    target_voice_profile,
)
from voice_lab.plugins import PluginManager
from voice_lab.ui.main_window import App
from voice_lab.tests.test_m6_3_device_failure_recovery import FakeHotkeys, FakeRouter, FakeSoundboard
from voice_lab.tests.test_m6_5_operator_settings import SettingsAudioIO
from voice_lab.tests.test_m7_2_custom_voice_management import PresetStore, SettingsStore


SAMPLE_RATE = 48000


def qt_application():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def make_service(target_planner_lab=False, voice_analysis_lab=False, formant_lab=False):
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
        target_planner_lab=target_planner_lab,
        voice_analysis_lab=voice_analysis_lab,
        formant_lab=formant_lab,
    )


def source_snapshot(**profile_changes):
    profile = {
        "ready": True,
        "reliability": "ready",
        "voiced_frame_count": 120,
        "voiced_duration_seconds": 8.0,
        "voiced_frame_ratio": 0.9,
        "median_f0_hz": 110.0,
        "lower_f0_hz": 90.0,
        "upper_f0_hz": 145.0,
        "pitch_span_hz": 55.0,
        "pitch_span_semitones": 8.0,
        "median_spectral_tilt_db": -8.0,
        "chest_energy_ratio": 0.20,
        "low_mid_energy_ratio": 0.34,
        "presence_energy_ratio": 0.20,
        "brightness_energy_ratio": 0.10,
        "sibilance_energy_ratio": 0.08,
        "f1_hz": 500.0,
        "f2_hz": 1500.0,
        "f3_hz": 2500.0,
        "resonance_confidence": 0.55,
    }
    profile.update(profile_changes)
    return {
        "current": {"captured_at": 10.0, "reliability": profile.get("reliability")},
        "profile": profile,
        "status": {"active": True, "latest_snapshot_age_seconds": 0.1, "last_failure": ""},
    }


def sine(frequency, seconds=0.02, amplitude=0.25):
    t = np.arange(int(SAMPLE_RATE * seconds), dtype=np.float32) / SAMPLE_RATE
    return (amplitude * np.sin(2.0 * np.pi * frequency * t)).astype(np.float32)


class M91PlannerContractTests(unittest.TestCase):
    def test_profiles_and_plans_are_immutable_scalar_contracts(self):
        plan = TransformationPlanner(clock=lambda: 20.0).plan(source_snapshot(), HIGHER_BRIGHTER_REFERENCE, 0.5)

        self.assertIsInstance(HIGHER_BRIGHTER_REFERENCE, TargetVoiceProfile)
        self.assertIsInstance(plan, TransformationPlan)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            plan.character_strength = 1.0
        with self.assertRaises(dataclasses.FrozenInstanceError):
            HIGHER_BRIGHTER_REFERENCE.target_median_f0_hz = 120.0
        self.assertFalse(any(isinstance(value, (list, dict, set)) for value in dataclasses.astuple(plan)))
        self.assertEqual(plan.plan_version, "m9.1")
        self.assertEqual(plan.target_version, "target_voice_profile.v1")

    def test_target_profile_validation_rejects_bad_identity_nonfinite_and_ranges(self):
        invalid = (
            {"target_id": "", "display_name": "Bad", "description": ""},
            {"target_id": "bad", "display_name": "", "description": ""},
            {"target_id": "bad", "display_name": "Bad", "description": "", "target_median_f0_hz": 40.0},
            {"target_id": "bad", "display_name": "Bad", "description": "", "target_median_f0_hz": float("inf")},
            {"target_id": "bad", "display_name": "Bad", "description": "", "target_median_f0_hz": float("-inf")},
            {"target_id": "bad", "display_name": "Bad", "description": "", "target_median_f0_hz": "110"},
            {"target_id": "bad", "display_name": "Bad", "description": "", "max_abs_formant_shift_st": 2.1},
            {"target_id": "bad", "display_name": "Bad", "description": "", "breathiness": 1.1},
        )
        for kwargs in invalid:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises((TypeError, ValueError)):
                    target_voice_profile(**kwargs)

    def test_strength_zero_half_and_full_are_monotonic_and_do_not_mutate_inputs(self):
        target = HIGHER_BRIGHTER_REFERENCE
        source = source_snapshot()
        before_target = target.asdict()
        before_source = dict(source["profile"])
        plans = [TransformationPlanner().plan(source, target, strength) for strength in (0.0, 0.5, 1.0)]

        self.assertEqual(plans[0].pitch.applied_pitch_shift_st, 0.0)
        self.assertGreater(plans[1].pitch.applied_pitch_shift_st, plans[0].pitch.applied_pitch_shift_st)
        self.assertGreater(plans[2].pitch.applied_pitch_shift_st, plans[1].pitch.applied_pitch_shift_st)
        self.assertGreater(plans[2].formant.applied_formant_shift_st, plans[1].formant.applied_formant_shift_st)
        self.assertEqual(target.asdict(), before_target)
        self.assertEqual(source["profile"], before_source)

    def test_invalid_strength_returns_failure_plan(self):
        plan = TransformationPlanner().plan(source_snapshot(), DEFAULT_TARGET_PROFILE, float("nan"))

        self.assertFalse(plan.ready)
        self.assertEqual(plan.status, "invalid_target")
        self.assertIn("strength must be a finite number", plan.unavailable_reason)


class M91PlannerMathTests(unittest.TestCase):
    def test_zero_strength_is_fully_neutral_for_all_diagnostic_targets(self):
        for target in TARGET_REFERENCE_ORDER:
            with self.subTest(target=target.target_id):
                plan = TransformationPlanner().plan(source_snapshot(), target, 0.0)
                spectral = plan.spectral

                self.assertEqual(plan.pitch.applied_pitch_shift_st, 0.0)
                self.assertEqual(plan.pitch.applied_pitch_range_scale, 1.0)
                self.assertEqual(plan.formant.applied_formant_shift_st, 0.0)
                self.assertEqual(spectral.chest_db.applied_db, 0.0)
                self.assertEqual(spectral.low_mid_db.applied_db, 0.0)
                self.assertEqual(spectral.presence_db.applied_db, 0.0)
                self.assertEqual(spectral.brightness_db.applied_db, 0.0)
                self.assertEqual(spectral.sibilance_db.applied_db, 0.0)
                self.assertEqual(spectral.spectral_tilt_db.applied_db, 0.0)
                self.assertEqual(spectral.de_essing_amount, 0.0)
                self.assertEqual(plan.texture.breathiness, 0.0)
                self.assertEqual(plan.texture.harmonic_weight, 0.0)
                self.assertFalse(plan.texture.breathiness_required)
                self.assertFalse(plan.texture.harmonic_enhancement_required)
                self.assertFalse(plan.dynamics.compressor.compressor_enabled)
                self.assertEqual(plan.dynamics.compressor.compressor_ratio, 1.0)
                self.assertEqual(plan.dynamics.compressor.compressor_makeup_gain_db, 0.0)
                self.assertFalse(plan.dynamics.limiter.limiter_enabled)
                self.assertEqual(plan.required_capabilities, ())
                self.assertFalse(any("required" in warning for warning in plan.warnings))

    def test_high_sibilance_and_target_expectation_are_neutral_at_zero_strength(self):
        target = target_voice_profile(
            target_id="diagnostic-expectation",
            display_name="Diagnostic Expectation",
            description="Diagnostic test target.",
            expect_de_essing=True,
            requires_pitch_range=True,
            requires_eq=True,
            requires_breathiness=True,
            requires_harmonic_enhancement=True,
            breathiness=0.4,
            harmonic_weight=0.4,
        )
        plan = TransformationPlanner().plan(source_snapshot(sibilance_energy_ratio=0.5), target, 0.0)

        self.assertEqual(plan.spectral.de_essing_amount, 0.0)
        self.assertEqual(plan.required_capabilities, ())
        self.assertFalse(plan.texture.breathiness_required)
        self.assertFalse(plan.texture.harmonic_enhancement_required)

    def test_active_strength_capabilities_are_ordered_unique_and_monotonic(self):
        source = source_snapshot()
        before_source = {key: dict(value) if isinstance(value, dict) else value for key, value in source.items()}
        before_target = HIGHER_BRIGHTER_REFERENCE.asdict()
        plans = [TransformationPlanner().plan(source, HIGHER_BRIGHTER_REFERENCE, strength) for strength in (0.0, 0.5, 1.0)]

        self.assertEqual(plans[0].required_capabilities, ())
        self.assertIsInstance(plans[1].required_capabilities, tuple)
        self.assertEqual(len(plans[1].required_capabilities), len(set(plans[1].required_capabilities)))
        self.assertEqual(
            plans[1].required_capabilities,
            (
                "adaptive_pitch_center",
                "pitch_range_mapping",
                "formant_shift",
                "parametric_eq",
                "spectral_tilt_shaping",
                "breathiness",
                "harmonic_enhancement",
                "de_esser",
            ),
        )
        self.assertEqual(plans[1].required_capabilities, plans[2].required_capabilities)
        self.assertLess(plans[0].pitch.applied_pitch_shift_st, plans[1].pitch.applied_pitch_shift_st)
        self.assertLess(plans[1].pitch.applied_pitch_shift_st, plans[2].pitch.applied_pitch_shift_st)
        self.assertLess(plans[0].formant.applied_formant_shift_st, plans[1].formant.applied_formant_shift_st)
        self.assertLess(plans[1].formant.applied_formant_shift_st, plans[2].formant.applied_formant_shift_st)
        self.assertEqual(source, before_source)
        self.assertEqual(HIGHER_BRIGHTER_REFERENCE.asdict(), before_target)

    def test_de_essing_is_bounded_and_monotonic_for_source_and_target_expectation(self):
        target = HIGHER_BRIGHTER_REFERENCE
        plans = [
            TransformationPlanner().plan(source_snapshot(sibilance_energy_ratio=0.5), target, strength)
            for strength in (0.0, 0.5, 1.0)
        ]

        self.assertEqual(plans[0].spectral.de_essing_amount, 0.0)
        self.assertGreaterEqual(plans[1].spectral.de_essing_amount, 0.0)
        self.assertGreaterEqual(plans[2].spectral.de_essing_amount, plans[1].spectral.de_essing_amount)
        self.assertLessEqual(plans[2].spectral.de_essing_amount, 1.0)
        self.assertNotIn("de_esser", plans[0].required_capabilities)
        self.assertIn("de_esser", plans[1].required_capabilities)

    def test_pitch_center_formula_and_range_scale_for_practical_f0s(self):
        planner = TransformationPlanner(clock=lambda: 1.0)
        for f0 in (85.0, 100.0, 120.0, 180.0, 220.0):
            for target in (HIGHER_BRIGHTER_REFERENCE, LOWER_WEIGHTIER_REFERENCE):
                with self.subTest(f0=f0, target=target.target_id):
                    plan = planner.plan(source_snapshot(median_f0_hz=f0, pitch_span_semitones=8.0), target, 0.5)
                    if target is LOWER_WEIGHTIER_REFERENCE:
                        expected_shift = target.pitch_strategy.relative_shift_st * 0.5
                    else:
                        expected_shift = 12.0 * math.log2(target.target_median_f0_hz / f0) * 0.5
                    expected_shift = max(-target.max_pitch_shift_st, min(target.max_pitch_shift_st, expected_shift))
                    expected_scale = 1.0 + (((target.target_pitch_span_st / 8.0) - 1.0) * 0.5)
                    self.assertAlmostEqual(plan.pitch.applied_pitch_shift_st, expected_shift, places=6)
                    self.assertAlmostEqual(plan.pitch.applied_pitch_range_scale, expected_scale, places=6)

    def test_missing_pitch_and_near_zero_span_degrade_only_related_pitch_controls(self):
        no_f0 = TransformationPlanner().plan(source_snapshot(median_f0_hz=None), HIGHER_BRIGHTER_REFERENCE, 1.0)
        no_span = TransformationPlanner().plan(
            source_snapshot(pitch_span_semitones=0.1), HIGHER_BRIGHTER_REFERENCE, 1.0
        )

        self.assertEqual(no_f0.status, "degraded")
        self.assertEqual(no_f0.pitch.unavailable_reason, "missing_source_median_f0")
        self.assertEqual(no_span.pitch.applied_pitch_range_scale, 1.0)
        self.assertEqual(no_span.status, "ready")

    def test_formant_planning_uses_target_intent_not_resonance_estimates(self):
        baseline = TransformationPlanner().plan(source_snapshot(f1_hz=400.0, f2_hz=1200.0), HIGHER_BRIGHTER_REFERENCE, 1.0)
        changed = TransformationPlanner().plan(source_snapshot(f1_hz=800.0, f2_hz=2600.0), HIGHER_BRIGHTER_REFERENCE, 1.0)

        self.assertAlmostEqual(baseline.formant.applied_formant_shift_st, 1.2)
        self.assertEqual(baseline.formant.applied_formant_shift_st, changed.formant.applied_formant_shift_st)
        self.assertIn("weak context", baseline.formant.basis)

    def test_spectral_ratio_tilt_de_ess_texture_and_dynamics_are_deterministic(self):
        plan = TransformationPlanner().plan(source_snapshot(brightness_energy_ratio=0.09), HIGHER_BRIGHTER_REFERENCE, 1.0)

        self.assertAlmostEqual(plan.spectral.brightness_db.requested_db, 10.0 * math.log10(0.18 / 0.09))
        self.assertAlmostEqual(plan.spectral.spectral_tilt_db.applied_db, 4.0)
        self.assertGreater(plan.spectral.de_essing_amount, 0.0)
        self.assertAlmostEqual(plan.texture.breathiness, HIGHER_BRIGHTER_REFERENCE.breathiness)
        self.assertTrue(plan.texture.harmonic_enhancement_required)
        lower = TransformationPlanner().plan(source_snapshot(), LOWER_WEIGHTIER_REFERENCE, 0.5)
        self.assertTrue(lower.dynamics.compressor.compressor_enabled)
        self.assertAlmostEqual(lower.dynamics.compressor.compressor_ratio, 2.0)
        self.assertAlmostEqual(lower.dynamics.compressor.compressor_makeup_gain_db, 0.5)
        self.assertTrue(lower.dynamics.limiter.limiter_enabled)
        self.assertIn("live M8.0 settings are not mutated", lower.dynamics.basis)

    def test_missing_or_zero_spectral_source_degrades_only_that_control(self):
        plan = TransformationPlanner().plan(source_snapshot(brightness_energy_ratio=0.0), HIGHER_BRIGHTER_REFERENCE, 1.0)

        self.assertEqual(plan.status, "degraded")
        self.assertIsNone(plan.spectral.brightness_db.applied_db)
        self.assertEqual(plan.spectral.brightness_db.unavailable_reason, "missing_or_zero_source_ratio")
        self.assertIsNotNone(plan.spectral.chest_db.applied_db)


class M91PlannerStateAndServiceTests(unittest.TestCase):
    def test_plan_states_waiting_collecting_stale_ready_and_failure(self):
        planner = TransformationPlanner()
        waiting = planner.plan({"profile": {}, "status": {"active": False}, "current": {}}, DEFAULT_TARGET_PROFILE, 1.0)
        collecting = planner.plan(source_snapshot(ready=False, reliability="collecting"), DEFAULT_TARGET_PROFILE, 1.0)
        stale = planner.plan(
            {
                **source_snapshot(),
                "current": {"captured_at": 1.0, "reliability": "stale"},
                "status": {"active": True, "latest_snapshot_age_seconds": 99.0, "last_failure": ""},
            },
            DEFAULT_TARGET_PROFILE,
            1.0,
        )
        failure = planner.plan(
            {**source_snapshot(), "status": {"active": True, "last_failure": "boom"}},
            DEFAULT_TARGET_PROFILE,
            1.0,
        )
        ready = planner.plan(source_snapshot(), DEFAULT_TARGET_PROFILE, 1.0)

        self.assertEqual(waiting.status, "waiting_for_source")
        self.assertEqual(collecting.status, "collecting_source")
        self.assertEqual(stale.status, "stale_source")
        self.assertEqual(failure.status, "planner_failure")
        self.assertEqual(ready.status, "ready")

    def test_service_gate_session_only_reset_and_references(self):
        normal = make_service()
        planner = make_service(target_planner_lab=True)
        original_preferences = planner.operator_preferences()

        self.assertIsNone(normal.target_planner_state())
        self.assertIsNotNone(planner.source_analysis_snapshot())
        self.assertIsNotNone(planner.target_planner_state())
        self.assertEqual(planner._processing_state, "stopped")
        self.assertTrue(planner.load_target_reference("higher_brighter").success)
        self.assertEqual(planner.current_target_profile.target_id, "diagnostic-higher-brighter")
        self.assertTrue(planner.set_target_planner_strength(25).success)
        self.assertEqual(planner.target_planner_strength, 0.25)
        self.assertFalse(planner.update_target_profile(target_median_f0_hz=999).success)
        self.assertTrue(planner.reset_target_planner().success)
        self.assertEqual(planner.current_target_profile.target_id, "diagnostic-neutral")
        self.assertEqual(planner.target_planner_strength, 1.0)
        self.assertEqual(planner.operator_preferences(), original_preferences)

    def test_mode_isolation_chains_and_audio_transparency(self):
        normal = make_service()
        target_lab = make_service(target_planner_lab=True)
        formant = make_service(formant_lab=True)
        expected_normal = ["High-Pass", "Noise Gate", "Compressor", "Pitch Shift", "Robot", "Lowpass", "Gain", "Limiter"]
        expected_formant = [
            "High-Pass",
            "Noise Gate",
            "Compressor",
            "Experimental Pitch/Formant",
            "Robot",
            "Lowpass",
            "Gain",
            "Limiter",
        ]

        self.assertEqual(normal.engine.effect_chain.effect_names(), expected_normal)
        self.assertEqual(target_lab.engine.effect_chain.effect_names(), expected_normal)
        self.assertEqual(formant.engine.effect_chain.effect_names(), expected_formant)
        samples = sine(220.0)
        np.testing.assert_allclose(
            normal.engine.process_voice(samples, len(samples)),
            target_lab.engine.process_voice(samples, len(samples)),
        )
        self.assertEqual(normal.operator_preferences(), target_lab.operator_preferences())
        self.assertEqual(normal.custom_preset_names(), target_lab.custom_preset_names())

    def test_ui_exposes_target_planner_only_in_target_lab_and_ui_imports_stay_clean(self):
        app = qt_application()
        normal = make_service()
        target_lab = make_service(target_planner_lab=True)
        normal_window = App(normal)
        target_window = App(target_lab)
        try:
            normal_titles = [normal_window.tabs.tabText(i) for i in range(normal_window.tabs.count())]
            target_titles = [target_window.tabs.tabText(i) for i in range(target_window.tabs.count())]
            self.assertNotIn("Target Planner", normal_titles)
            self.assertIn("Source Analysis", target_titles)
            self.assertIn("Target Planner", target_titles)
            self.assertFalse(hasattr(normal_window, "target_planner_controls"))
            self.assertTrue(hasattr(target_window, "target_planner_controls"))
        finally:
            normal_window.close()
            target_window.close()
            app.processEvents()

        ui_source = Path("voice_lab/ui/main_window.py").read_text()
        self.assertNotIn("voice_lab.planner", ui_source)
        self.assertNotIn("numpy", ui_source)
        self.assertNotIn("scipy", ui_source)

    def test_callback_source_boundary_has_no_planner_work_or_persistence(self):
        router_source = Path("voice_lab/io/router.py").read_text()
        service_source = Path("voice_lab/app/service.py").read_text()
        settings_source = Path("voice_lab/config/settings.py").read_text()
        presets_source = Path("voice_lab/config/presets.py").read_text()

        self.assertNotIn("target_planner", router_source)
        self.assertNotIn("TransformationPlanner", router_source)
        self.assertIn("target_planner_lab", service_source)
        self.assertNotIn("target_planner", settings_source)
        self.assertNotIn("target_planner", presets_source)

    def test_replace_target_preserves_nested_dynamics_contract(self):
        updated = replace_target(LOWER_WEIGHTIER_REFERENCE, target_median_f0_hz=100.0)

        self.assertEqual(updated.target_median_f0_hz, 100.0)
        self.assertTrue(updated.dynamics.compressor_enabled)


if __name__ == "__main__":
    unittest.main()
