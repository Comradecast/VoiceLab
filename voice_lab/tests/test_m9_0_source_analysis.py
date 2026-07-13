import ast
import math
import os
import time
import unittest
from pathlib import Path

import numpy as np
from PySide6.QtWidgets import QApplication

from voice_lab.analysis import (
    ANALYSIS_CADENCE_HZ,
    F0_MAX_HZ,
    F0_MIN_HZ,
    MAX_PROFILE_READINGS,
    SourceAnalysisTap,
    SourceVoiceAnalyzer,
    VoiceAnalysisSnapshot,
    analyze_source_voice,
)
from voice_lab.app.service import ApplicationService
from voice_lab.config.service import ConfigurationService
from voice_lab.core import AudioContext, AudioFrame
from voice_lab.engine.audio_engine import AudioEngine
from voice_lab.mixer import Mixer
from voice_lab.plugins import PluginManager
from voice_lab.ui.main_window import App
from voice_lab.tests.test_m6_3_device_failure_recovery import FakeHotkeys, FakeRouter, FakeSoundboard
from voice_lab.tests.test_m6_5_operator_settings import SettingsAudioIO
from voice_lab.tests.test_m7_2_custom_voice_management import PresetStore, SettingsStore


SAMPLE_RATE = 48000


def qt_application():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def make_service(voice_analysis_lab=False, formant_lab=False):
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
        voice_analysis_lab=voice_analysis_lab,
    )


def sine(frequency, seconds=0.16, amplitude=0.3, phase=0.0, sample_rate=SAMPLE_RATE):
    t = np.arange(int(sample_rate * seconds), dtype=np.float64) / sample_rate
    return (amplitude * np.sin(2.0 * np.pi * frequency * t + phase)).astype(np.float32)


def band_limited_noise(low_hz, high_hz, seconds=0.18, amplitude=0.2):
    rng = np.random.default_rng(1234)
    samples = rng.normal(0.0, 1.0, int(SAMPLE_RATE * seconds))
    spectrum = np.fft.rfft(samples)
    freqs = np.fft.rfftfreq(samples.size, 1.0 / SAMPLE_RATE)
    mask = (freqs >= low_hz) & (freqs <= high_hz)
    spectrum[~mask] = 0.0
    filtered = np.fft.irfft(spectrum, samples.size)
    filtered = filtered / max(float(np.max(np.abs(filtered))), 1e-12)
    return (filtered * amplitude).astype(np.float32)


def vowel_like_signal(f0=140.0, formants=(520.0, 1550.0, 2550.0), seconds=0.18):
    t = np.arange(int(SAMPLE_RATE * seconds), dtype=np.float64) / SAMPLE_RATE
    signal = np.zeros_like(t)
    max_harmonic = int((SAMPLE_RATE / 2.0) // f0)
    for harmonic in range(1, max_harmonic):
        frequency = f0 * harmonic
        envelope = sum(math.exp(-0.5 * ((frequency - center) / 120.0) ** 2.0) for center in formants)
        signal += (envelope / max(1.0, harmonic**0.4)) * np.sin(2.0 * np.pi * frequency * t)
    signal = signal / max(float(np.max(np.abs(signal))), 1e-12)
    return (0.3 * signal).astype(np.float32)


def frame(samples, block_index=0):
    context = AudioContext(
        sample_rate=SAMPLE_RATE,
        block_size=len(samples),
        frame_count=len(samples),
        sample_format="float32",
        input_channel_count=1,
        output_channel_count=2,
        block_index=block_index,
        processing_stage="capture",
    )
    return AudioFrame(
        samples=np.asarray(samples, dtype=np.float32),
        sample_rate=SAMPLE_RATE,
        channel_count=1,
        frame_count=len(samples),
        sample_format="float32",
        block_index=block_index,
        context=context,
    )


class M90SourceAnalyzerContractTests(unittest.TestCase):
    def test_input_contract_sanitizes_without_modifying_source_and_returns_scalars(self):
        source = np.array([0.0, np.nan, np.inf, -np.inf, 0.25, -0.25], dtype=np.float32)
        original = source.copy()

        reading = analyze_source_voice(source, SAMPLE_RATE, captured_at=1.0)

        np.testing.assert_array_equal(source, original)
        self.assertTrue(np.isfinite(reading.rms_dbfs))
        self.assertTrue(np.isfinite(reading.peak_dbfs))
        self.assertIsNone(reading.f0_hz)
        for key, value in reading.asdict().items():
            self.assertFalse(isinstance(value, np.ndarray), key)

    def test_silence_low_level_noise_and_out_of_range_pitch_are_not_voiced(self):
        cases = (
            np.zeros(4096, dtype=np.float32),
            sine(120, amplitude=0.0001),
            band_limited_noise(200.0, 6000.0),
            sine(40.0),
            sine(800.0),
        )
        for samples in cases:
            with self.subTest(case=float(np.max(np.abs(samples))) if samples.size else 0.0):
                reading = analyze_source_voice(samples, SAMPLE_RATE)
                self.assertFalse(reading.voiced)
                self.assertIsNone(reading.f0_hz)

    def test_supported_channel_and_dtype_behavior_is_deterministic(self):
        mono = sine(180.0)
        stereo = np.column_stack((mono, mono * 0.5)).astype(np.float32)
        first = analyze_source_voice(stereo, SAMPLE_RATE)
        second = analyze_source_voice(stereo, SAMPLE_RATE)

        self.assertTrue(first.voiced)
        self.assertAlmostEqual(first.f0_hz, second.f0_hz, places=6)
        self.assertAlmostEqual(first.f0_confidence, second.f0_confidence, places=6)

    def test_snapshot_contract_is_immutable_and_exposes_no_arrays(self):
        analyzer = SourceVoiceAnalyzer()
        snapshot = analyzer.snapshot()

        self.assertIsInstance(snapshot, VoiceAnalysisSnapshot)
        with self.assertRaises(Exception):
            snapshot.status.active = True
        self.assertNotIn(np.ndarray, {type(value) for value in snapshot.asdict()["status"].values()})

    def test_start_stop_reset_and_stale_snapshot(self):
        analyzer = SourceVoiceAnalyzer(sleep_seconds=0.001)
        analyzer.start()
        analyzer.tap.publish(frame(sine(140.0)))
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and analyzer.snapshot().status.analyzed_frame_count == 0:
            time.sleep(0.01)
        self.assertGreaterEqual(analyzer.snapshot().status.analyzed_frame_count, 1)

        analyzer.reset()
        self.assertEqual(analyzer.snapshot().status.retained_reading_count, 0)
        analyzer.stop()
        snapshot = analyzer.snapshot()
        self.assertFalse(snapshot.status.active)
        self.assertFalse(snapshot.status.worker_running)


class M90F0AndProfileTests(unittest.TestCase):
    def test_f0_estimator_tracks_practical_speech_range(self):
        for frequency in (70, 85, 100, 120, 140, 180, 220, 300, 400):
            with self.subTest(frequency=frequency):
                reading = analyze_source_voice(sine(frequency), SAMPLE_RATE)
                cents = 1200.0 * math.log2(reading.f0_hz / frequency)
                self.assertTrue(reading.voiced)
                self.assertLess(abs(reading.f0_hz - frequency), 1.0)
                self.assertLess(abs(cents), 20.0)
                self.assertGreater(reading.f0_confidence, 0.80)

    def test_f0_amplitude_phase_harmonics_and_missing_fundamental(self):
        base = analyze_source_voice(sine(140.0, amplitude=0.1), SAMPLE_RATE)
        loud = analyze_source_voice(sine(140.0, amplitude=0.5, phase=1.25), SAMPLE_RATE)
        t = np.arange(int(SAMPLE_RATE * 0.16), dtype=np.float64) / SAMPLE_RATE
        harmonic = (
            0.2 * np.sin(2 * np.pi * 140 * t)
            + 0.15 * np.sin(2 * np.pi * 280 * t)
            + 0.1 * np.sin(2 * np.pi * 420 * t)
        ).astype(np.float32)
        missing = (
            0.18 * np.sin(2 * np.pi * 280 * t)
            + 0.12 * np.sin(2 * np.pi * 420 * t)
            + 0.08 * np.sin(2 * np.pi * 560 * t)
        ).astype(np.float32)

        self.assertLess(abs(base.f0_hz - loud.f0_hz), 1.0)
        self.assertLess(abs(analyze_source_voice(harmonic, SAMPLE_RATE).f0_hz - 140.0), 1.0)
        self.assertLess(abs(analyze_source_voice(missing, SAMPLE_RATE).f0_hz - 140.0), 2.0)

    def test_profile_excludes_invalid_frames_caps_storage_and_resets(self):
        analyzer = SourceVoiceAnalyzer()
        for index, frequency in enumerate([100.0, 120.0, 140.0, 180.0] * 70):
            reading = analyze_source_voice(sine(frequency, seconds=0.12), SAMPLE_RATE)
            analyzer._readings.append(reading)
            if index % 5 == 0:
                analyzer._readings.append(analyze_source_voice(np.zeros(4096, dtype=np.float32), SAMPLE_RATE))
        analyzer._refresh_snapshot(active=True)
        profile = analyzer.snapshot().profile

        self.assertLessEqual(profile.voiced_frame_count, MAX_PROFILE_READINGS)
        self.assertTrue(profile.ready)
        self.assertAlmostEqual(profile.median_f0_hz, 130.0, delta=12.0)
        self.assertGreater(profile.upper_f0_hz, profile.lower_f0_hz)
        self.assertGreater(profile.pitch_span_semitones, 0.0)
        analyzer.reset()
        self.assertEqual(analyzer.snapshot().profile.voiced_frame_count, 0)


class M90SpectralAndResonanceTests(unittest.TestCase):
    def test_spectral_band_ratios_follow_energy_placement_and_amplitude_scale(self):
        chest = analyze_source_voice(sine(140.0), SAMPLE_RATE)
        low_mid = analyze_source_voice(sine(600.0), SAMPLE_RATE)
        presence = analyze_source_voice(sine(3000.0), SAMPLE_RATE)
        bright = analyze_source_voice(sine(6500.0), SAMPLE_RATE)
        sibilance = analyze_source_voice(band_limited_noise(5500.0, 9500.0), SAMPLE_RATE)
        scaled = analyze_source_voice(sine(140.0, amplitude=0.15), SAMPLE_RATE)

        self.assertGreater(chest.chest_energy_ratio, low_mid.chest_energy_ratio)
        self.assertGreater(low_mid.low_mid_energy_ratio, chest.low_mid_energy_ratio)
        self.assertGreater(presence.presence_energy_ratio, chest.presence_energy_ratio)
        self.assertGreater(bright.brightness_energy_ratio, chest.brightness_energy_ratio)
        self.assertGreater(sibilance.sibilance_energy_ratio, chest.sibilance_energy_ratio)
        self.assertAlmostEqual(chest.chest_energy_ratio, scaled.chest_energy_ratio, delta=0.02)

    def test_spectral_tilt_orders_dark_neutral_and_bright_signals(self):
        dark = analyze_source_voice(sine(140.0), SAMPLE_RATE)
        neutral = analyze_source_voice(sine(140.0) + sine(2500.0, amplitude=0.08), SAMPLE_RATE)
        bright = analyze_source_voice(sine(140.0) + sine(6500.0, amplitude=0.18), SAMPLE_RATE)

        self.assertTrue(dark.spectral_valid)
        self.assertLess(dark.spectral_tilt_db, neutral.spectral_tilt_db)
        self.assertLess(neutral.spectral_tilt_db, bright.spectral_tilt_db)
        self.assertIsNone(analyze_source_voice(np.zeros(4096, dtype=np.float32), SAMPLE_RATE).spectral_tilt_db)

    def test_resonance_estimates_shift_with_vowel_like_envelope_and_are_invalid_on_noise(self):
        low = analyze_source_voice(vowel_like_signal(formants=(500.0, 1400.0, 2500.0)), SAMPLE_RATE)
        high = analyze_source_voice(vowel_like_signal(formants=(700.0, 1900.0, 3100.0)), SAMPLE_RATE)
        noise = analyze_source_voice(band_limited_noise(100.0, 8000.0), SAMPLE_RATE)

        self.assertTrue(low.resonance_valid)
        self.assertTrue(high.resonance_valid)
        self.assertGreater(high.f1_hz, low.f1_hz)
        self.assertGreater(high.f2_hz, low.f2_hz)
        self.assertFalse(noise.resonance_valid)


class M90TransportIsolationAndUITests(unittest.TestCase):
    def test_tap_is_fixed_capacity_newest_wins_and_counts_drops_without_waiting(self):
        clock = {"now": 0.0}
        tap = SourceAnalysisTap(cadence_hz=20.0, clock=lambda: clock["now"])
        tap.start()
        first = frame(np.ones(16, dtype=np.float32) * 0.1, block_index=1)
        second = frame(np.ones(16, dtype=np.float32) * 0.2, block_index=2)
        self.assertTrue(tap.publish(first))
        clock["now"] += 0.10
        self.assertTrue(tap.publish(second))
        latest = tap.take_latest()

        self.assertEqual(tap.dropped_frame_count, 1)
        self.assertEqual(latest.frame_count, second.frame_count)
        self.assertAlmostEqual(float(latest.samples[0]), 0.2, places=6)
        self.assertIsNone(tap.take_latest())

    def test_tap_cadence_skips_callback_frames_without_growth(self):
        clock = {"now": 0.0}
        tap = SourceAnalysisTap(cadence_hz=ANALYSIS_CADENCE_HZ, clock=lambda: clock["now"])
        tap.start()
        self.assertTrue(tap.publish(frame(sine(100.0, seconds=0.01))))
        for _ in range(10):
            clock["now"] += 0.001
            tap.publish(frame(sine(100.0, seconds=0.01)))
        self.assertEqual(tap.skipped_frame_count, 10)
        self.assertIsNotNone(tap.take_latest())
        self.assertIsNone(tap.take_latest())

    def test_service_and_ui_gate_keep_normal_launch_unexposed(self):
        app = qt_application()
        normal = make_service(voice_analysis_lab=False)
        analysis = make_service(voice_analysis_lab=True)
        normal_window = App(normal)
        analysis_window = App(analysis)
        try:
            self.assertIsNone(normal.source_analysis_snapshot())
            self.assertIsNotNone(analysis.source_analysis_snapshot())
            self.assertFalse(normal_window.source_analysis_enabled)
            self.assertTrue(analysis_window.source_analysis_enabled)
            titles = [
                analysis_window.tabs.tabText(i)
                for i in range(analysis_window.tabs.count())
            ]
            self.assertIn("Source Analysis", titles)
        finally:
            normal_window.close()
            analysis_window.close()
            app.processEvents()

    def test_normal_and_prototype_chains_are_unchanged_and_analyzer_is_not_a_plugin(self):
        normal = make_service()
        analysis = make_service(voice_analysis_lab=True)
        formant = make_service(formant_lab=True)

        production = ["High-Pass", "Noise Gate", "Compressor", "Pitch Shift", "Robot", "Lowpass", "Gain", "Limiter"]
        prototype = [
            "High-Pass",
            "Noise Gate",
            "Compressor",
            "Experimental Pitch/Formant",
            "Robot",
            "Lowpass",
            "Gain",
            "Limiter",
        ]
        self.assertEqual(normal.engine.effect_chain.effect_names(), production)
        self.assertEqual(analysis.engine.effect_chain.effect_names(), production)
        self.assertEqual(formant.engine.effect_chain.effect_names(), prototype)
        self.assertNotIn("Source", " ".join(analysis.engine.effect_chain.effect_names()))

    def test_analysis_enabled_does_not_change_deterministic_audio_output_or_persistence(self):
        normal = make_service()
        analysis = make_service(voice_analysis_lab=True)
        source = frame(sine(220.0, seconds=0.02))

        normal_output = normal.engine.process_voice(source)
        analysis_output = analysis.engine.process_voice(source)

        np.testing.assert_allclose(analysis_output.samples, normal_output.samples, atol=0.0)
        self.assertEqual(normal.operator_preferences(), analysis.operator_preferences())
        self.assertEqual(normal.custom_preset_names(), analysis.custom_preset_names())

    def test_callback_source_boundary_has_no_analysis_work_or_unbounded_queue(self):
        router_source = Path("voice_lab/io/router.py").read_text()
        analysis_source = Path("voice_lab/analysis/source_voice.py").read_text()
        callback_source = router_source[router_source.index("def main_callback") :]

        self.assertIn("analysis_tap.publish(input_frame)", callback_source)
        self.assertNotIn("analyze_source_voice", callback_source)
        self.assertNotIn("fft", callback_source.casefold())
        self.assertNotIn("correlate", callback_source)
        self.assertNotIn("put(", callback_source)
        self.assertNotIn("Queue(", analysis_source)
        self.assertIn("deque(maxlen=MAX_PROFILE_READINGS)", analysis_source)
        self.assertNotIn("PySide6", analysis_source)
        self.assertNotIn("open(", analysis_source)
        self.assertNotIn("query_devices", analysis_source)

    def test_ui_imports_stay_behind_service_boundary(self):
        tree = ast.parse(Path("voice_lab/ui/main_window.py").read_text())
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
        prohibited = (
            "voice_lab.analysis",
            "voice_lab.effects",
            "voice_lab.engine",
            "voice_lab.io",
            "voice_lab.config.settings",
            "numpy",
            "scipy",
        )
        self.assertFalse(any(name.startswith(prohibited) for name in imports))

    def test_documented_range_constants(self):
        self.assertEqual(F0_MIN_HZ, 60.0)
        self.assertEqual(F0_MAX_HZ, 500.0)


if __name__ == "__main__":
    unittest.main()
