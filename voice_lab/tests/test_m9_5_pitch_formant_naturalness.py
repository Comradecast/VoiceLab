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
        for target in TARGET_REFERENCE_ORDER:
            with self.subTest(target=target.target_id):
                plan = TransformationPlanner().plan(source_snapshot(), target, 0.0)
                self.assertEqual(plan.pitch.applied_pitch_shift_st, 0.0)
                self.assertEqual(plan.formant.applied_formant_shift_st, 0.0)
                self.assertFalse(plan.formant.naturalness_guard_active)
                self.assertFalse(plan.formant.stylized_formant_combination_active)
                self.assertFalse(plan.dynamics.compressor.compressor_enabled)
                self.assertFalse(plan.dynamics.limiter.limiter_enabled)
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

    def test_large_cavernous_is_stylized_negative_formant(self):
        plan = TransformationPlanner().plan(source_snapshot(), LARGE_CAVERNOUS_REFERENCE, 1.0)
        self.assertLess(plan.pitch.applied_pitch_shift_st, 0.0)
        self.assertLess(plan.formant.applied_formant_shift_st, 0.0)
        self.assertTrue(plan.formant.stylized_formant_combination_active)
        self.assertIn("stylized negative pitch plus negative formant", " ".join(plan.warnings))
        self.assertNotEqual(plan.target_id, NATURAL_DEEP_REFERENCE.target_id)

    def test_naturalness_guard_blocks_inconsistent_natural_target(self):
        bad = target_voice_profile(
            target_id="bad-natural",
            display_name="Bad Natural",
            description="bad",
            pitch_strategy=PitchStrategy("relative_shift", -3.5),
            formant_strategy=FormantStrategy("restrained_fixed_shift", fixed_shift_st=-1.0, natural=True),
            nominal_formant_shift_st=-1.0,
            requires_eq=False,
            requires_pitch_range=False,
        )
        before = bad.asdict()
        plan = TransformationPlanner().plan(source_snapshot(), bad, 1.0)
        self.assertEqual(plan.status, "degraded")
        self.assertEqual(plan.formant.applied_formant_shift_st, 0.0)
        self.assertTrue(plan.formant.naturalness_guard_active)
        self.assertIn("naturalness guard", " ".join(plan.warnings))
        self.assertEqual(bad.asdict(), before)

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
        plan = TransformationPlanner().plan(source_snapshot(), NATURAL_DEEP_REFERENCE, 0.5)
        trim = manual_trim(formant_trim=-1.0)
        adjusted, projection = apply_manual_trim(plan, trim)
        self.assertEqual(plan.formant.applied_formant_shift_st, 0.7525)
        self.assertAlmostEqual(projection["final_formant_target_st"], -0.2475)
        self.assertLess(adjusted.formant.applied_formant_shift_st, 0.0)
        self.assertIn("stylized large-vocal-tract", " ".join(adjusted.warnings))

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
