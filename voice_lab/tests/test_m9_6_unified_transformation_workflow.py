import os
import unittest

from PySide6.QtWidgets import QApplication, QGroupBox, QPushButton

from voice_lab.planner import (
    HIGHER_BRIGHTER_REFERENCE,
    LARGE_CAVERNOUS_REFERENCE,
    NATURAL_DEEP_REFERENCE,
    SMALL_CARTOON_REFERENCE,
    TransformationPlanner,
)
from voice_lab.tests.test_m9_1_target_planner import source_snapshot
from voice_lab.tests.test_m9_3_calibrate_lock import make_service, process_blocks, ready_source
from voice_lab.tests.test_m9_5_pitch_formant_naturalness import voice_like_signal
from voice_lab.ui.main_window import App


def qt_application():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


class M96UnifiedTransformationWorkflowTests(unittest.TestCase):
    def test_primary_workflow_without_tab_specific_calls(self):
        service = make_service(parametric_eq_lab=True)
        service.source_analysis_snapshot = lambda: ready_source(median_f0_hz=120.0)
        state = service.transformation_workflow_snapshot()
        self.assertEqual(state["primary_label"], "Calibrate Voice")

        self.assertTrue(service.capture_calibration().success)
        self.assertTrue(service.load_target_reference("natural_bright").success)
        self.assertTrue(service.set_target_planner_strength(75).success)
        state = service.transformation_workflow_snapshot()
        self.assertEqual(state["primary_label"], "Apply Transformation")
        self.assertIn("Natural Bright", state["summary"])

        result = service.apply_suggested_transformation()
        self.assertTrue(result.success)
        state = service.transformation_workflow_snapshot()
        self.assertEqual(state["primary_label"], "Transformation Applied")
        self.assertEqual(state["applied_state"], "Applied")
        self.assertFalse(state["dirty"])
        self.assertEqual(state["stable"].locked.target_id, HIGHER_BRIGHTER_REFERENCE.target_id)
        self.assertTrue(state["stable"].execution_enabled)

        self.assertTrue(service.set_formant_trim(-0.5).success)
        self.assertAlmostEqual(service.stable_control_snapshot().final_formant_target_st, 0.25)
        self.assertTrue(service.return_transformation_to_neutral().success)
        self.assertEqual(service.transformation_workflow_snapshot()["primary_label"], "Resume Transformation")
        self.assertTrue(service.set_plan_execution_enabled(True).success)
        self.assertTrue(service.clear_stored_transformation().success)
        cleared = service.transformation_workflow_snapshot()
        self.assertEqual(cleared["applied_state"], "No Stored Transformation")
        self.assertIsNone(cleared["stable"].locked)

    def test_atomic_apply_requires_suggestion_and_rolls_back_on_failure(self):
        service = make_service(calibrate_lock_lab=True)
        blocked = service.apply_suggested_transformation()
        self.assertFalse(blocked.success)
        self.assertIsNone(service.stable_control_snapshot().locked)

        service.source_analysis_snapshot = lambda: ready_source(median_f0_hz=120.0)
        self.assertTrue(service.capture_calibration().success)
        self.assertTrue(service.load_target_reference("natural_bright").success)
        before_generation = service.stable_control_snapshot().lock_generation
        applied = service.apply_suggested_transformation()
        self.assertTrue(applied.success)
        state = service.stable_control_snapshot()
        self.assertEqual(state.lock_generation, before_generation + 1)
        self.assertTrue(state.execution_enabled)
        self.assertEqual(state.locked.plan, state.suggestion.plan)

        prior_lock = state.locked
        prior_generation = state.lock_generation
        service.load_target_reference("small_cartoon")

        def fail_refresh():
            raise RuntimeError("controlled apply failure")

        service._refresh_execution_target = fail_refresh
        failed = service.apply_suggested_transformation()
        self.assertFalse(failed.success)
        after = service.stable_control_snapshot()
        self.assertEqual(after.lock_generation, prior_generation)
        self.assertEqual(after.locked.lock_id, prior_lock.lock_id)
        self.assertEqual(after.locked.target_id, prior_lock.target_id)
        self.assertEqual(after.locked.plan, prior_lock.plan)
        self.assertTrue(after.execution_enabled)

    def test_state_driven_action_and_dirty_behavior(self):
        service = make_service(parametric_eq_lab=True)
        service._processing_state = "stopped"
        self.assertEqual(service.transformation_workflow_snapshot()["primary_label"], "Start Listening")

        service._processing_state = "running"
        service.source_analysis_snapshot = lambda: ready_source(ready=False, reliability="collecting")
        analyzing = service.transformation_workflow_snapshot()
        self.assertEqual(analyzing["primary_label"], "Analyzing Voice...")
        self.assertFalse(analyzing["primary_enabled"])

        service.source_analysis_snapshot = lambda: ready_source(median_f0_hz=120.0)
        self.assertEqual(service.transformation_workflow_snapshot()["primary_label"], "Calibrate Voice")
        service.capture_calibration()
        self.assertEqual(service.transformation_workflow_snapshot()["primary_label"], "Apply Transformation")
        service.apply_suggested_transformation()
        self.assertEqual(service.transformation_workflow_snapshot()["primary_label"], "Transformation Applied")
        service.load_target_reference("small_cartoon")
        dirty = service.transformation_workflow_snapshot()
        self.assertEqual(dirty["primary_label"], "Apply Changes")
        self.assertTrue(dirty["dirty"])
        self.assertEqual(dirty["applied_state"], "Changes Not Applied")
        service.apply_suggested_transformation()
        self.assertFalse(service.transformation_workflow_snapshot()["dirty"])

    def test_unified_page_navigation_persistent_status_and_diagnostics(self):
        app = qt_application()
        service = make_service(parametric_eq_lab=True)
        service.source_analysis_snapshot = lambda: ready_source(median_f0_hz=120.0)
        window = App(service)
        try:
            titles = [window.tabs.tabText(index) for index in range(window.tabs.count())]
            self.assertEqual(titles[:4], ["Transform", "Input Processing", "Routing", "Diagnostics"])
            for title in ("Source Analysis", "Target Planner", "Plan Execution", "Calibrate & Lock", "Parametric EQ"):
                self.assertIn(title, titles)
            self.assertIn("Transform", titles[0])
            buttons = [button.text() for button in window.findChildren(QPushButton)]
            for label in ("Neutral", "Natural Bright", "Natural Deep", "Small / Cartoon", "Large / Cavernous"):
                self.assertTrue(any(label in button for button in buttons))
            self.assertTrue(any("Advanced Tone Shaping - Parametric EQ" == box.title() for box in window.findChildren(QGroupBox)))
            self.assertIn("Analysis", window.transformation_summary.text())
            service.capture_calibration()
            service.load_target_reference("natural_bright")
            service.set_target_planner_strength(100)
            service.apply_suggested_transformation()
            window.refresh_transform_workflow()
            self.assertIn("Natural Bright", window.transformation_summary.text())
            self.assertIn("Applied", window.transformation_summary.text())
            service.set_target_planner_strength(50)
            window.refresh_transform_workflow()
            self.assertIn("Changes Not Applied", window.transformation_summary.text())
            self.assertIn("Preview", window.transform_preview.text())
            self.assertIn("Applied Transformation", window.transform_applied.text())
        finally:
            window.close()
            app.processEvents()

    def test_target_values_dsp_and_eq_authority_unchanged(self):
        source = source_snapshot(median_f0_hz=120.0)
        cases = (
            (HIGHER_BRIGHTER_REFERENCE, 3.5, 1.0),
            (NATURAL_DEEP_REFERENCE, -3.5, 1.505),
            (SMALL_CARTOON_REFERENCE, 6.0, 2.0),
            (LARGE_CAVERNOUS_REFERENCE, -4.5, -1.5),
        )
        for target, pitch, formant in cases:
            plan = TransformationPlanner().plan(source, target, 1.0)
            self.assertAlmostEqual(plan.pitch.applied_pitch_shift_st, pitch)
            self.assertAlmostEqual(plan.formant.applied_formant_shift_st, formant)

        service = make_service(parametric_eq_lab=True)
        self.assertIs(service.engine.parametric_eq_controller, service.parametric_eq_controller)
        service.source_analysis_snapshot = lambda: ready_source(median_f0_hz=120.0)
        service.capture_calibration()
        service.apply_suggested_transformation()
        process_blocks(service, voice_like_signal())
        execution = service.transformation_execution_snapshot()
        self.assertEqual(service.engine.effect_chain.effect_names().count("Experimental Pitch/Formant"), 1)
        self.assertNotIn("Pitch Shift", service.engine.effect_chain.effect_names())
        self.assertEqual(execution.latency_frames, 4800)
        self.assertEqual(service.parametric_eq_snapshot().added_latency_frames, 0)


if __name__ == "__main__":
    unittest.main()
