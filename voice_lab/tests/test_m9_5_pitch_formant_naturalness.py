import dataclasses
import math
import os
import unittest

import numpy as np
from PySide6.QtWidgets import QApplication, QPushButton

from voice_lab.calibrate_lock import manual_trim, apply_manual_trim
from voice_lab.planner import (
    DEFAULT_TARGET_PROFILE,
    HIGHER_BRIGHTER_REFERENCE,
    LARGE_CAVERNOUS_REFERENCE,
    LOWER_WEIGHTIER_REFERENCE,
    NATURAL_DEEP_REFERENCE,
    TARGET_REFERENCE_ORDER,
    FormantStrategy,
    PitchStrategy,
    TransformationPlanner,
    target_voice_profile,
)
from voice_lab.tests.test_m9_1_target_planner import source_snapshot
from voice_lab.tests.test_m9_3_calibrate_lock import (
    ADAPTIVE_CONTINUOUS,
    ADAPTIVE_OFF,
    calibrate_and_lock,
    make_service,
    process_blocks,
    ready_source,
)
from voice_lab.ui.main_window import App


def qt_application():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def voice_like_signal(samples=8192):
    t = np.arange(samples, dtype=np.float32) / 48000.0
    data = (
        0.12 * np.sin(2.0 * np.pi * 115.0 * t)
        + 0.07 * np.sin(2.0 * np.pi * 230.0 * t)
        + 0.04 * np.sin(2.0 * np.pi * 920.0 * t)
        + 0.03 * np.sin(2.0 * np.pi * 2400.0 * t)
    )
    return data.astype(np.float32)


class M95PitchFormantNaturalnessTests(unittest.TestCase):
    def test_strategy_contracts_are_frozen_scalar_and_ordered(self):
        plan = TransformationPlanner(clock=lambda: 1.0).plan(source_snapshot(), NATURAL_DEEP_REFERENCE, 1.0)
        self.assertEqual(tuple(t.target_id for t in TARGET_REFERENCE_ORDER), (
            "diagnostic-neutral",
            "diagnostic-higher-brighter",
            "diagnostic-lower-weightier",
            "diagnostic-large-cavernous",
        ))
        self.assertEqual(len({t.target_id for t in TARGET_REFERENCE_ORDER}), 4)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            NATURAL_DEEP_REFERENCE.pitch_strategy.relative_shift_st = -4.0
        with self.assertRaises(dataclasses.FrozenInstanceError):
            plan.formant.strategy = "changed"
        self.assertFalse(any(isinstance(value, (list, dict, set)) for value in dataclasses.astuple(plan)))
        old = plan
        newer = TransformationPlanner(clock=lambda: 2.0).plan(source_snapshot(), NATURAL_DEEP_REFERENCE, 0.5)
        self.assertEqual(old.formant.applied_formant_shift_st, NATURAL_DEEP_REFERENCE.formant_strategy.compensation_ratio * 3.5)
        self.assertNotEqual(old, newer)

    def test_invalid_strategy_inputs_are_rejected(self):
        with self.assertRaises(ValueError):
            target_voice_profile(
                target_id="bad-pitch",
                display_name="Bad Pitch",
                description="bad",
                pitch_strategy=PitchStrategy("bad"),
            )
        with self.assertRaises(ValueError):
            target_voice_profile(
                target_id="bad-formant",
                display_name="Bad Formant",
                description="bad",
                formant_strategy=FormantStrategy("bad"),
            )
        with self.assertRaises(ValueError):
            target_voice_profile(
                target_id="bad-ratio",
                display_name="Bad Ratio",
                description="bad",
                formant_strategy=FormantStrategy("natural_compensation", compensation_ratio=math.nan),
            )

    def test_zero_strength_is_neutral_for_all_targets(self):
        for target in TARGET_REFERENCE_ORDER + (LOWER_WEIGHTIER_REFERENCE,):
            with self.subTest(target=target.display_name):
                plan = TransformationPlanner().plan(source_snapshot(), target, 0.0)
                self.assertEqual(plan.pitch.applied_pitch_shift_st, 0.0)
                self.assertEqual(plan.formant.applied_formant_shift_st, 0.0)
                self.assertFalse(plan.formant.naturalness_guard_active)
                self.assertFalse(plan.formant.stylized_formant_combination_active)
                self.assertFalse(plan.dynamics.compressor.compressor_enabled)
                self.assertFalse(plan.dynamics.limiter.limiter_enabled)
                self.assertEqual(plan.required_capabilities, ())
                self.assertNotIn("naturalness guard", " ".join(plan.warnings))
                self.assertNotIn("stylized negative pitch plus negative formant", " ".join(plan.warnings))

    def test_neutral_target_is_fully_neutral_at_every_strength(self):
        for strength in (0.0, 0.25, 0.5, 0.75, 1.0):
            with self.subTest(strength=strength):
                plan = TransformationPlanner().plan(source_snapshot(), DEFAULT_TARGET_PROFILE, strength)
                self.assertEqual(plan.pitch.requested_pitch_shift_st, 0.0)
                self.assertEqual(plan.pitch.applied_pitch_shift_st, 0.0)
                self.assertEqual(plan.formant.requested_formant_shift_st, 0.0)
                self.assertEqual(plan.formant.applied_formant_shift_st, 0.0)
                self.assertEqual(plan.spectral.chest_db.applied_db, 0.0)
                self.assertEqual(plan.spectral.low_mid_db.applied_db, 0.0)
                self.assertEqual(plan.spectral.presence_db.applied_db, 0.0)
                self.assertEqual(plan.spectral.brightness_db.applied_db, 0.0)
                self.assertEqual(plan.spectral.sibilance_db.applied_db, 0.0)
                self.assertEqual(plan.spectral.spectral_tilt_db.applied_db, 0.0)
                self.assertEqual(plan.texture.breathiness, 0.0)
                self.assertEqual(plan.texture.harmonic_weight, 0.0)
                self.assertFalse(plan.dynamics.compressor_differs_from_neutral)
                self.assertFalse(plan.dynamics.limiter_differs_from_neutral)
                self.assertEqual(plan.required_capabilities, ())

    def test_natural_deep_direction_is_relative_monotonic_and_nonnegative_formant(self):
        previous_pitch = 0.0
        previous_formant = 0.0
        for strength in (0.25, 0.5, 0.75, 1.0):
            plan = TransformationPlanner().plan(source_snapshot(median_f0_hz=200.0), NATURAL_DEEP_REFERENCE, strength)
            self.assertLess(plan.pitch.applied_pitch_shift_st, 0.0)
            self.assertGreaterEqual(plan.formant.applied_formant_shift_st, 0.0)
            self.assertLess(plan.pitch.applied_pitch_shift_st, previous_pitch)
            self.assertGreater(plan.formant.applied_formant_shift_st, previous_formant)
            self.assertEqual(plan.pitch.strategy, "relative_shift")
            self.assertEqual(plan.formant.strategy, "natural_compensation")
            previous_pitch = plan.pitch.applied_pitch_shift_st
            previous_formant = plan.formant.applied_formant_shift_st
        full = TransformationPlanner().plan(source_snapshot(median_f0_hz=100.0), NATURAL_DEEP_REFERENCE, 1.0)
        self.assertAlmostEqual(full.pitch.applied_pitch_shift_st, -3.5)
        self.assertGreaterEqual(full.formant.applied_formant_shift_st, 1.0)
        self.assertLessEqual(full.formant.applied_formant_shift_st, 2.0)
        half = TransformationPlanner().plan(source_snapshot(median_f0_hz=150.0), NATURAL_DEEP_REFERENCE, 0.5)
        self.assertAlmostEqual(half.pitch.applied_pitch_shift_st, -1.75)
        self.assertAlmostEqual(half.formant.applied_formant_shift_st, 0.7525)
        for median in (100.0, 120.0, 150.0, 200.0):
            with self.subTest(median=median):
                series = [
                    TransformationPlanner().plan(source_snapshot(median_f0_hz=median), NATURAL_DEEP_REFERENCE, strength)
                    for strength in (0.0, 0.25, 0.5, 0.75, 1.0)
                ]
                self.assertEqual([round(plan.pitch.applied_pitch_shift_st, 6) for plan in series], [
                    -0.0,
                    -0.875,
                    -1.75,
                    -2.625,
                    -3.5,
                ])
                self.assertEqual([round(plan.formant.applied_formant_shift_st, 6) for plan in series], [
                    0.0,
                    0.37625,
                    0.7525,
                    1.12875,
                    1.505,
                ])

    def test_large_cavernous_is_stylized_negative_formant(self):
        for strength in (0.0, 0.25, 0.5, 0.75, 1.0):
            plan = TransformationPlanner().plan(source_snapshot(), LARGE_CAVERNOUS_REFERENCE, strength)
            if strength == 0.0:
                self.assertEqual(plan.required_capabilities, ())
                self.assertFalse(plan.formant.stylized_formant_combination_active)
                self.assertNotIn("stylized negative pitch plus negative formant", " ".join(plan.warnings))
            else:
                self.assertLess(plan.pitch.applied_pitch_shift_st, 0.0)
                self.assertLess(plan.formant.applied_formant_shift_st, 0.0)
                self.assertTrue(plan.formant.stylized_formant_combination_active)
                self.assertIn("stylized negative pitch plus negative formant", " ".join(plan.warnings))
        self.assertNotEqual(plan.target_id, NATURAL_DEEP_REFERENCE.target_id)

    def test_naturalness_guard_matrix_blocks_negative_natural_compensation(self):
        cases = (
            ("negative_pitch_negative_formant", -3.0, -1.0, True),
            ("zero_pitch_negative_formant", 0.0, -1.0, True),
            ("positive_pitch_negative_formant", 3.0, -1.0, True),
            ("negative_pitch_zero_formant", -3.0, 0.0, False),
            ("negative_pitch_positive_formant", -3.0, 1.0, False),
        )
        for name, pitch, formant, guarded in cases:
            with self.subTest(name=name):
                target = target_voice_profile(
                    target_id=f"guard-{name}",
                    display_name=name,
                    description="guard matrix",
                    pitch_strategy=PitchStrategy("relative_shift", pitch),
                    formant_strategy=FormantStrategy("natural_compensation", fixed_shift_st=formant),
                    nominal_formant_shift_st=max(-2.0, min(2.0, formant)),
                    requires_eq=False,
                    requires_pitch_range=False,
                )
                before = target.asdict()
                plan = TransformationPlanner().plan(source_snapshot(), target, 1.0)
                self.assertEqual(target.asdict(), before)
                if guarded:
                    self.assertEqual(plan.status, "degraded")
                    self.assertEqual(plan.formant.requested_formant_shift_st, formant)
                    self.assertEqual(plan.formant.applied_formant_shift_st, 0.0)
                    self.assertTrue(plan.formant.naturalness_guard_active)
                    self.assertIn("naturalness guard", " ".join(plan.warnings))
                    self.assertNotIn("formant_shift", plan.required_capabilities)
                else:
                    self.assertNotEqual(plan.status, "degraded")
                    self.assertGreaterEqual(plan.formant.applied_formant_shift_st, 0.0)
                    self.assertFalse(plan.formant.naturalness_guard_active)

    def test_higher_brighter_direction_remains_positive_and_bounded(self):
        plan = TransformationPlanner().plan(source_snapshot(), HIGHER_BRIGHTER_REFERENCE, 1.0)
        self.assertGreater(plan.pitch.applied_pitch_shift_st, 0.0)
        self.assertAlmostEqual(plan.formant.applied_formant_shift_st, 1.2)
        self.assertLessEqual(abs(plan.pitch.applied_pitch_shift_st), HIGHER_BRIGHTER_REFERENCE.max_pitch_shift_st)

    def test_planner_is_deterministic_with_fixed_inputs(self):
        planner = TransformationPlanner(clock=lambda: 42.0)
        first = planner.plan(source_snapshot(), NATURAL_DEEP_REFERENCE, 0.75)
        second = planner.plan(source_snapshot(), NATURAL_DEEP_REFERENCE, 0.75)
        self.assertEqual(first, second)

    def test_lock_isolation_and_clear_for_natural_deep(self):
        service = make_service(calibrate_lock_lab=True)
        calibrate_and_lock(service, source=ready_source(median_f0_hz=120.0), target=NATURAL_DEEP_REFERENCE)
        locked = service.stable_control_snapshot().locked
        service.source_analysis_snapshot = lambda: ready_source(median_f0_hz=220.0)
        service.load_target_reference("large_cavernous")
        service.set_target_planner_strength(25)
        self.assertEqual(service.stable_control_snapshot().locked.plan, locked.plan)
        self.assertTrue(service.stable_control_snapshot().newer_suggestion_available)
        service.lock_suggested_transformation()
        self.assertEqual(service.stable_control_snapshot().locked.target_id, LARGE_CAVERNOUS_REFERENCE.target_id)
        service.return_transformation_to_neutral()
        self.assertIsNotNone(service.stable_control_snapshot().locked)
        service.clear_stored_transformation()
        self.assertIsNone(service.stable_control_snapshot().locked)

    def test_manual_trim_is_additive_and_can_create_stylized_warning(self):
        plan = TransformationPlanner().plan(source_snapshot(), NATURAL_DEEP_REFERENCE, 1.0)
        self.assertAlmostEqual(plan.formant.applied_formant_shift_st, 1.505)
        zero_trim = manual_trim(formant_trim=-1.505)
        zero_adjusted, zero_projection = apply_manual_trim(plan, zero_trim)
        self.assertAlmostEqual(zero_projection["final_formant_target_st"], 0.0)
        self.assertNotIn("stylized large-vocal-tract", " ".join(zero_adjusted.warnings))
        trim = manual_trim(formant_trim=-2.0)
        adjusted, projection = apply_manual_trim(plan, trim)
        self.assertEqual(trim.applied_formant_trim_st, -2.0)
        self.assertAlmostEqual(projection["final_formant_target_st"], -0.495)
        self.assertLess(adjusted.formant.applied_formant_shift_st, 0.0)
        self.assertIn("stylized large-vocal-tract", " ".join(adjusted.warnings))
        clamped = manual_trim(formant_trim=-2.5)
        self.assertEqual(clamped.requested_formant_trim_st, -2.5)
        self.assertEqual(clamped.applied_formant_trim_st, -2.0)
        self.assertEqual(plan.formant.applied_formant_shift_st, 1.505)

    def test_final_warning_return_neutral_and_clear_semantics(self):
        service = make_service(calibrate_lock_lab=True)
        calibrate_and_lock(service, source=ready_source(median_f0_hz=120.0), target=NATURAL_DEEP_REFERENCE)
        service.set_formant_trim(-2.0)
        state = service.stable_control_snapshot()
        self.assertLess(state.final_formant_target_st, 0.0)
        self.assertIn("stylized large-vocal-tract", " ".join(state.warnings))
        service.set_formant_trim(-1.505)
        self.assertAlmostEqual(service.stable_control_snapshot().final_formant_target_st, 0.0)
        self.assertNotIn("stylized large-vocal-tract", " ".join(service.stable_control_snapshot().warnings))
        service.set_formant_trim(-0.5)
        self.assertGreater(service.stable_control_snapshot().final_formant_target_st, 0.0)
        self.assertNotIn("stylized large-vocal-tract", " ".join(service.stable_control_snapshot().warnings))
        service.set_formant_trim(-2.0)
        service.set_plan_execution_enabled(True)
        service.return_transformation_to_neutral()
        runtime = service.transformation_execution_snapshot()
        self.assertFalse(runtime.enabled)
        self.assertEqual(runtime.target_pitch_semitones, 0.0)
        self.assertEqual(runtime.target_formant_semitones, 0.0)
        self.assertIsNotNone(service.stable_control_snapshot().locked)
        self.assertEqual(service.stable_control_snapshot().applied_formant_trim_st, -2.0)
        service.clear_stored_transformation()
        cleared = service.stable_control_snapshot()
        self.assertIsNone(cleared.locked)
        self.assertEqual(cleared.applied_formant_trim_st, 0.0)

    def test_legacy_alias_canonicalizes_without_dirty_state(self):
        plans = []
        for reference in ("natural_deep", "lower_weightier"):
            service = make_service(calibrate_lock_lab=True)
            service.load_target_reference(reference)
            service.set_target_planner_strength(100)
            service.source_analysis_snapshot = lambda: ready_source(median_f0_hz=120.0)
            service.capture_calibration()
            service.lock_suggested_transformation()
            state = service.stable_control_snapshot()
            self.assertEqual(state.suggestion.target_id, NATURAL_DEEP_REFERENCE.target_id)
            self.assertEqual(state.locked.target_id, NATURAL_DEEP_REFERENCE.target_id)
            self.assertEqual(state.current_target_name, "Natural Deep Reference")
            self.assertFalse(state.suggestion_differs_from_lock)
            self.assertFalse(state.newer_suggestion_available)
            plans.append(state.locked.plan)
        self.assertEqual(plans[0].pitch.applied_pitch_shift_st, plans[1].pitch.applied_pitch_shift_st)
        self.assertEqual(plans[0].formant.applied_formant_shift_st, plans[1].formant.applied_formant_shift_st)

    def test_normal_production_pitch_runtime_and_lab_chain_truthfulness(self):
        service = make_service()
        self.assertIn("Pitch Shift", service.engine.effect_chain.effect_names())
        service.start_audio(0, 1)
        service.apply_effect_parameters(1.0, 0.0, 4000, False, 0.35, 0.7, pitch=4.0)
        self.assertEqual(service.current_effect_params["pitch"], 4.0)
        self.assertTrue(service.select_preset("Deep Voice").success)
        self.assertEqual(service.current_effect_params["pitch"], -4)
        lab = make_service(parametric_eq_lab=True)
        chain = lab.engine.effect_chain.effect_names()
        self.assertEqual(chain.count("Experimental Pitch/Formant"), 1)
        self.assertNotIn("Pitch Shift", chain)

    def test_continuous_mode_uses_new_strategies_and_off_restores_lock(self):
        service = make_service(calibrate_lock_lab=True)
        calibrate_and_lock(service, source=ready_source(median_f0_hz=120.0), target=NATURAL_DEEP_REFERENCE)
        locked_pitch = service.stable_control_snapshot().locked.plan.pitch.applied_pitch_shift_st
        self.assertEqual(service.stable_adaptive_mode, ADAPTIVE_OFF)
        service.set_plan_execution_enabled(True)
        service.source_analysis_snapshot = lambda: ready_source(median_f0_hz=220.0)
        service.load_target_reference("large_cavernous")
        service.set_adaptive_updating_mode(ADAPTIVE_CONTINUOUS)
        continuous = service.transformation_execution_snapshot()
        self.assertEqual(continuous.target_id, LARGE_CAVERNOUS_REFERENCE.target_id)
        self.assertLess(continuous.target_formant_semitones, 0.0)
        service.set_adaptive_updating_mode(ADAPTIVE_OFF)
        restored = service.transformation_execution_snapshot()
        self.assertAlmostEqual(restored.target_pitch_semitones, locked_pitch)

    def test_ui_guidance_exposes_four_targets_and_strategy_text(self):
        app = qt_application()
        service = make_service(parametric_eq_lab=True)
        window = App(service)
        try:
            buttons = [button.text() for button in window.findChildren(QPushButton)]
            for label in ("Neutral", "Higher / Brighter", "Natural Deep", "Large / Cavernous"):
                self.assertIn(label, buttons)
            self.assertNotIn("Lower / Weightier", buttons)
            self.assertEqual(window.formant_trim.minimum(), -2.0)
            self.assertEqual(window.formant_trim.maximum(), 2.0)
            service.load_target_reference("natural_deep")
            window.refresh_target_planner()
            self.assertIn("lowers pitch while preserving vowel shape", window.target_plan_details.text())
            self.assertIn("natural_compensation", window.target_strategy_details.text())
            service.load_target_reference("large_cavernous")
            window.refresh_target_planner()
            self.assertIn("stylized", window.target_plan_details.text())
            self.assertIn("size_coupled_stylization", window.target_strategy_details.text())
            self.assertIn("Suggested Plan", window.execution_suggested_state.text())
        finally:
            window.close()
            app.processEvents()

    def test_deterministic_audio_probe_is_finite_without_extra_stage(self):
        x = voice_like_signal()
        for target in TARGET_REFERENCE_ORDER:
            service = make_service(calibrate_lock_lab=True)
            calibrate_and_lock(service, source=ready_source(median_f0_hz=120.0), target=target)
            service.set_plan_execution_enabled(True)
            y = process_blocks(service, x)
            self.assertEqual(y.shape, x.shape)
            self.assertEqual(y.dtype, np.float32)
            self.assertTrue(np.all(np.isfinite(y)))
            self.assertTrue(np.array_equal(x, voice_like_signal()))
            chain = service.engine.effect_chain.effect_names()
            self.assertEqual(chain.count("Experimental Pitch/Formant"), 1)
            self.assertNotIn("Pitch Shift", chain)
            self.assertEqual(service.transformation_execution_snapshot().latency_frames, 4800)


if __name__ == "__main__":
    unittest.main()
