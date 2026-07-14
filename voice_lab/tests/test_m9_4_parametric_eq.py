import dataclasses
import inspect
import math
import os
import threading
import time
import unittest

import numpy as np
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from voice_lab.app.service import ApplicationService
from voice_lab.parametric_eq import (
    PARAMETRIC_EQ_BAND_ORDER,
    PARAMETRIC_EQ_TRANSITION_MS,
    ParametricEqApplicationSnapshot,
    ParametricEqBandParameters,
    ParametricEqPlan,
    default_band_definitions,
    design_coefficient_bank,
    flat_band_parameters,
    frequency_response,
    validate_band_parameters,
)
from voice_lab.planner import HIGHER_BRIGHTER_REFERENCE, LOWER_WEIGHTIER_REFERENCE
from voice_lab.tests.test_m9_3_calibrate_lock import calibrate_and_lock, make_service, process_blocks, ready_source
from voice_lab.ui.parametric_eq_graph import (
    adjusted_q_from_wheel,
    frequency_step_hz,
    frequency_to_x,
    gain_to_y,
    quantize_frequency_hz,
    quantize_gain_db,
    quantize_q,
    x_to_frequency,
    y_to_gain,
)
from voice_lab.ui.main_window import App


SAMPLE_RATE = 48000


def qt_application():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def sine_mix(samples=8192):
    t = np.arange(samples, dtype=np.float32) / SAMPLE_RATE
    data = (
        0.12 * np.sin(2.0 * np.pi * 120.0 * t)
        + 0.08 * np.sin(2.0 * np.pi * 300.0 * t)
        + 0.07 * np.sin(2.0 * np.pi * 1000.0 * t)
        + 0.05 * np.sin(2.0 * np.pi * 3000.0 * t)
        + 0.03 * np.sin(2.0 * np.pi * 8000.0 * t)
    )
    return data.astype(np.float32)


def band_dict(band_id, frequency_hz=None, gain_db=0.0, q=1.0, enabled=True):
    definitions = {definition.band_id: definition for definition in default_band_definitions()}
    definition = definitions[band_id]
    return {
        "band_id": band_id,
        "enabled": enabled,
        "frequency_hz": definition.default_frequency_hz if frequency_hz is None else frequency_hz,
        "gain_db": gain_db,
        "q": definition.default_q if not definition.q_editable else q,
    }


def parametric_eq_effect(service):
    return next(effect for effect in service.engine.effects if getattr(effect, "name", "") == "Parametric EQ")


def settle_parametric_eq(service, samples=None, block=256, extra_blocks=1):
    data = sine_mix(4096) if samples is None else samples
    chunks = []
    blocks = int(math.ceil(len(data) / float(block))) + extra_blocks
    for index in range(blocks):
        start = (index * block) % len(data)
        chunk = data[start : start + block]
        if len(chunk) < block:
            chunk = np.concatenate((chunk, data[: block - len(chunk)]))
        chunks.append(service.engine.process_voice(chunk.copy(), len(chunk)))
    return np.concatenate(chunks)


class _FakeMouseEvent:
    def __init__(self, position, modifiers=Qt.NoModifier, button=Qt.LeftButton):
        self._position = position
        self._modifiers = modifiers
        self._button = button

    def position(self):
        return self._position

    def modifiers(self):
        return self._modifiers

    def button(self):
        return self._button


class _FakeWheelEvent:
    def __init__(self, delta, modifiers=Qt.NoModifier):
        self._delta = delta
        self._modifiers = modifiers
        self.accepted = False

    def angleDelta(self):
        return QPoint(0, self._delta)

    def modifiers(self):
        return self._modifiers

    def accept(self):
        self.accepted = True


def assert_eq_transition_settled(testcase, service, *, flat=None, local_bypass=None, processing_active=None):
    snapshot = service.parametric_eq_snapshot()
    testcase.assertFalse(snapshot.transition_active)
    testcase.assertFalse(getattr(snapshot, "transition_pending", False))
    testcase.assertEqual(snapshot.transition_progress, 1.0)
    if flat is not None:
        testcase.assertEqual(snapshot.applied_plan.flat, flat)
    if local_bypass is not None:
        testcase.assertEqual(snapshot.local_bypass, local_bypass)
    if processing_active is not None:
        testcase.assertEqual(snapshot.processing_active, processing_active)
    return snapshot


class M94ContractValidationAndCoefficientTests(unittest.TestCase):
    def test_accessible_quantization_helpers_are_deterministic(self):
        self.assertEqual(quantize_gain_db(2.26, fine=False), 2.5)
        self.assertEqual(quantize_gain_db(2.24, fine=False), 2.0)
        self.assertEqual(quantize_gain_db(-2.26, fine=False), -2.5)
        self.assertEqual(quantize_gain_db(-2.24, fine=False), -2.0)
        self.assertEqual(quantize_gain_db(2.26, fine=True), 2.3)
        self.assertEqual(quantize_gain_db(-2.26, fine=True), -2.3)
        self.assertEqual(quantize_gain_db(0.0), 0.0)
        self.assertEqual(quantize_gain_db(0.25), 0.5)
        self.assertEqual(quantize_gain_db(-0.25), -0.5)
        service = make_service(parametric_eq_lab=True)
        self.assertTrue(service.set_parametric_eq_band_gain("mid", quantize_gain_db(99.0)).success)
        self.assertEqual(service.parametric_eq_snapshot().applied_plan.bands[2].applied_gain_db, 6.0)
        self.assertTrue(service.set_parametric_eq_band_gain("mid", quantize_gain_db(-99.0)).success)
        self.assertEqual(service.parametric_eq_snapshot().applied_plan.bands[2].applied_gain_db, -6.0)

        frequency_cases = (
            (60.0, False, 60.0),
            (62.6, False, 65.0),
            (62.6, True, 63.0),
            (120.0, False, 120.0),
            (199.0, False, 200.0),
            (199.0, True, 199.0),
            (200.0, False, 200.0),
            (300.0, False, 300.0),
            (999.0, False, 1000.0),
            (999.0, True, 1000.0),
            (1000.0, False, 1000.0),
            (3000.0, False, 3000.0),
            (3999.0, False, 4000.0),
            (3999.0, True, 4000.0),
            (4000.0, False, 4000.0),
            (8000.0, False, 8000.0),
            (12000.0, False, 12000.0),
        )
        for value, fine, expected in frequency_cases:
            self.assertEqual(quantize_frequency_hz(value, fine=fine), expected)
        self.assertEqual(frequency_step_hz(120.0, fine=False), 5.0)
        self.assertEqual(frequency_step_hz(120.0, fine=True), 1.0)
        self.assertEqual(frequency_step_hz(300.0, fine=False), 10.0)
        self.assertEqual(frequency_step_hz(3000.0, fine=False), 25.0)
        self.assertEqual(frequency_step_hz(8000.0, fine=True), 25.0)
        self.assertTrue(service.set_parametric_eq_band_frequency("low_shelf", quantize_frequency_hz(10.0)).success)
        self.assertEqual(service.parametric_eq_snapshot().applied_plan.bands[0].applied_frequency_hz, 60.0)

        self.assertEqual(quantize_q(1.13, fine=False), 1.25)
        self.assertEqual(quantize_q(1.13, fine=True), 1.15)
        self.assertEqual(adjusted_q_from_wheel(1.0, 120), 1.25)
        self.assertEqual(adjusted_q_from_wheel(1.0, -120), 0.75)
        self.assertEqual(adjusted_q_from_wheel(1.0, 120, fine=True), 1.05)
        self.assertEqual(adjusted_q_from_wheel(0.31, -120), 0.3)
        self.assertEqual(adjusted_q_from_wheel(5.95, 120), 6.0)
        for helper in (quantize_gain_db, quantize_frequency_hz, quantize_q):
            with self.assertRaises(ValueError):
                helper(math.nan)

    def test_contracts_are_frozen_scalar_snapshots_with_five_ordered_bands(self):
        service = make_service(parametric_eq_lab=True)
        snapshot = service.parametric_eq_snapshot()
        self.assertIsInstance(snapshot, ParametricEqApplicationSnapshot)
        self.assertIsInstance(snapshot.applied_plan, ParametricEqPlan)
        self.assertEqual(tuple(b.band_id for b in snapshot.applied_plan.bands), PARAMETRIC_EQ_BAND_ORDER)
        self.assertEqual(len(snapshot.applied_plan.bands), 5)
        self.assertIsInstance(snapshot.applied_plan.bands, tuple)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            snapshot.processing_active = True
        with self.assertRaises(dataclasses.FrozenInstanceError):
            snapshot.applied_plan.bands[0].applied_gain_db = 1.0
        old = snapshot
        service.set_parametric_eq_band_gain("mid", 2.0)
        self.assertEqual(old.applied_plan.bands[2].applied_gain_db, 0.0)

    def test_validation_clamps_boundaries_and_rejects_nonfinite_values_atomically(self):
        service = make_service(parametric_eq_lab=True)
        before = service.parametric_eq_snapshot()
        self.assertTrue(service.set_parametric_eq_band_gain("mid", 99.0).success)
        after = service.parametric_eq_snapshot()
        self.assertEqual(after.applied_plan.bands[2].applied_gain_db, 6.0)
        self.assertTrue(after.applied_plan.bands[2].gain_clamped)
        self.assertTrue(service.set_parametric_eq_band_frequency("high_shelf", 30000.0).success)
        high = service.parametric_eq_snapshot().applied_plan.bands[4]
        self.assertLessEqual(high.applied_frequency_hz, SAMPLE_RATE * 0.45)
        invalid_values = (math.nan, math.inf, -math.inf, True, "bad", None)
        for value in invalid_values:
            preserved = service.parametric_eq_snapshot()
            self.assertFalse(service.set_parametric_eq_band_gain("mid", value).success)
            self.assertEqual(service.parametric_eq_snapshot(), preserved)
            self.assertFalse(service.set_parametric_eq_band_frequency("mid", value).success)
            self.assertEqual(service.parametric_eq_snapshot(), preserved)
            self.assertFalse(service.set_parametric_eq_band_q("mid", value).success)
            self.assertEqual(service.parametric_eq_snapshot(), preserved)
        self.assertFalse(service.set_parametric_eq_band_gain("unknown", 1.0).success)
        self.assertEqual(before.applied_plan.bands[2].applied_gain_db, 0.0)

    def test_coefficients_are_finite_stable_deterministic_and_frequency_responses_are_directional(self):
        for sample_rate in (44100, 48000, 96000):
            flat = design_coefficient_bank(flat_band_parameters(sample_rate), sample_rate=sample_rate, coefficient_generation=1)
            self.assertTrue(flat.flat)
            np.testing.assert_allclose(np.abs(frequency_response(flat, [120, 1000, 8000])), np.ones(3), atol=1e-6)
            for definition in default_band_definitions():
                plus_band = validate_band_parameters(
                    definition.band_id,
                    frequency_hz=definition.default_frequency_hz,
                    gain_db=6.0,
                    q=definition.default_q,
                    sample_rate=sample_rate,
                )
                minus_band = validate_band_parameters(
                    definition.band_id,
                    frequency_hz=definition.default_frequency_hz,
                    gain_db=-6.0,
                    q=definition.default_q,
                    sample_rate=sample_rate,
                )
                plus = design_coefficient_bank((plus_band,), sample_rate=sample_rate, coefficient_generation=1)
                minus = design_coefficient_bank((minus_band,), sample_rate=sample_rate, coefficient_generation=1)
                self.assertTrue(all(np.isfinite(np.array(plus.sections).ravel())))
                self.assertEqual(plus.sections, design_coefficient_bank((plus_band,), sample_rate=sample_rate, coefficient_generation=1).sections)
                center = definition.default_frequency_hz
                center_plus = abs(frequency_response(plus, [center])[0])
                center_minus = abs(frequency_response(minus, [center])[0])
                self.assertGreater(center_plus, 1.05)
                self.assertLess(center_minus, 0.95)


class M94ProcessingAndIntegrationTests(unittest.TestCase):
    def test_flat_neutrality_disabled_and_enabled_match_calibrate_lock_chain(self):
        x = sine_mix()
        stable = make_service(calibrate_lock_lab=True)
        eq = make_service(parametric_eq_lab=True)
        eq_flat = make_service(parametric_eq_lab=True)
        y_stable = process_blocks(stable, x)
        y_disabled = process_blocks(eq, x)
        np.testing.assert_allclose(y_stable, y_disabled, atol=0.0)
        self.assertTrue(eq_flat.set_parametric_eq_enabled(True).success)
        y_flat = process_blocks(eq_flat, x)
        np.testing.assert_allclose(y_stable, y_flat, atol=0.0)
        self.assertEqual(y_flat.shape, x.shape)
        self.assertEqual(y_flat.dtype, np.float32)
        self.assertTrue(np.array_equal(x, sine_mix()))

    def test_each_band_changes_intended_region_and_five_band_cascade_is_finite(self):
        probes = (
            ("low_shelf", 80.0, 8000.0),
            ("low_mid", 300.0, 5000.0),
            ("mid", 1000.0, 120.0),
            ("presence", 3000.0, 120.0),
            ("high_shelf", 9000.0, 120.0),
        )
        for band_id, target, distant in probes:
            plus = design_coefficient_bank(
                (validate_band_parameters(band_id, frequency_hz=target, gain_db=6.0, q=1.0),),
                sample_rate=SAMPLE_RATE,
                coefficient_generation=1,
            )
            minus = design_coefficient_bank(
                (validate_band_parameters(band_id, frequency_hz=target, gain_db=-6.0, q=1.0),),
                sample_rate=SAMPLE_RATE,
                coefficient_generation=2,
            )
            target_plus = abs(frequency_response(plus, [target])[0])
            target_minus = abs(frequency_response(minus, [target])[0])
            distant_plus = abs(frequency_response(plus, [distant])[0])
            self.assertGreater(target_plus, 1.05, band_id)
            self.assertLess(target_minus, 0.95, band_id)
            self.assertLess(abs(distant_plus - 1.0), abs(target_plus - 1.0) + 0.05)

        service = make_service(parametric_eq_lab=True)
        self.assertTrue(service.set_parametric_eq_plan(
            (
                band_dict("low_shelf", gain_db=2.0),
                band_dict("low_mid", gain_db=-2.0, q=1.0),
                band_dict("mid", gain_db=-1.0, q=1.2),
                band_dict("presence", gain_db=2.0, q=1.0),
                band_dict("high_shelf", gain_db=1.5),
            ),
            enabled=True,
            bypassed=False,
        ).success)
        y = process_blocks(service, sine_mix())
        self.assertTrue(np.all(np.isfinite(y)))
        self.assertEqual(y.shape, sine_mix().shape)
        self.assertEqual(service.engine.effect_chain.effect_names()[-1], "Limiter")

    def test_dynamic_updates_transition_bounded_latest_wins_and_no_stream_restart(self):
        service = make_service(parametric_eq_lab=True)
        self.assertTrue(service.set_parametric_eq_enabled(True).success)
        x = sine_mix(4096)
        baseline = process_blocks(service, x, block=512)
        max_jump = 0.0
        for index in range(30):
            self.assertTrue(service.set_parametric_eq_band_gain("mid", -6.0 + (index % 13)).success)
            self.assertTrue(service.set_parametric_eq_band_frequency("presence", 1500.0 + (index * 100.0)).success)
            self.assertTrue(service.set_parametric_eq_band_q("low_mid", 0.3 + (index % 10) * 0.5).success)
            y = process_blocks(service, x, block=512)
            self.assertTrue(np.all(np.isfinite(y)))
            max_jump = max(max_jump, float(np.max(np.abs(np.diff(y)))))
        snapshot = service.parametric_eq_snapshot()
        self.assertFalse(snapshot.transition_active)
        self.assertGreater(snapshot.coefficient_generation, 1)
        self.assertLess(max_jump, 2.0)
        self.assertNotEqual(float(np.max(np.abs(process_blocks(service, x, block=512) - baseline))), 0.0)

    def test_local_global_bypass_failure_and_reset_are_truthful(self):
        service = make_service(parametric_eq_lab=True)
        service.set_parametric_eq_enabled(True)
        service.set_parametric_eq_band_gain("mid", 4.0)
        x = sine_mix()
        active = process_blocks(service, x)
        self.assertTrue(service.set_parametric_eq_bypassed(True).success)
        bypassed = process_blocks(service, x)
        self.assertGreater(float(np.max(np.abs(active - bypassed))), 0.0)
        service.set_effects_bypassed(True)
        global_bypassed = service.parametric_eq_snapshot()
        self.assertTrue(global_bypassed.global_bypass)
        before = service.parametric_eq_snapshot()
        self.assertFalse(service.set_parametric_eq_plan(({"band_id": "mid", "enabled": True, "frequency_hz": math.nan, "gain_db": 1.0, "q": 1.0},)).success)
        self.assertEqual(service.parametric_eq_snapshot(), before)
        self.assertTrue(service.reset_parametric_eq_to_flat().success)
        flat = service.parametric_eq_snapshot()
        self.assertTrue(flat.applied_plan.flat)
        self.assertFalse(flat.applied_plan.applied_enabled)

    def test_mode_isolation_ui_chain_and_m9_3_authority_are_preserved(self):
        app = qt_application()
        normal = make_service()
        formant = make_service(formant_lab=True)
        execution = make_service(transformation_execution_lab=True)
        stable = make_service(calibrate_lock_lab=True)
        eq = make_service(parametric_eq_lab=True)
        windows = []
        try:
            for service in (normal, formant, execution, stable, eq):
                windows.append(App(service))
            self.assertFalse(getattr(windows[0], "parametric_eq_enabled", False))
            self.assertFalse(getattr(windows[1], "parametric_eq_enabled", False))
            self.assertFalse(getattr(windows[2], "parametric_eq_enabled", False))
            self.assertFalse(getattr(windows[3], "parametric_eq_enabled", False))
            self.assertTrue(windows[4].parametric_eq_enabled)
            titles = [windows[4].tabs.tabText(i) for i in range(windows[4].tabs.count())]
            for title in ("Source Analysis", "Target Planner", "Plan Execution", "Calibrate & Lock", "Parametric EQ"):
                self.assertIn(title, titles)
        finally:
            for window in windows:
                window.close()
            app.processEvents()
        self.assertNotIn("Parametric EQ", normal.engine.effect_chain.effect_names())
        self.assertNotIn("Parametric EQ", stable.engine.effect_chain.effect_names())
        self.assertEqual(eq.engine.effect_chain.effect_names(), [
            "High-Pass",
            "Noise Gate",
            "Compressor",
            "Experimental Pitch/Formant",
            "Parametric EQ",
            "Robot",
            "Lowpass",
            "Gain",
            "Limiter",
        ])
        calibrate_and_lock(eq, source=ready_source(median_f0_hz=110.0), target=HIGHER_BRIGHTER_REFERENCE)
        locked = eq.stable_control_snapshot().locked
        eq.set_parametric_eq_band_gain("mid", 3.0)
        eq.return_to_suggested_plan()
        eq.return_transformation_to_neutral()
        self.assertEqual(eq.stable_control_snapshot().locked, locked)
        self.assertEqual(eq.parametric_eq_snapshot().applied_plan.bands[2].applied_gain_db, 3.0)
        eq.load_target_reference("lower_weightier")
        eq.lock_suggested_transformation()
        self.assertEqual(eq.parametric_eq_snapshot().applied_plan.bands[2].applied_gain_db, 3.0)

    def test_bounded_operations_lifecycle_and_no_persistence_mutation(self):
        service = make_service(parametric_eq_lab=True)
        preferences = service.operator_preferences()
        presets = service.custom_preset_names()
        for index in range(1000):
            band = PARAMETRIC_EQ_BAND_ORDER[index % len(PARAMETRIC_EQ_BAND_ORDER)]
            service.set_parametric_eq_band_gain(band, (index % 17) - 8)
            service.set_parametric_eq_band_frequency(band, 100.0 + (index % 5000))
            if band in {"low_mid", "mid", "presence"}:
                service.set_parametric_eq_band_q(band, 0.2 + (index % 8))
            if index % 13 == 0:
                service.set_parametric_eq_enabled(index % 26 == 0)
            if index % 17 == 0:
                service.reset_parametric_eq_to_flat()
        snapshot = service.parametric_eq_snapshot()
        self.assertEqual(service.parametric_eq_controller.retained_counts(), {"plans": 1, "coefficient_banks": 1, "transitions": 1})
        self.assertEqual(service.operator_preferences(), preferences)
        self.assertEqual(service.custom_preset_names(), presets)
        before = [t.name for t in threading.enumerate()]
        service.start_audio(0, 1)
        time.sleep(0.05)
        during = [t.name for t in threading.enumerate()]
        service.stop_audio()
        time.sleep(0.05)
        after = [t.name for t in threading.enumerate()]
        self.assertIn("VoiceLabSourceAnalysis", during)
        self.assertIn("TransformationExecutionController", during)
        self.assertEqual(before, after)
        self.assertIsInstance(snapshot.applied_plan.bands[0], ParametricEqBandParameters)

    def test_neutral_reset_transition_settles_and_reenable_flat_stays_truthful(self):
        service = make_service(parametric_eq_lab=True)
        service.set_parametric_eq_enabled(True)
        service.set_parametric_eq_band_gain("mid", 6.0)
        settle_parametric_eq(service)
        assert_eq_transition_settled(self, service, flat=False, local_bypass=False, processing_active=True)

        self.assertTrue(service.reset_parametric_eq_to_flat().success)
        progress = []
        output = []
        for _ in range(6):
            output.append(settle_parametric_eq(service, sine_mix(256), block=256, extra_blocks=0))
            progress.append(service.parametric_eq_snapshot().transition_progress)
        self.assertTrue(np.all(np.isfinite(np.concatenate(output))))
        self.assertGreater(max(progress), min(progress))
        snapshot = assert_eq_transition_settled(self, service, flat=True, local_bypass=True, processing_active=False)
        self.assertFalse(snapshot.applied_plan.applied_enabled)

        self.assertTrue(service.set_parametric_eq_enabled(True).success)
        settle_parametric_eq(service)
        assert_eq_transition_settled(self, service, flat=True, local_bypass=False, processing_active=False)

    def test_local_bypass_transitions_settle_preserve_settings_and_latest_wins(self):
        service = make_service(parametric_eq_lab=True)
        service.set_parametric_eq_enabled(True)
        service.set_parametric_eq_band_gain("presence", 4.0)
        settle_parametric_eq(service)
        before = service.parametric_eq_snapshot().applied_plan.bands[3]

        self.assertTrue(service.set_parametric_eq_bypassed(True).success)
        settle_parametric_eq(service)
        bypassed = assert_eq_transition_settled(self, service, flat=False, local_bypass=True, processing_active=False)
        self.assertEqual(bypassed.applied_plan.bands[3].applied_gain_db, before.applied_gain_db)

        self.assertTrue(service.set_parametric_eq_bypassed(False).success)
        settle_parametric_eq(service)
        active = assert_eq_transition_settled(self, service, flat=False, local_bypass=False, processing_active=True)
        self.assertEqual(active.applied_plan.bands[3].applied_gain_db, before.applied_gain_db)

        self.assertTrue(service.set_parametric_eq_band_gain("mid", 5.0).success)
        service.engine.process_voice(sine_mix(128), 128)
        self.assertTrue(service.parametric_eq_snapshot().transition_active)
        self.assertTrue(service.set_parametric_eq_bypassed(True).success)
        self.assertTrue(service.set_parametric_eq_bypassed(False).success)
        settle_parametric_eq(service)
        latest = assert_eq_transition_settled(self, service, flat=False, local_bypass=False, processing_active=True)
        self.assertEqual(latest.applied_plan.bands[2].applied_gain_db, 5.0)
        self.assertEqual(service.parametric_eq_controller.retained_counts(), {"plans": 1, "coefficient_banks": 1, "transitions": 1})

    def test_reset_and_reenable_supersede_active_transitions_without_stale_state(self):
        service = make_service(parametric_eq_lab=True)
        service.set_parametric_eq_enabled(True)
        service.set_parametric_eq_band_gain("low_shelf", 4.0)
        settle_parametric_eq(service)

        self.assertTrue(service.set_parametric_eq_band_gain("presence", 6.0).success)
        service.engine.process_voice(sine_mix(128), 128)
        self.assertTrue(service.parametric_eq_snapshot().transition_active)
        self.assertTrue(service.reset_parametric_eq_to_flat().success)
        settle_parametric_eq(service)
        flat = assert_eq_transition_settled(self, service, flat=True, local_bypass=True, processing_active=False)
        self.assertEqual(flat.applied_plan.active_band_count, 0)
        effect = parametric_eq_effect(service)
        self.assertIsNone(effect._transition_old)
        self.assertIsNone(effect._transition_new)

        service.set_parametric_eq_band_gain("mid", 3.0)
        service.set_parametric_eq_enabled(True)
        settle_parametric_eq(service)
        active = assert_eq_transition_settled(self, service, flat=False, local_bypass=False, processing_active=True)
        self.assertEqual(active.applied_plan.bands[2].applied_gain_db, 3.0)

    def test_global_bypass_pauses_transition_reporting_and_release_settles(self):
        service = make_service(parametric_eq_lab=True)
        service.set_parametric_eq_enabled(True)
        service.set_parametric_eq_band_gain("mid", 4.0)
        settle_parametric_eq(service)

        service.set_parametric_eq_band_gain("presence", 6.0)
        service.engine.process_voice(sine_mix(128), 128)
        self.assertTrue(service.parametric_eq_snapshot().transition_active)
        self.assertTrue(service.set_effects_bypassed(True).success)
        globally_bypassed = service.parametric_eq_snapshot()
        self.assertTrue(globally_bypassed.global_bypass)
        self.assertFalse(globally_bypassed.transition_active)
        self.assertTrue(globally_bypassed.transition_pending)
        self.assertFalse(globally_bypassed.processing_active)

        self.assertTrue(service.set_effects_bypassed(False).success)
        settle_parametric_eq(service)
        settled = assert_eq_transition_settled(self, service, flat=False, local_bypass=False, processing_active=True)
        self.assertEqual(settled.applied_plan.bands[3].applied_gain_db, 6.0)

    def test_stop_start_and_runtime_failure_clear_transition_state(self):
        service = make_service(parametric_eq_lab=True)
        service.set_parametric_eq_enabled(True)
        service.set_parametric_eq_band_gain("mid", 4.0)
        settle_parametric_eq(service)
        service.set_parametric_eq_band_gain("mid", -4.0)
        service.engine.process_voice(sine_mix(128), 128)
        self.assertTrue(service.parametric_eq_snapshot().transition_active)
        service.engine.stop()
        stopped = assert_eq_transition_settled(self, service, flat=False, local_bypass=False, processing_active=False)
        self.assertEqual(stopped.backend_health.backend_status, "active")
        settle_parametric_eq(service)
        assert_eq_transition_settled(self, service, flat=False, local_bypass=False, processing_active=True)

        service.set_parametric_eq_band_gain("presence", 5.0)
        service.engine.process_voice(sine_mix(128), 128)
        effect = parametric_eq_effect(service)

        class FailingPath:
            def process(self, source):
                raise RuntimeError("forced EQ transition failure")

        effect._transition_new = FailingPath()
        output = service.engine.process_voice(sine_mix(256), 256)
        self.assertTrue(np.all(np.isfinite(output)))
        failed = service.parametric_eq_snapshot()
        self.assertFalse(failed.transition_active)
        self.assertEqual(failed.backend_health.backend_status, "failed")
        self.assertTrue(failed.backend_health.failed)
        self.assertTrue(failed.local_bypass)
        service.engine.stop()
        settle_parametric_eq(service)
        recovered = service.parametric_eq_snapshot()
        self.assertEqual(recovered.backend_health.backend_status, "active")
        self.assertFalse(recovered.transition_active)

    def test_rapid_transition_mix_remains_bounded_without_stale_telemetry(self):
        service = make_service(parametric_eq_lab=True)
        service.set_parametric_eq_enabled(True)
        preferences = service.operator_preferences()
        presets = service.custom_preset_names()
        for index in range(1000):
            band = PARAMETRIC_EQ_BAND_ORDER[index % len(PARAMETRIC_EQ_BAND_ORDER)]
            self.assertTrue(service.set_parametric_eq_band_gain(band, (index % 13) - 6).success)
            self.assertTrue(service.set_parametric_eq_band_frequency(band, 100.0 + index).success)
            if band in {"low_mid", "mid", "presence"}:
                self.assertTrue(service.set_parametric_eq_band_q(band, 0.3 + (index % 50) / 10.0).success)
            if index % 31 == 0:
                self.assertTrue(service.set_parametric_eq_bypassed(index % 62 == 0).success)
            if index % 47 == 0:
                self.assertTrue(service.set_parametric_eq_enabled(index % 94 != 0).success)
            if index % 71 == 0:
                self.assertTrue(service.reset_parametric_eq_to_flat().success)
            if index % 97 == 0:
                service.set_effects_bypassed(True)
                service.set_effects_bypassed(False)
            if index % 113 == 0:
                service.engine.stop()
            service.engine.process_voice(sine_mix(128), 128)
        output = settle_parametric_eq(service)
        self.assertTrue(np.all(np.isfinite(output)))
        self.assertEqual(service.parametric_eq_controller.retained_counts(), {"plans": 1, "coefficient_banks": 1, "transitions": 1})
        self.assertFalse(service.parametric_eq_snapshot().transition_active)
        self.assertEqual(service.operator_preferences(), preferences)
        self.assertEqual(service.custom_preset_names(), presets)

    def test_graph_coordinate_helpers_are_logarithmic_and_reversible(self):
        app = qt_application()
        window = App(make_service(parametric_eq_lab=True))
        try:
            rect = window.parametric_eq_graph.plot_rect()
            if rect.width() <= 0:
                window.parametric_eq_graph.resize(900, 360)
                window.parametric_eq_graph.repaint()
                rect = window.parametric_eq_graph._current_plot_rect()
            for hz in (20, 60, 120, 300, 1000, 3000, 8000, 12000, 20000):
                mapped = x_to_frequency(frequency_to_x(hz, rect), rect)
                self.assertAlmostEqual(mapped, hz, delta=max(0.02, hz * 0.001))
            for gain in (-12, -6, 0, 6, 12):
                mapped = y_to_gain(gain_to_y(gain, rect), rect)
                self.assertAlmostEqual(mapped, gain, places=6)
            self.assertGreater(adjusted_q_from_wheel(1.0, 120), 1.0)
            self.assertLess(adjusted_q_from_wheel(1.0, -120), 1.0)
            self.assertLess(adjusted_q_from_wheel(1.0, 120, fine=True) - 1.0, adjusted_q_from_wheel(1.0, 120) - 1.0)
        finally:
            window.close()
            app.processEvents()

    def test_graph_editor_replaces_five_row_form_and_renders_offscreen(self):
        app = qt_application()
        service = make_service(parametric_eq_lab=True)
        window = App(service)
        try:
            self.assertTrue(hasattr(window, "parametric_eq_graph"))
            self.assertFalse(hasattr(window, "parametric_eq_band_widgets"))
            self.assertEqual(window.parametric_eq_graph.node_count(), 5)
            self.assertEqual(tuple(b.band_id for b in window.parametric_eq_graph.bands), PARAMETRIC_EQ_BAND_ORDER)
            self.assertFalse(window.parametric_eq_diagnostics.isChecked())
            self.assertEqual(window.parametric_eq_band_title.text(), "Mid Peak")
            pixmap = QPixmap(900, 420)
            window.parametric_eq_graph.resize(900, 360)
            window.parametric_eq_graph.render(pixmap)
            image = pixmap.toImage()
            colors = {
                image.pixelColor(x, y).rgb()
                for x in range(0, image.width(), 90)
                for y in range(0, image.height(), 70)
            }
            self.assertGreater(len(colors), 3)
            window.resize(720, 620)
            window.parametric_eq_graph.resize(620, 280)
            window.parametric_eq_graph.render(QPixmap(620, 280))
            window.resize(1280, 760)
            window.parametric_eq_graph.resize(1100, 420)
            window.parametric_eq_graph.render(QPixmap(1100, 420))
        finally:
            window.close()
            app.processEvents()

    def test_graph_drag_wheel_overlay_and_inspector_use_coarse_fine_accessible_steps(self):
        app = qt_application()
        service = make_service(parametric_eq_lab=True)
        window = App(service)
        try:
            graph = window.parametric_eq_graph
            graph.resize(900, 360)
            window.refresh_parametric_eq()
            window.select_parametric_eq_band("presence")
            rect = graph._current_plot_rect()

            graph._dragging = True
            graph.selected_band_id = "presence"
            coarse_point = QPointF(
                frequency_to_x(3026.0, rect),
                gain_to_y(2.26, rect),
            )
            graph.mouseMoveEvent(_FakeMouseEvent(coarse_point))
            band = service.parametric_eq_snapshot().applied_plan.bands[3]
            self.assertEqual(band.requested_frequency_hz, 3025.0)
            self.assertEqual(band.requested_gain_db, 2.5)
            self.assertIn("Coarse", graph._interaction_overlay)
            self.assertIn("+2.5 dB", graph._interaction_overlay)

            fine_point = QPointF(
                frequency_to_x(3026.0, rect),
                gain_to_y(2.26, rect),
            )
            graph.mouseMoveEvent(_FakeMouseEvent(fine_point, modifiers=Qt.ShiftModifier))
            band = service.parametric_eq_snapshot().applied_plan.bands[3]
            self.assertEqual(band.requested_frequency_hz, 3030.0)
            self.assertEqual(band.requested_gain_db, 2.3)
            self.assertIn("Fine", graph._interaction_overlay)
            graph.mouseReleaseEvent(_FakeMouseEvent(fine_point))

            window.set_parametric_eq_band_q_value("presence", 1.0)
            graph.wheelEvent(_FakeWheelEvent(120))
            band = service.parametric_eq_snapshot().applied_plan.bands[3]
            self.assertEqual(band.requested_q, 1.25)
            self.assertIn("Coarse", graph._interaction_overlay)

            window.set_parametric_eq_band_q_value("presence", 1.0)
            graph.wheelEvent(_FakeWheelEvent(120, modifiers=Qt.ShiftModifier))
            band = service.parametric_eq_snapshot().applied_plan.bands[3]
            self.assertEqual(band.requested_q, 1.05)
            self.assertIn("Fine", graph._interaction_overlay)

            window.select_parametric_eq_band("low_shelf")
            graph.wheelEvent(_FakeWheelEvent(120))
            shelf = service.parametric_eq_snapshot().applied_plan.bands[0]
            self.assertEqual(shelf.requested_q, 1.0)

            window.select_parametric_eq_band("presence")
            self.assertEqual(window.parametric_eq_gain.singleStep(), 0.5)
            self.assertEqual(window.parametric_eq_q.singleStep(), 0.25)
            self.assertEqual(window.parametric_eq_frequency.singleStep(), 25.0)
            window.parametric_eq_fine_steps.setChecked(True)
            self.assertEqual(window.parametric_eq_gain.singleStep(), 0.1)
            self.assertEqual(window.parametric_eq_q.singleStep(), 0.05)
            self.assertEqual(window.parametric_eq_frequency.singleStep(), 10.0)

            window.parametric_eq_gain.setValue(2.3)
            window.set_selected_parametric_eq_gain()
            self.assertEqual(service.parametric_eq_snapshot().applied_plan.bands[3].requested_gain_db, 2.3)
            window.parametric_eq_q.setValue(1.37)
            window.set_selected_parametric_eq_q()
            self.assertEqual(service.parametric_eq_snapshot().applied_plan.bands[3].requested_q, 1.37)
            self.assertIn("requested/applied", window.parametric_eq_band_state.text())
            self.assertIn("clamps f/g/q", window.parametric_eq_band_state.text())
        finally:
            window.close()
            app.processEvents()

    def test_graph_selection_drag_wheel_reset_and_visual_states_use_service(self):
        app = qt_application()
        service = make_service(parametric_eq_lab=True)
        window = App(service)
        try:
            graph = window.parametric_eq_graph
            graph.resize(900, 360)
            window.select_parametric_eq_band("presence")
            self.assertEqual(window.parametric_eq_selected_band_id, "presence")
            self.assertEqual(service.parametric_eq_visualization_snapshot().selected_band_id, "presence")
            window.drag_parametric_eq_band("presence", 30000.0, 9.0)
            band = service.parametric_eq_snapshot().applied_plan.bands[3]
            self.assertTrue(band.frequency_clamped)
            self.assertTrue(band.gain_clamped)
            self.assertEqual(band.applied_gain_db, 6.0)
            window.set_parametric_eq_band_q_value("presence", 2.5)
            self.assertEqual(service.parametric_eq_snapshot().applied_plan.bands[3].applied_q, 2.5)
            window.reset_parametric_eq_band("presence")
            self.assertEqual(service.parametric_eq_snapshot().applied_plan.bands[3].applied_gain_db, 0.0)
            service.set_parametric_eq_enabled(True)
            service.set_parametric_eq_band_gain("mid", 4.0)
            settle_parametric_eq(service)
            window.refresh_parametric_eq()
            self.assertIn("enabled", window.parametric_eq_status.text())
            service.set_parametric_eq_bypassed(True)
            window.refresh_parametric_eq()
            self.assertTrue(service.parametric_eq_visualization_snapshot().local_bypass)
            service.set_effects_bypassed(True)
            window.refresh_parametric_eq()
            self.assertTrue(service.parametric_eq_visualization_snapshot().global_bypass)
            effect = parametric_eq_effect(service)
            effect._runtime_status = dataclasses.replace(effect._runtime_status, failure_reason="forced display failure")
            service.parametric_eq_controller.record_runtime_status(effect._runtime_status)
            window.refresh_parametric_eq()
            self.assertEqual(service.parametric_eq_visualization_snapshot().backend_status, "failed")
        finally:
            window.close()
            app.processEvents()

    def test_prominent_ab_control_uses_local_bypass_and_preserves_plan(self):
        app = qt_application()
        service = make_service(parametric_eq_lab=True)
        window = App(service)
        try:
            self.assertEqual(window.parametric_eq_ab_on.text(), "EQ ON")
            self.assertEqual(window.parametric_eq_bypass.text(), "BYPASS")
            service.set_parametric_eq_enabled(True)
            service.set_parametric_eq_band_gain("mid", 4.0)
            service.set_parametric_eq_band_frequency("mid", 1200.0)
            settle_parametric_eq(service)
            window.refresh_parametric_eq()
            before = service.parametric_eq_snapshot().applied_plan.bands[2]

            window.set_parametric_eq_ab(True)
            bypassed = service.parametric_eq_snapshot()
            self.assertTrue(bypassed.local_bypass)
            self.assertTrue(bypassed.requested_plan.requested_bypassed)
            self.assertEqual(bypassed.applied_plan.bands[2].requested_gain_db, before.requested_gain_db)
            self.assertTrue(window.parametric_eq_bypass.isChecked())

            window.set_parametric_eq_ab(False)
            restored = service.parametric_eq_snapshot()
            self.assertFalse(restored.local_bypass)
            self.assertFalse(restored.requested_plan.requested_bypassed)
            self.assertEqual(restored.applied_plan.bands[2].requested_gain_db, before.requested_gain_db)
            self.assertTrue(window.parametric_eq_ab_on.isChecked())

            service.set_effects_bypassed(True)
            window.refresh_parametric_eq()
            self.assertTrue(service.parametric_eq_snapshot().global_bypass)
            self.assertFalse(service.parametric_eq_snapshot().requested_plan.requested_bypassed)
        finally:
            window.close()
            app.processEvents()

    def test_visualization_response_is_cached_immutable_and_matches_applied_bank(self):
        service = make_service(parametric_eq_lab=True)
        first = service.parametric_eq_visualization_snapshot()
        second = service.parametric_eq_visualization_snapshot()
        self.assertIs(first, second)
        self.assertIsInstance(first.frequency_hz, tuple)
        self.assertIsInstance(first.response_db, tuple)
        self.assertEqual(len(first.frequency_hz), 256)
        np.testing.assert_allclose(first.response_db, np.zeros(len(first.response_db)), atol=1e-9)
        service.set_parametric_eq_enabled(True)
        service.set_parametric_eq_band_gain("mid", 6.0)
        active = service.parametric_eq_visualization_snapshot()
        bank = service.parametric_eq_controller.coefficient_bank()
        expected = 20.0 * np.log10(np.maximum(np.abs(frequency_response(bank, active.frequency_hz)), 1.0e-12))
        np.testing.assert_allclose(active.response_db, expected, atol=1e-9)
        self.assertNotEqual(active.response_db, first.response_db)
        service.reset_parametric_eq_to_flat()
        flat = service.parametric_eq_visualization_snapshot()
        np.testing.assert_allclose(flat.response_db, np.zeros(len(flat.response_db)), atol=1e-9)
        self.assertEqual(service.parametric_eq_visualization_snapshot().coefficient_generation, flat.coefficient_generation)
        self.assertEqual(service.parametric_eq_controller.retained_counts(), {"plans": 1, "coefficient_banks": 1, "transitions": 1})

    def test_post_eq_spectrum_is_bounded_finite_and_has_no_callback_fft(self):
        source = inspect.getsource(parametric_eq_effect(make_service(parametric_eq_lab=True)).process)
        self.assertNotIn("fft", source.casefold())
        service = make_service(parametric_eq_lab=True)
        before_threads = [thread.name for thread in threading.enumerate()]
        self.assertTrue(service.set_parametric_eq_spectrum_mode("post-eq").success)
        t = np.arange(4096, dtype=np.float32) / SAMPLE_RATE
        sine = (0.5 * np.sin(2.0 * np.pi * 1000.0 * t)).astype(np.float32)
        for _ in range(8):
            service.parametric_eq_controller.publish_spectrum_frame(sine, SAMPLE_RATE)
            time.sleep(0.03)
        spectrum = service.parametric_eq_spectrum_snapshot()
        self.assertTrue(spectrum.active)
        self.assertEqual(spectrum.source_mode, "post-eq")
        self.assertEqual(spectrum.fft_size, 2048)
        self.assertGreater(spectrum.analysis_generation, 0)
        self.assertLessEqual(spectrum.capture_generation - spectrum.analysis_generation, spectrum.capture_generation)
        self.assertTrue(np.all(np.isfinite(np.array(spectrum.output_magnitude_db))))
        peak_hz = spectrum.frequency_hz[int(np.argmax(np.array(spectrum.output_magnitude_db)))]
        self.assertLess(abs(peak_hz - 1000.0), 80.0)
        service.parametric_eq_controller.publish_spectrum_frame(np.zeros(2048, dtype=np.float32), SAMPLE_RATE)
        time.sleep(0.06)
        silence = service.parametric_eq_spectrum_snapshot()
        self.assertTrue(np.all(np.array(silence.output_magnitude_db) <= 0.0))
        self.assertTrue(service.set_parametric_eq_spectrum_mode("off").success)
        time.sleep(0.05)
        after_threads = [thread.name for thread in threading.enumerate()]
        self.assertEqual(before_threads, after_threads)


if __name__ == "__main__":
    unittest.main()
