import os
import unittest

import numpy as np
from PySide6.QtWidgets import QApplication

from voice_lab.planner import HIGHER_BRIGHTER_REFERENCE, LOWER_WEIGHTIER_REFERENCE
from voice_lab.tests.test_m9_3_calibrate_lock import (
    calibrate_and_lock,
    make_service,
    process_blocks,
    ready_source,
)
from voice_lab.ui.main_window import App


def qt_application():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def probe_signal(samples=8192):
    t = np.arange(samples, dtype=np.float32) / 48000.0
    return (
        0.13 * np.sin(2.0 * np.pi * 140.0 * t)
        + 0.07 * np.sin(2.0 * np.pi * 520.0 * t)
        + 0.04 * np.sin(2.0 * np.pi * 1800.0 * t)
    ).astype(np.float32)


class LaboratoryWorkflowTruthfulnessTests(unittest.TestCase):
    def test_voice_tab_mode_aware_pitch_control_and_chain_indicator(self):
        app = qt_application()
        normal = make_service()
        lab = make_service(parametric_eq_lab=True)
        normal_window = App(normal)
        lab_window = App(lab)
        try:
            self.assertTrue(normal.voice_control_availability()["controls"]["pitch"]["editable"])
            self.assertTrue(normal_window.pitch.isEnabled())
            lab_availability = lab.voice_control_availability()
            self.assertFalse(lab_availability["controls"]["pitch"]["editable"])
            self.assertIn("Experimental Pitch/Formant", lab_availability["chain_label"])
            self.assertIn("Parametric EQ", lab_availability["chain_label"])
            self.assertFalse(lab_window.pitch.isEnabled())
            self.assertIn("Production Pitch Shift is not in this lab chain", lab_window.voice_pitch_lab_note.text())
            self.assertTrue(lab_window.gain.isEnabled())
            self.assertTrue(lab_window.robot.isEnabled())
            self.assertTrue(lab_window.lowpass.isEnabled())
        finally:
            normal_window.close()
            lab_window.close()
            app.processEvents()

    def test_return_audio_to_neutral_matches_baseline_and_retains_stored_plan(self):
        baseline_service = make_service(calibrate_lock_lab=True)
        service = make_service(calibrate_lock_lab=True)
        calibrate_and_lock(service, source=ready_source(median_f0_hz=110.0), target=HIGHER_BRIGHTER_REFERENCE)
        locked = service.stable_control_snapshot().locked
        self.assertIsNotNone(locked)
        self.assertTrue(service.set_pitch_trim(-1.0).success)
        self.assertTrue(service.set_formant_trim(0.25).success)
        self.assertTrue(service.set_plan_execution_enabled(True).success)
        active = service.transformation_execution_snapshot()
        self.assertTrue(active.enabled)
        self.assertFalse(active.neutral)

        x = probe_signal()
        service.engine.process_voice(x.copy(), len(x))
        result = service.return_transformation_to_neutral()
        self.assertTrue(result.success)
        self.assertIn("Audio is neutral. Stored transformation retained.", result.message)
        for _ in range(12):
            service.engine.process_voice(x.copy(), 512)
        neutral = service.transformation_execution_snapshot()
        self.assertFalse(neutral.enabled)
        self.assertTrue(neutral.neutral)
        self.assertEqual(neutral.target_pitch_semitones, 0.0)
        self.assertEqual(neutral.target_formant_semitones, 0.0)
        self.assertFalse(neutral.compressor_override_active)
        self.assertFalse(neutral.limiter_override_active)
        self.assertEqual(service.stable_control_snapshot().locked, locked)
        self.assertTrue(service.stable_control_snapshot().manual_trim_active)
        service.engine.stop()
        baseline_service.engine.stop()
        np.testing.assert_allclose(
            process_blocks(service, x),
            process_blocks(baseline_service, x),
            atol=0.0,
        )

    def test_clear_stored_transformation_clears_lock_trims_authority_and_preserves_suggestion_context(self):
        service = make_service(calibrate_lock_lab=True)
        calibrate_and_lock(service, source=ready_source(median_f0_hz=110.0), target=HIGHER_BRIGHTER_REFERENCE)
        calibration = service.stable_control_snapshot().calibration
        suggestion = service.stable_control_snapshot().suggestion
        service.set_pitch_trim(-2.0)
        service.set_formant_trim(0.5)
        service.set_plan_execution_enabled(True)
        result = service.clear_stored_transformation()
        self.assertTrue(result.success)
        self.assertEqual(result.message, "No stored transformation. Audio is neutral.")
        state = service.stable_control_snapshot()
        runtime = service.transformation_execution_runtime.snapshot()
        self.assertIsNone(state.locked)
        self.assertFalse(state.manual_trim_active)
        self.assertFalse(state.execution_enabled)
        self.assertEqual(state.execution_authority, "none")
        self.assertEqual(state.adaptive_mode, "off")
        self.assertEqual(state.calibration, calibration)
        self.assertEqual(state.suggestion.target_id, suggestion.target_id)
        self.assertEqual(state.current_target_id, HIGHER_BRIGHTER_REFERENCE.target_id)
        self.assertEqual(state.current_strength, 1.0)
        self.assertFalse(runtime.enabled)
        self.assertTrue(runtime.neutral)
        self.assertEqual(service.transformation_execution_controller.retained_counts(), {"plans": 0, "targets": 0})

    def test_target_change_updates_suggestion_only_and_ui_labels_relock_requirement(self):
        app = qt_application()
        service = make_service(calibrate_lock_lab=True)
        calibrate_and_lock(service, source=ready_source(median_f0_hz=110.0), target=HIGHER_BRIGHTER_REFERENCE)
        locked = service.stable_control_snapshot().locked
        service.load_target_reference("lower_weightier")
        service.set_target_planner_strength(40)
        state = service.stable_control_snapshot()
        self.assertTrue(state.newer_suggestion_available)
        self.assertEqual(state.locked.plan, locked.plan)
        self.assertEqual(state.locked.lock_id, locked.lock_id)
        window = App(service)
        try:
            window.refresh_target_planner()
            window.refresh_calibrate_lock()
            window.refresh_execution_lab()
            self.assertIn("require Lock Suggested Transformation", window.target_plan_details.text() + window.target_execution_details.text())
            self.assertIn("New suggestion available", window.adaptation_state.text())
            self.assertIn("Suggested Plan", window.execution_suggested_state.text())
            self.assertIn("Stored Plan: Present", window.execution_stored_state.text())
            self.assertIn("Applied Runtime: Neutral", window.execution_applied_state.text())
            service.load_target_reference("neutral")
            self.assertEqual(service.stable_control_snapshot().locked.plan, locked.plan)
        finally:
            window.close()
            app.processEvents()

    def test_supported_and_unsupported_capabilities_are_separated(self):
        app = qt_application()
        service = make_service(calibrate_lock_lab=True)
        service.source_analysis_snapshot = lambda: ready_source()
        service.capture_calibration()
        window = App(service)
        try:
            window.refresh_target_planner()
            self.assertIn("Executed Now:", window.target_execution_details.text())
            self.assertIn("Planned but Not Executed:", window.target_unsupported_details.text())
            self.assertTrue(window.target_unsupported_details.isHidden())
            window.target_unsupported_toggle.setChecked(True)
            window.refresh_target_planner()
            self.assertFalse(window.target_unsupported_details.isHidden())
        finally:
            window.close()
            app.processEvents()

    def test_calibrate_lock_buttons_and_workflow_show_exact_prerequisites(self):
        app = qt_application()
        service = make_service(calibrate_lock_lab=True)
        service._processing_state = "stopped"
        service.source_analysis_snapshot = lambda: ready_source()
        window = App(service)
        try:
            window.refresh_calibrate_lock()
            self.assertFalse(window.calibrate_source_button.isEnabled())
            self.assertFalse(window.recalibrate_source_button.isEnabled())
            self.assertFalse(window.lock_suggested_button.isEnabled())
            self.assertIn("Processing is not running.", window.command_availability_state.text())
            self.assertIn("Step 2 of 8", window.workflow_state.text())

            service._processing_state = "running"
            window.refresh_calibrate_lock()
            self.assertTrue(window.calibrate_source_button.isEnabled())
            self.assertFalse(window.recalibrate_source_button.isEnabled())
            self.assertFalse(window.lock_suggested_button.isEnabled())
            self.assertIn("Step 3 of 8", window.workflow_state.text())

            service.capture_calibration()
            window.refresh_calibrate_lock()
            self.assertTrue(window.recalibrate_source_button.isEnabled())
            self.assertTrue(window.lock_suggested_button.isEnabled())
            self.assertIn("Step 5 of 8", window.workflow_state.text())
        finally:
            window.close()
            app.processEvents()

    def test_cross_tab_snapshots_share_service_state_without_construction_order_dependency(self):
        service = make_service(parametric_eq_lab=True)
        service.source_analysis_snapshot = lambda: ready_source(median_f0_hz=118.0)
        self.assertTrue(service.capture_calibration().success)
        self.assertTrue(service.load_target_reference("large_cavernous").success)
        self.assertTrue(service.lock_suggested_transformation().success)

        source = service.source_analysis_snapshot()
        target = service.target_planner_state()
        execution = service.transformation_execution_snapshot()
        stable = service.stable_control_snapshot()

        self.assertEqual(source["profile"]["ready"], stable.source_ready)
        self.assertEqual(target["plan"]["target_id"], stable.suggestion.target_id)
        self.assertEqual(target["plan"]["status"], stable.suggestion.planner_status)
        self.assertEqual(
            target["plan"]["pitch"]["applied_pitch_shift_st"],
            stable.suggestion.plan.pitch.applied_pitch_shift_st,
        )
        self.assertEqual(
            target["plan"]["formant"]["applied_formant_shift_st"],
            stable.suggestion.plan.formant.applied_formant_shift_st,
        )
        self.assertEqual(execution.target_id, stable.locked.target_id)
        self.assertEqual(stable.current_target_id, stable.suggestion.target_id)
        self.assertEqual(stable.locked.plan, stable.suggestion.plan)

        app = qt_application()
        first = App(service)
        second = App(service)
        try:
            second.refresh_execution_lab()
            first.refresh_calibrate_lock()
            self.assertIn(stable.locked.target_id, first.locked_state.text())
            self.assertIn(stable.suggestion.target_id, second.execution_suggested_state.text())
        finally:
            first.close()
            second.close()
            app.processEvents()

    def test_soundboard_disabled_in_labs_and_normal_mode_unchanged(self):
        app = qt_application()
        normal = make_service()
        lab = make_service(target_planner_lab=True)
        self.assertTrue(normal.soundboard_available())
        self.assertFalse(lab.soundboard_available())
        self.assertNotEqual(normal.sound_files(), ())
        self.assertEqual(lab.sound_files(), ())
        self.assertFalse(lab.play_sound_by_index(0).success)
        window = App(lab)
        try:
            self.assertIn("Soundboard is disabled", window.soundboard_policy.text())
        finally:
            window.close()
            app.processEvents()

    def test_parametric_eq_chain_and_planner_targets_remain_unchanged(self):
        eq = make_service(parametric_eq_lab=True)
        self.assertEqual(
            eq.engine.effect_chain.effect_names(),
            [
                "High-Pass",
                "Noise Gate",
                "Compressor",
                "Experimental Pitch/Formant",
                "Parametric EQ",
                "Robot",
                "Lowpass",
                "Gain",
                "Limiter",
            ],
        )
        before = LOWER_WEIGHTIER_REFERENCE.asdict()
        eq.target_planner.plan(ready_source(), LOWER_WEIGHTIER_REFERENCE, 0.75)
        self.assertEqual(LOWER_WEIGHTIER_REFERENCE.asdict(), before)


if __name__ == "__main__":
    unittest.main()
