import math
import os
import unittest

import numpy as np
from PySide6.QtWidgets import QApplication

from voice_lab.app.service import ApplicationService
from voice_lab.config.service import ConfigurationService
from voice_lab.effects.formant_lab import (
    ExperimentalPitchFormantEffect,
    FormantLabState,
    formant_factor,
    formant_lab_parameters,
    validate_formant_semitones,
)
from voice_lab.effects.signalsmith_backend import SignalsmithPitchBackend, signalsmith_status
from voice_lab.engine.audio_engine import AudioEngine
from voice_lab.mixer import Mixer
from voice_lab.plugins import PluginManager
from voice_lab.ui.main_window import App
from voice_lab.tests.test_m6_3_device_failure_recovery import FakeHotkeys, FakeRouter, FakeSoundboard
from voice_lab.tests.test_m6_5_operator_settings import SettingsAudioIO
from voice_lab.tests.test_m7_2_custom_voice_management import PresetStore, SettingsStore


SAMPLE_RATE = 48000
BLOCK_SIZE = 480


def make_service(formant_lab=False):
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
        formant_lab=formant_lab,
    )


def vowel_like_signal(f0=140.0, seconds=1.2):
    samples = int(SAMPLE_RATE * seconds)
    t = np.arange(samples, dtype=np.float64) / SAMPLE_RATE
    signal = np.zeros(samples, dtype=np.float64)
    centers = (520.0, 1550.0, 2550.0)
    widths = (100.0, 180.0, 260.0)
    max_harmonic = int((SAMPLE_RATE / 2.0) // f0)
    for harmonic in range(1, max_harmonic):
        frequency = f0 * harmonic
        envelope = sum(
            math.exp(-0.5 * ((frequency - center) / width) ** 2.0)
            for center, width in zip(centers, widths)
        )
        signal += (envelope / (harmonic**0.35)) * np.sin(2.0 * np.pi * frequency * t)
    return (0.25 * signal / np.max(np.abs(signal))).astype(np.float32)


def process_prototype(source, pitch=0.0, formant=0.0):
    state = FormantLabState()
    state.replace(formant_lab_parameters(pitch_semitones=pitch, formant_semitones=formant))
    effect = ExperimentalPitchFormantEffect(state)
    blocks = []
    for start in range(0, source.shape[0], BLOCK_SIZE):
        block = source[start : start + BLOCK_SIZE]
        blocks.append(effect.process(block, block.shape[0], SAMPLE_RATE))
    output = np.concatenate(blocks)
    return output[BLOCK_SIZE * 12 :], effect


def estimate_f0(samples, low_hz=90.0, high_hz=220.0):
    data = np.asarray(samples[:16000], dtype=np.float64)
    data -= np.mean(data)
    fft_size = 1 << (2 * data.shape[0] - 1).bit_length()
    spectrum = np.fft.rfft(data, fft_size)
    corr = np.fft.irfft(spectrum * np.conj(spectrum), fft_size)[: data.shape[0]]
    low_lag = int(SAMPLE_RATE / high_hz)
    high_lag = int(SAMPLE_RATE / low_hz)
    lag = low_lag + int(np.argmax(corr[low_lag:high_lag]))
    return SAMPLE_RATE / lag


def spectral_centroid(samples, low_hz, high_hz):
    data = np.asarray(samples, dtype=np.float64)
    window = np.hanning(data.shape[0])
    spectrum = np.abs(np.fft.rfft(data * window))
    freqs = np.fft.rfftfreq(data.shape[0], 1.0 / SAMPLE_RATE)
    mask = (freqs >= low_hz) & (freqs <= high_hz)
    weights = spectrum[mask] + 1e-12
    return float(np.sum(freqs[mask] * weights) / np.sum(weights))


def formant_effect(service):
    for effect in service.engine.effect_chain.effects:
        if getattr(effect, "name", "") == "Experimental Pitch/Formant":
            return effect
    raise AssertionError("Experimental Pitch/Formant effect not found")


def qt_application():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


class ChangingSnapshotState:
    def __init__(self):
        self.snapshots = (
            formant_lab_parameters(pitch_semitones=-4.0, formant_semitones=-4.0),
            formant_lab_parameters(pitch_semitones=4.0, formant_semitones=4.0),
        )
        self.read_count = 0

    @property
    def parameters(self):
        snapshot = self.snapshots[min(self.read_count, len(self.snapshots) - 1)]
        self.read_count += 1
        return snapshot


@unittest.skipUnless(signalsmith_status().available, signalsmith_status().reason)
class M81SignalsmithFormantBackendTests(unittest.TestCase):
    def test_native_and_python_wrappers_expose_formant_controls(self):
        backend = SignalsmithPitchBackend(SAMPLE_RATE, BLOCK_SIZE, channels=1)

        self.assertTrue(hasattr(backend, "set_formant_semitones"))
        self.assertTrue(hasattr(backend, "set_formant_factor"))
        backend.set_formant_semitones(4.0)
        backend.set_formant_factor(formant_factor(-4.0))

    def test_formant_factor_validation_is_bounded_and_deterministic(self):
        self.assertEqual(validate_formant_semitones(-12), -12.0)
        self.assertEqual(validate_formant_semitones(12), 12.0)
        self.assertAlmostEqual(formant_factor(12), 2.0)
        self.assertAlmostEqual(formant_factor(-12), 0.5)
        with self.assertRaises(ValueError):
            validate_formant_semitones(12.5)
        with self.assertRaises(ValueError):
            validate_formant_semitones(float("nan"))

    def test_formant_only_shift_preserves_f0_while_moving_spectral_envelope(self):
        source = vowel_like_signal()
        neutral, _neutral_effect = process_prototype(source, formant=0.0)
        down, _down_effect = process_prototype(source, formant=-4.0)
        up, up_effect = process_prototype(source, formant=4.0)

        neutral_f0 = estimate_f0(neutral)
        self.assertLess(abs(estimate_f0(down) - neutral_f0), 1.0)
        self.assertLess(abs(estimate_f0(up) - neutral_f0), 1.0)
        self.assertLess(
            spectral_centroid(down, 300.0, 900.0),
            spectral_centroid(neutral, 300.0, 900.0) * 0.95,
        )
        self.assertGreater(
            spectral_centroid(up, 300.0, 900.0),
            spectral_centroid(neutral, 300.0, 900.0) * 1.05,
        )
        status = up_effect.status().asdict()
        self.assertTrue(status["active"])
        self.assertEqual(status["backend"], "signalsmith")
        self.assertAlmostEqual(status["formant_factor"], formant_factor(4.0))

    def test_pitch_and_formant_parameters_share_one_streaming_backend(self):
        source = vowel_like_signal(seconds=0.3)
        state = FormantLabState()
        effect = ExperimentalPitchFormantEffect(state)
        first = effect.process(source[:BLOCK_SIZE], BLOCK_SIZE, SAMPLE_RATE)
        state.replace(formant_lab_parameters(pitch_semitones=4.0, formant_semitones=-4.0))
        second = effect.process(source[BLOCK_SIZE : BLOCK_SIZE * 2], BLOCK_SIZE, SAMPLE_RATE)

        self.assertEqual(first.shape, (BLOCK_SIZE,))
        self.assertEqual(second.shape, (BLOCK_SIZE,))
        self.assertTrue(np.all(np.isfinite(first)))
        self.assertTrue(np.all(np.isfinite(second)))
        status = effect.status().asdict()
        self.assertEqual(status["last_stable_pitch"], 4.0)
        self.assertEqual(status["last_stable_formant"], -4.0)
        self.assertGreater(status["latency_frames"], 0)

    def test_effect_reads_one_whole_snapshot_per_processing_block(self):
        source = vowel_like_signal(seconds=0.05)[:BLOCK_SIZE]
        state = ChangingSnapshotState()
        effect = ExperimentalPitchFormantEffect(state)

        effect.process(source, BLOCK_SIZE, SAMPLE_RATE)

        self.assertEqual(state.read_count, 1)
        status = effect.status().asdict()
        self.assertEqual(status["last_stable_pitch"], -4.0)
        self.assertEqual(status["last_stable_formant"], -4.0)

    def test_coordinated_updates_replace_complete_logical_configuration(self):
        source = vowel_like_signal(seconds=0.1)
        state = FormantLabState()
        effect = ExperimentalPitchFormantEffect(state)
        first = formant_lab_parameters(pitch_semitones=-4.0, formant_semitones=-4.0)
        second = formant_lab_parameters(pitch_semitones=4.0, formant_semitones=4.0)

        state.replace(first)
        effect.process(source[:BLOCK_SIZE], BLOCK_SIZE, SAMPLE_RATE)
        state.replace(second)
        effect.process(source[BLOCK_SIZE : BLOCK_SIZE * 2], BLOCK_SIZE, SAMPLE_RATE)

        self.assertEqual(effect.status().last_stable_pitch, 4.0)
        self.assertEqual(effect.status().last_stable_formant, 4.0)


class M81IsolationAndServiceTests(unittest.TestCase):
    def test_normal_effect_chain_remains_production_order(self):
        engine = AudioEngine()
        chain = PluginManager().load_default_effect_chain(engine)

        self.assertEqual(
            chain.effect_names(),
            ["High-Pass", "Noise Gate", "Compressor", "Pitch Shift", "Robot", "Lowpass", "Gain", "Limiter"],
        )
        self.assertNotIn("Experimental Pitch/Formant", chain.effect_names())

    def test_formant_lab_chain_replaces_only_the_pitch_stage(self):
        engine = AudioEngine()
        chain = PluginManager().load_default_effect_chain(engine, formant_lab=True)

        self.assertEqual(
            chain.effect_names(),
            [
                "High-Pass",
                "Noise Gate",
                "Compressor",
                "Experimental Pitch/Formant",
                "Robot",
                "Lowpass",
                "Gain",
                "Limiter",
            ],
        )

    def test_service_gate_keeps_normal_launch_unexposed(self):
        normal = make_service(formant_lab=False)
        prototype = make_service(formant_lab=True)

        self.assertIsNone(normal.formant_lab_state())
        self.assertIsNotNone(prototype.formant_lab_state())
        self.assertNotIn("Experimental Pitch/Formant", normal.engine.effect_chain.effect_names())
        self.assertIn("Experimental Pitch/Formant", prototype.engine.effect_chain.effect_names())

    def test_service_update_reset_and_validation_are_session_only(self):
        service = make_service(formant_lab=True)

        result = service.update_formant_lab(pitch_semitones=4.0, formant_semitones=-4.0, bypassed=True)
        self.assertTrue(result.success)
        state = result.metadata["formant_lab"]
        self.assertEqual(state["pitch_semitones"], 4.0)
        self.assertEqual(state["formant_semitones"], -4.0)
        self.assertTrue(state["bypassed"])

        invalid = service.update_formant_lab(formant_semitones=13.0)
        self.assertFalse(invalid.success)
        reset = service.reset_formant_lab()
        self.assertTrue(reset.success)
        self.assertEqual(reset.metadata["formant_lab"]["pitch_semitones"], 0.0)
        self.assertEqual(reset.metadata["formant_lab"]["formant_semitones"], 0.0)
        self.assertFalse(reset.metadata["formant_lab"]["bypassed"])

    def test_prototype_bypass_preserves_complete_snapshot_and_resumes_values(self):
        service = make_service(formant_lab=True)
        service.update_formant_lab(pitch_semitones=2.0, formant_semitones=1.0, bypassed=False)
        bypassed = service.update_formant_lab(bypassed=True)
        resumed = service.update_formant_lab(bypassed=False)

        self.assertEqual(bypassed.metadata["formant_lab"]["pitch_semitones"], 2.0)
        self.assertEqual(bypassed.metadata["formant_lab"]["formant_semitones"], 1.0)
        self.assertTrue(bypassed.metadata["formant_lab"]["bypassed"])
        self.assertEqual(resumed.metadata["formant_lab"]["pitch_semitones"], 2.0)
        self.assertEqual(resumed.metadata["formant_lab"]["formant_semitones"], 1.0)
        self.assertFalse(resumed.metadata["formant_lab"]["bypassed"])

    def test_normal_bypass_does_not_erase_formant_lab_values(self):
        service = make_service(formant_lab=True)
        service.update_formant_lab(pitch_semitones=-2.0, formant_semitones=1.5)

        service.set_effects_bypassed(True)
        service.set_effects_bypassed(False)

        state = service.formant_lab_state()
        self.assertEqual(state["pitch_semitones"], -2.0)
        self.assertEqual(state["formant_semitones"], 1.5)

    def test_stop_clears_native_adapter_while_session_values_remain(self):
        service = make_service(formant_lab=True)
        service.update_formant_lab(pitch_semitones=2.0, formant_semitones=-1.0)
        effect = formant_effect(service)
        source = vowel_like_signal(seconds=0.05)[:BLOCK_SIZE]
        effect.process(source, BLOCK_SIZE, SAMPLE_RATE)
        self.assertIsNotNone(effect._adapter)

        service.stop_audio()

        self.assertIsNone(effect._adapter)
        state = service.formant_lab_state()
        self.assertEqual(state["pitch_semitones"], 2.0)
        self.assertEqual(state["formant_semitones"], -1.0)

    def test_reset_prototype_restores_defaults_without_touching_operator_state(self):
        service = make_service(formant_lab=True)
        original_input_processing = service.input_processing_state()
        original_devices = service.devices()
        original_monitor = service.current_monitor_enabled
        original_monitor_volume = service.current_monitor_volume
        original_soundboard_volume = service.current_soundboard_volume
        original_voice = service.active_voice_state()
        service.update_formant_lab(enabled=False, pitch_semitones=3.0, formant_semitones=-2.0, bypassed=True)

        result = service.reset_formant_lab()

        self.assertTrue(result.success)
        state = result.metadata["formant_lab"]
        self.assertTrue(service.engine.formant_lab.enabled)
        self.assertTrue(state["available"])
        self.assertFalse(state["bypassed"])
        self.assertEqual(state["pitch_semitones"], 0.0)
        self.assertEqual(state["formant_semitones"], 0.0)
        self.assertEqual(service.input_processing_state(), original_input_processing)
        self.assertEqual(service.devices(), original_devices)
        self.assertEqual(service.current_monitor_enabled, original_monitor)
        self.assertEqual(service.current_monitor_volume, original_monitor_volume)
        self.assertEqual(service.current_soundboard_volume, original_soundboard_volume)
        self.assertEqual(service.active_voice_state()["parameters"], original_voice["parameters"])

    def test_mode_isolation_for_launch_state_chain_and_ui(self):
        app = qt_application()
        normal = make_service(formant_lab=False)
        prototype = make_service(formant_lab=True)
        normal_window = App(normal)
        prototype_window = App(prototype)
        try:
            self.assertEqual(normal._processing_state, "stopped")
            self.assertEqual(prototype._processing_state, "stopped")
            self.assertFalse(normal_window.formant_lab_enabled)
            self.assertFalse(hasattr(normal_window, "formant_lab_formant"))
            self.assertTrue(prototype_window.formant_lab_enabled)
            self.assertTrue(hasattr(prototype_window, "formant_lab_formant"))
            self.assertNotIn("Experimental Pitch/Formant", normal.engine.effect_chain.effect_names())
            self.assertNotIn("Pitch Shift", prototype.engine.effect_chain.effect_names())
        finally:
            normal_window.close()
            prototype_window.close()
            app.processEvents()

    def test_formant_validation_rejects_non_finite_and_wrong_types(self):
        invalid_values = (
            float("nan"),
            float("inf"),
            float("-inf"),
            "1.0",
            object(),
            True,
            13.0,
            -13.0,
        )
        for value in invalid_values:
            with self.subTest(value=repr(value)):
                with self.assertRaises(ValueError):
                    validate_formant_semitones(value)
                result = make_service(formant_lab=True).update_formant_lab(formant_semitones=value)
                self.assertFalse(result.success)


if __name__ == "__main__":
    unittest.main()
