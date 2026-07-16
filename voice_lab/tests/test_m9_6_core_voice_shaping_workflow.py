import os
import unittest

from PySide6.QtWidgets import QApplication, QPushButton

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


class M96CoreVoiceShapingWorkflowTests(unittest.TestCase):
    def test_transform_exposes_core_voice_shaping_controls(self):
        app = qt_application()
        service = make_service(parametric_eq_lab=True)
        window = App(service)
        try:
            labels = "\n".join(
                (
                    window.transform_gain_label.text(),
                    window.transform_robot_label.text(),
                    window.transform_lowpass_label.text(),
                    window.transform_high_pass_label.text(),
                    window.transform_core_status.text(),
                )
            )
            buttons = [button.text() for button in window.findChildren(QPushButton)]
            self.assertIn("Gain", labels)
            self.assertIn("Robot", labels)
            self.assertIn("Lowpass", labels)
            self.assertIn("High-Pass", labels)
            self.assertIn("Open Full Input Processing", buttons)
        finally:
            window.close()
            app.processEvents()

    def test_transform_core_controls_share_existing_voice_and_input_authority(self):
        app = qt_application()
        service = make_service(parametric_eq_lab=True)
        window = App(service)
        try:
            window.transform_gain.setValue(15)
            self.assertEqual(window.gain.value(), 15)
            self.assertAlmostEqual(service.current_effect_params["gain"], 1.5)

            window.transform_robot.setValue(40)
            self.assertEqual(window.robot.value(), 40)
            self.assertAlmostEqual(service.current_effect_params["robot"], 0.4)

            window.transform_lowpass.setValue(2600)
            self.assertEqual(window.lowpass.value(), 2600)
            self.assertEqual(service.current_effect_params["lowpass"], 2600)

            window.transform_high_pass_enabled.setChecked(True)
            window.transform_high_pass.setValue(120)
            self.assertTrue(service.current_input_processing.high_pass.enabled)
            self.assertEqual(service.current_input_processing.high_pass.cutoff_hz, 120)
            self.assertTrue(window.input_processing_controls["high_pass"]["enabled"].isChecked())
            self.assertEqual(window.input_processing_controls["high_pass"]["params"]["cutoff_hz"].value(), 120)

            window.gain.setValue(22)
            window.apply_current_parameters()
            window.sync_voice_controls_from_service()
            self.assertEqual(window.transform_gain.value(), 22)

            service.update_input_processing("high_pass", enabled=True, cutoff_hz=160)
            window.sync_input_processing_from_service()
            self.assertEqual(window.transform_high_pass.value(), 160)
            self.assertIn("160 Hz", window.transform_high_pass_label.text())
        finally:
            window.close()
            app.processEvents()

    def test_global_bypass_is_reported_and_not_mutated_by_core_edits(self):
        app = qt_application()
        service = make_service(parametric_eq_lab=True)
        window = App(service)
        try:
            self.assertTrue(service.set_effects_bypassed(True).success)
            window.sync_voice_controls_from_service()
            self.assertTrue(service.effects_bypassed)
            self.assertIn("Global Bypass Effects active", window.transform_core_status.text())
            window.transform_robot.setValue(70)
            self.assertTrue(service.effects_bypassed)
            self.assertAlmostEqual(service.current_effect_params["robot"], 0.7)
            self.assertIn("Global Bypass Effects active", window.transform_core_status.text())
        finally:
            window.close()
            app.processEvents()

    def test_mode_truthfulness_chain_order_and_no_duplicate_authority(self):
        service = make_service(parametric_eq_lab=True)
        self.assertEqual(
            service.engine.effect_chain.effect_names(),
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
        self.assertEqual(service.engine.effect_chain.effect_names().count("Robot"), 1)
        self.assertEqual(service.engine.effect_chain.effect_names().count("Lowpass"), 1)
        self.assertEqual(service.engine.effect_chain.effect_names().count("Gain"), 1)
        self.assertEqual(service.engine.effect_chain.effect_names().count("High-Pass"), 1)
        self.assertEqual(service.engine.effect_chain.effect_names().count("Experimental Pitch/Formant"), 1)
        self.assertNotIn("Pitch Shift", service.engine.effect_chain.effect_names())
        self.assertIs(service.engine.parametric_eq_controller, service.parametric_eq_controller)

    def test_target_values_latency_and_unified_workflow_regressions(self):
        source = source_snapshot(median_f0_hz=120.0)
        for target, pitch, formant in (
            (HIGHER_BRIGHTER_REFERENCE, 3.5, 1.0),
            (NATURAL_DEEP_REFERENCE, -3.5, 1.505),
            (SMALL_CARTOON_REFERENCE, 6.0, 2.0),
            (LARGE_CAVERNOUS_REFERENCE, -4.5, -1.5),
        ):
            plan = TransformationPlanner().plan(source, target, 1.0)
            self.assertAlmostEqual(plan.pitch.applied_pitch_shift_st, pitch)
            self.assertAlmostEqual(plan.formant.applied_formant_shift_st, formant)

        service = make_service(parametric_eq_lab=True)
        service.source_analysis_snapshot = lambda: ready_source(median_f0_hz=120.0)
        self.assertTrue(service.capture_calibration().success)
        self.assertEqual(service.transformation_workflow_snapshot()["primary_label"], "Apply Transformation")
        self.assertTrue(service.apply_suggested_transformation().success)
        self.assertEqual(service.transformation_workflow_snapshot()["primary_label"], "Transformation Applied")
        service.set_target_planner_strength(50)
        self.assertEqual(service.transformation_workflow_snapshot()["primary_label"], "Apply Changes")
        process_blocks(service, voice_like_signal())
        self.assertEqual(service.transformation_execution_snapshot().latency_frames, 4800)


if __name__ == "__main__":
    unittest.main()
