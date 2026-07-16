import dataclasses
import math
import os
import unittest

import numpy as np
from PySide6.QtWidgets import QApplication, QPushButton

from voice_lab.calibrate_lock import apply_manual_trim, manual_trim
from voice_lab.planner import (
    DEFAULT_TARGET_PROFILE,
    HIGHER_BRIGHTER_REFERENCE,
    LARGE_CAVERNOUS_REFERENCE,
    LOWER_WEIGHTIER_REFERENCE,
    NATURAL_DEEP_REFERENCE,
    SMALL_CARTOON_REFERENCE,
    TARGET_REFERENCE_ORDER,
    TransformationPlanner,
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
from voice_lab.tests.test_m9_5_pitch_formant_naturalness import voice_like_signal
from voice_lab.ui.main_window import App


SOURCE_MEDIANS = (80.0, 100.0, 120.0, 150.0, 180.0, 200.0, 240.0)
STRENGTHS = (0.0, 0.25, 0.5, 0.75, 1.0)


def qt_application():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


class M96HigherBrighterNaturalnessTests(unittest.TestCase):
    def test_contract_registry_order_aliases_and_existing_targets(self):
        self.assertEqual(
            tuple(target.target_id for target in TARGET_REFERENCE_ORDER),
            (
                "diagnostic-neutral",
                "diagnostic-higher-brighter",
                "diagnostic-lower-weightier",
                "diagnostic-small-cartoon",
                "diagnostic-large-cavernous",
            ),
        )
        self.assertEqual(len(TARGET_REFERENCE_ORDER), 5)
        self.assertEqual(len({target.target_id for target in TARGET_REFERENCE_ORDER}), 5)
        self.assertEqual(HIGHER_BRIGHTER_REFERENCE.display_name, "Natural Bright Reference")
        self.assertEqual(HIGHER_BRIGHTER_REFERENCE.target_id, "diagnostic-higher-brighter")
        self.assertEqual(HIGHER_BRIGHTER_REFERENCE.pitch_strategy.strategy_id, "relative_shift")
        self.assertEqual(HIGHER_BRIGHTER_REFERENCE.formant_strategy.strategy_id, "restrained_fixed_shift")
        self.assertEqual(SMALL_CARTOON_REFERENCE.target_id, "diagnostic-small-cartoon")
        self.assertEqual(SMALL_CARTOON_REFERENCE.formant_strategy.strategy_id, "size_coupled_stylization")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            HIGHER_BRIGHTER_REFERENCE.pitch_strategy.relative_shift_st = 10.0
        self.assertEqual(LOWER_WEIGHTIER_REFERENCE.target_id, NATURAL_DEEP_REFERENCE.target_id)
        self.assertAlmostEqual(NATURAL_DEEP_REFERENCE.pitch_strategy.relative_shift_st, -3.5)
        self.assertAlmostEqual(NATURAL_DEEP_REFERENCE.formant_strategy.compensation_ratio * 3.5, 1.505)
        self.assertAlmostEqual(LARGE_CAVERNOUS_REFERENCE.pitch_strategy.relative_shift_st, -4.5)
        self.assertAlmostEqual(LARGE_CAVERNOUS_REFERENCE.formant_strategy.fixed_shift_st, -1.5)

    def test_legacy_higher_brighter_lookup_resolves_natural_bright_without_dirty_state(self):
        plans = []
        for reference in ("higher_brighter", "natural_bright"):
            service = make_service(calibrate_lock_lab=True)
            self.assertTrue(service.load_target_reference(reference).success)
            service.set_target_planner_strength(100)
            service.source_analysis_snapshot = lambda: ready_source(median_f0_hz=120.0)
            self.assertTrue(service.capture_calibration().success)
            self.assertTrue(service.lock_suggested_transformation().success)
            state = service.stable_control_snapshot()
            self.assertEqual(state.suggestion.target_id, "diagnostic-higher-brighter")
            self.assertEqual(state.locked.target_id, "diagnostic-higher-brighter")
            self.assertEqual(state.current_target_name, "Natural Bright Reference")
            self.assertFalse(state.suggestion_differs_from_lock)
            self.assertFalse(state.newer_suggestion_available)
            plans.append(state.locked.plan)
        self.assertEqual(plans[0].target_id, plans[1].target_id)
        self.assertEqual(plans[0].pitch.applied_pitch_shift_st, plans[1].pitch.applied_pitch_shift_st)
        self.assertEqual(plans[0].formant.applied_formant_shift_st, plans[1].formant.applied_formant_shift_st)

    def test_zero_strength_is_fully_neutral_for_all_targets_and_aliases(self):
        targets = TARGET_REFERENCE_ORDER + (LOWER_WEIGHTIER_REFERENCE,)
        for target in targets:
            with self.subTest(target=target.target_id):
                plan = TransformationPlanner().plan(source_snapshot(median_f0_hz=120.0), target, 0.0)
                self.assertEqual(plan.pitch.requested_pitch_shift_st, 0.0)
                self.assertEqual(plan.pitch.applied_pitch_shift_st, 0.0)
                self.assertEqual(plan.formant.requested_formant_shift_st, 0.0)
                self.assertEqual(plan.formant.applied_formant_shift_st, 0.0)
                self.assertFalse(plan.formant.stylized_formant_combination_active)
                self.assertFalse(plan.dynamics.compressor_differs_from_neutral)
                self.assertFalse(plan.dynamics.limiter_differs_from_neutral)
                self.assertEqual(plan.required_capabilities, ())
                self.assertEqual(plan.warnings, ())

    def test_natural_bright_direction_interpolation_and_source_f0_independence(self):
        expected = {
            0.25: (0.875, 0.25),
            0.5: (1.75, 0.5),
            0.75: (2.625, 0.75),
            1.0: (3.5, 1.0),
        }
        for median in SOURCE_MEDIANS:
            previous_pitch = 0.0
            previous_formant = 0.0
            for strength, (pitch_st, formant_st) in expected.items():
                with self.subTest(median=median, strength=strength):
                    plan = TransformationPlanner().plan(
                        source_snapshot(median_f0_hz=median), HIGHER_BRIGHTER_REFERENCE, strength
                    )
                    self.assertAlmostEqual(plan.pitch.requested_pitch_shift_st, pitch_st)
                    self.assertAlmostEqual(plan.pitch.applied_pitch_shift_st, pitch_st)
                    self.assertAlmostEqual(plan.formant.requested_formant_shift_st, formant_st)
                    self.assertAlmostEqual(plan.formant.applied_formant_shift_st, formant_st)
                    self.assertFalse(plan.pitch.pitch_shift_clamped)
                    self.assertFalse(plan.formant.formant_clamped)
                    self.assertGreater(plan.pitch.applied_pitch_shift_st, previous_pitch)
                    self.assertGreater(plan.formant.applied_formant_shift_st, previous_formant)
                    self.assertFalse(plan.formant.stylized_formant_combination_active)
                    self.assertNotIn("chipmunk", " ".join(plan.warnings))
                    self.assertIn("adaptive_pitch_center", plan.required_capabilities)
                    self.assertIn("formant_shift", plan.required_capabilities)
                    self.assertNotIn("parametric_eq", plan.required_capabilities)
                    previous_pitch = plan.pitch.applied_pitch_shift_st
                    previous_formant = plan.formant.applied_formant_shift_st

    def test_estimated_resulting_f0_is_display_evidence_only(self):
        for median in SOURCE_MEDIANS:
            plan = TransformationPlanner().plan(source_snapshot(median_f0_hz=median), HIGHER_BRIGHTER_REFERENCE, 1.0)
            estimated = median * (2.0 ** (plan.pitch.applied_pitch_shift_st / 12.0))
            self.assertAlmostEqual(plan.pitch.requested_pitch_shift_st, 3.5)
            self.assertNotAlmostEqual(estimated, HIGHER_BRIGHTER_REFERENCE.target_median_f0_hz)

    def test_small_cartoon_is_stylized_positive_comparison_target(self):
        for strength in STRENGTHS:
            plan = TransformationPlanner().plan(source_snapshot(median_f0_hz=120.0), SMALL_CARTOON_REFERENCE, strength)
            bright = TransformationPlanner().plan(source_snapshot(median_f0_hz=120.0), HIGHER_BRIGHTER_REFERENCE, strength)
            if strength == 0.0:
                self.assertEqual(plan.required_capabilities, ())
                self.assertEqual(plan.warnings, ())
                self.assertFalse(plan.formant.stylized_formant_combination_active)
            else:
                self.assertGreater(plan.pitch.applied_pitch_shift_st, 0.0)
                self.assertGreater(plan.formant.applied_formant_shift_st, 0.0)
                self.assertGreater(plan.pitch.applied_pitch_shift_st, bright.pitch.applied_pitch_shift_st)
                self.assertGreater(plan.formant.applied_formant_shift_st, bright.formant.applied_formant_shift_st)
                self.assertTrue(plan.formant.stylized_formant_combination_active)
                self.assertIn("chipmunk-like", " ".join(plan.warnings))
                self.assertFalse(plan.pitch.pitch_shift_clamped)
                self.assertFalse(plan.formant.formant_clamped)
        full = TransformationPlanner().plan(source_snapshot(median_f0_hz=120.0), SMALL_CARTOON_REFERENCE, 1.0)
        self.assertAlmostEqual(full.pitch.applied_pitch_shift_st, 6.0)
        self.assertAlmostEqual(full.formant.applied_formant_shift_st, 2.0)

    def test_existing_natural_deep_and_large_cavernous_values_are_unchanged(self):
        deep = TransformationPlanner().plan(source_snapshot(median_f0_hz=120.0), NATURAL_DEEP_REFERENCE, 1.0)
        large = TransformationPlanner().plan(source_snapshot(median_f0_hz=120.0), LARGE_CAVERNOUS_REFERENCE, 1.0)
        self.assertAlmostEqual(deep.pitch.applied_pitch_shift_st, -3.5)
        self.assertAlmostEqual(deep.formant.applied_formant_shift_st, 1.505)
        self.assertAlmostEqual(large.pitch.applied_pitch_shift_st, -4.5)
        self.assertAlmostEqual(large.formant.applied_formant_shift_st, -1.5)
        self.assertIn("stylized negative pitch plus negative formant", " ".join(large.warnings))

    def test_lock_isolation_relock_return_neutral_and_clear_for_natural_bright(self):
        service = make_service(calibrate_lock_lab=True)
        calibrate_and_lock(service, source=ready_source(median_f0_hz=120.0), target=HIGHER_BRIGHTER_REFERENCE)
        locked = service.stable_control_snapshot().locked.plan
        service.source_analysis_snapshot = lambda: ready_source(median_f0_hz=240.0)
        service.load_target_reference("small_cartoon")
        service.set_target_planner_strength(50)
        self.assertEqual(service.stable_control_snapshot().locked.plan, locked)
        self.assertTrue(service.stable_control_snapshot().newer_suggestion_available)
        service.lock_suggested_transformation()
        self.assertEqual(service.stable_control_snapshot().locked.target_id, SMALL_CARTOON_REFERENCE.target_id)
        service.return_transformation_to_neutral()
        self.assertIsNotNone(service.stable_control_snapshot().locked)
        service.clear_stored_transformation()
        cleared = service.stable_control_snapshot()
        self.assertIsNone(cleared.locked)
        self.assertEqual(cleared.applied_formant_trim_st, 0.0)

    def test_continuous_uses_new_targets_and_off_restores_retained_lock(self):
        service = make_service(calibrate_lock_lab=True)
        calibrate_and_lock(service, source=ready_source(median_f0_hz=120.0), target=HIGHER_BRIGHTER_REFERENCE)
        locked_pitch = service.stable_control_snapshot().locked.plan.pitch.applied_pitch_shift_st
        self.assertEqual(service.stable_adaptive_mode, ADAPTIVE_OFF)
        service.set_plan_execution_enabled(True)
        service.load_target_reference("small_cartoon")
        service.set_adaptive_updating_mode(ADAPTIVE_CONTINUOUS)
        continuous = service.transformation_execution_snapshot()
        self.assertEqual(continuous.target_id, SMALL_CARTOON_REFERENCE.target_id)
        self.assertAlmostEqual(continuous.target_pitch_semitones, 6.0)
        self.assertAlmostEqual(continuous.target_formant_semitones, 2.0)
        service.set_adaptive_updating_mode(ADAPTIVE_OFF)
        restored = service.transformation_execution_snapshot()
        self.assertAlmostEqual(restored.target_pitch_semitones, locked_pitch)

    def test_manual_trim_compares_natural_bright_formant_values_without_mutating_base(self):
        plan = TransformationPlanner().plan(source_snapshot(median_f0_hz=120.0), HIGHER_BRIGHTER_REFERENCE, 1.0)
        self.assertAlmostEqual(plan.pitch.applied_pitch_shift_st, 3.5)
        self.assertAlmostEqual(plan.formant.applied_formant_shift_st, 1.0)
        for trim_value, expected_final in ((-1.0, 0.0), (-0.5, 0.5), (0.0, 1.0), (0.5, 1.5), (1.0, 2.0)):
            with self.subTest(trim=trim_value):
                adjusted, projection = apply_manual_trim(plan, manual_trim(formant_trim=trim_value))
                self.assertAlmostEqual(projection["locked_base_formant_st"], 1.0)
                self.assertAlmostEqual(projection["final_formant_target_st"], expected_final)
                self.assertAlmostEqual(adjusted.formant.applied_formant_shift_st, expected_final)
                self.assertAlmostEqual(plan.formant.applied_formant_shift_st, 1.0)

    def test_ui_guidance_exposes_five_targets_descriptions_and_base_trim_final_state(self):
        app = qt_application()
        service = make_service(parametric_eq_lab=True)
        window = App(service)
        try:
            buttons = [button.text() for button in window.findChildren(QPushButton)]
            for label in ("Neutral", "Natural Bright", "Natural Deep", "Small / Cartoon", "Large / Cavernous"):
                self.assertIn(label, buttons)
            self.assertNotIn("Higher / Brighter", buttons)
            service.load_target_reference("natural_bright")
            service.source_analysis_snapshot = lambda: ready_source(median_f0_hz=120.0)
            window.refresh_target_planner()
            self.assertIn("brighter but non-cartoon-like", window.target_plan_details.text())
            self.assertIn("3.5 st", window.target_strategy_details.text())
            service.load_target_reference("small_cartoon")
            window.refresh_target_planner()
            self.assertIn("chipmunk-like", window.target_plan_details.text())
            self.assertIn("size_coupled_stylization", window.target_strategy_details.text())
            calibrate_and_lock(service, source=ready_source(median_f0_hz=120.0), target=HIGHER_BRIGHTER_REFERENCE)
            service.set_formant_trim(-1.0)
            window.refresh_calibrate_lock()
            self.assertIn("formant base/requested/applied/final/current", window.trim_state.text())
            self.assertIn("1.0 st/-1.0 st/-1.0 st/0.0 st", window.trim_state.text())
            self.assertIn("Suggested Plan", window.execution_suggested_state.text())
            self.assertIn("Stored Plan", window.execution_stored_state.text())
            self.assertIn("Applied Runtime", window.execution_applied_state.text())
        finally:
            window.close()
            app.processEvents()

    def test_safe_audio_probe_for_m96_targets_uses_one_stage_and_latency(self):
        x = voice_like_signal()
        probes = (
            DEFAULT_TARGET_PROFILE,
            HIGHER_BRIGHTER_REFERENCE,
            SMALL_CARTOON_REFERENCE,
            NATURAL_DEEP_REFERENCE,
            LARGE_CAVERNOUS_REFERENCE,
        )
        for target in probes:
            with self.subTest(target=target.target_id):
                service = make_service(calibrate_lock_lab=True)
                calibrate_and_lock(service, source=ready_source(median_f0_hz=120.0), target=target)
                service.set_plan_execution_enabled(True)
                before = x.copy()
                y = process_blocks(service, x)
                snapshot = service.transformation_execution_snapshot()
                self.assertEqual(y.shape, x.shape)
                self.assertEqual(y.dtype, np.float32)
                self.assertTrue(np.all(np.isfinite(y)))
                self.assertTrue(np.array_equal(x, before))
                self.assertEqual(service.engine.effect_chain.effect_names().count("Experimental Pitch/Formant"), 1)
                self.assertNotIn("Pitch Shift", service.engine.effect_chain.effect_names())
                self.assertEqual(snapshot.latency_frames, 4800)


if __name__ == "__main__":
    unittest.main()
