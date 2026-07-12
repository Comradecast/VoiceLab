import ast
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from voice_lab.app.service import ApplicationService
from voice_lab.config.input_processing import (
    CompressorSettings,
    HighPassSettings,
    LimiterSettings,
    NoiseGateSettings,
    validate_input_processing_document,
)
from voice_lab.config.service import ConfigurationService
from voice_lab.config.settings import validate_settings_document
from voice_lab.effects.input_processing import (
    CompressorEffect,
    HighPassFilterEffect,
    NoiseGateEffect,
    VoiceLimiterEffect,
    db_to_amplitude,
)
from voice_lab.engine.audio_engine import AudioEngine
from voice_lab.mixer import Mixer
from voice_lab.plugins import PluginManager
from voice_lab.tests.test_m6_3_device_failure_recovery import FakeHotkeys, FakeRouter, FakeSoundboard
from voice_lab.tests.test_m6_5_operator_settings import SettingsAudioIO
from voice_lab.tests.test_m7_2_custom_voice_management import PresetStore, SettingsStore


SAMPLE_RATE = 48000


def sine(frequency, seconds=0.5, amplitude=0.5):
    samples = int(SAMPLE_RATE * seconds)
    t = np.arange(samples, dtype=np.float32) / SAMPLE_RATE
    return (amplitude * np.sin(2.0 * np.pi * frequency * t)).astype(np.float32)


def rms(samples):
    data = np.asarray(samples, dtype=np.float64)
    return float(np.sqrt(np.mean(data * data)))


def make_service(settings=None, router=None, mixer=None):
    preset_store = PresetStore()
    settings_store = SettingsStore(settings)
    config = ConfigurationService(
        load_func=preset_store.load,
        save_func=preset_store.save,
        settings_load_func=settings_store.load,
        settings_save_func=settings_store.save,
    )
    svc = ApplicationService(
        config=config,
        plugins=PluginManager(),
        engine=AudioEngine(),
        mixer=mixer or Mixer(),
        audio_io=SettingsAudioIO(),
        router=router or FakeRouter(),
        hotkeys=FakeHotkeys(),
        soundboard=FakeSoundboard(),
    )
    return svc, preset_store, settings_store


class M80EffectContractTests(unittest.TestCase):
    def test_all_new_effects_are_transparent_when_disabled_and_preserve_contract(self):
        source = sine(440, seconds=0.05, amplitude=0.25)
        effects = (
            HighPassFilterEffect(HighPassSettings(enabled=False)),
            NoiseGateEffect(NoiseGateSettings(enabled=False)),
            CompressorEffect(CompressorSettings(enabled=False)),
            VoiceLimiterEffect(LimiterSettings(enabled=False)),
        )

        for effect in effects:
            with self.subTest(effect=effect.name):
                original = source.copy()
                output = effect.process(source, len(source), SAMPLE_RATE)
                self.assertEqual(output.shape, source.shape)
                self.assertEqual(output.dtype, np.float32)
                np.testing.assert_allclose(output, source, atol=1e-7)
                np.testing.assert_allclose(source, original, atol=0.0)
                self.assertTrue(np.all(np.isfinite(output)))

    def test_invalid_audio_values_are_sanitized_to_finite_output(self):
        source = np.array([0.0, np.nan, np.inf, -np.inf, 0.1], dtype=np.float32)
        effects = (
            HighPassFilterEffect(HighPassSettings(enabled=True)),
            NoiseGateEffect(NoiseGateSettings(enabled=True)),
            CompressorEffect(CompressorSettings(enabled=True)),
            VoiceLimiterEffect(LimiterSettings(enabled=True)),
        )

        for effect in effects:
            with self.subTest(effect=effect.name):
                output = effect.process(source, len(source), SAMPLE_RATE)
                self.assertTrue(np.all(np.isfinite(output)))
                self.assertEqual(output.shape, source.shape)

    def test_block_processing_is_deterministic_after_reset(self):
        source = sine(220, seconds=0.2, amplitude=0.4)
        effects = (
            HighPassFilterEffect(HighPassSettings(enabled=True, cutoff_hz=100)),
            NoiseGateEffect(NoiseGateSettings(enabled=True, threshold_dbfs=-35, release_ms=90)),
            CompressorEffect(CompressorSettings(enabled=True, threshold_dbfs=-24, ratio=4, attack_ms=5, release_ms=80)),
            VoiceLimiterEffect(LimiterSettings(enabled=True, ceiling_dbfs=-6, release_ms=50)),
        )

        for effect in effects:
            with self.subTest(effect=effect.name):
                first = np.concatenate(
                    [
                        effect.process(source[:2048], 2048, SAMPLE_RATE),
                        effect.process(source[2048:], len(source) - 2048, SAMPLE_RATE),
                    ]
                )
                effect.reset()
                second = np.concatenate(
                    [
                        effect.process(source[:2048], 2048, SAMPLE_RATE),
                        effect.process(source[2048:], len(source) - 2048, SAMPLE_RATE),
                    ]
                )
                np.testing.assert_allclose(first, second, atol=1e-7)


class M80HighPassTests(unittest.TestCase):
    def test_low_frequency_is_attenuated_and_passband_is_preserved(self):
        effect = HighPassFilterEffect(HighPassSettings(enabled=True, cutoff_hz=120))
        low = effect.process(sine(30, seconds=1.0, amplitude=0.5), SAMPLE_RATE, SAMPLE_RATE)
        effect.reset()
        high_source = sine(1000, seconds=1.0, amplitude=0.5)
        high = effect.process(high_source, SAMPLE_RATE, SAMPLE_RATE)

        self.assertLess(rms(low[-SAMPLE_RATE // 2:]), 0.18)
        self.assertGreater(rms(high[-SAMPLE_RATE // 2:]), rms(high_source[-SAMPLE_RATE // 2:]) * 0.85)

    def test_dc_decays_and_state_continues_across_blocks(self):
        effect = HighPassFilterEffect(HighPassSettings(enabled=True, cutoff_hz=80))
        dc = np.ones(SAMPLE_RATE, dtype=np.float32) * 0.25
        first = effect.process(dc[:1024], 1024, SAMPLE_RATE)
        second = effect.process(dc[1024:2048], 1024, SAMPLE_RATE)
        self.assertLess(abs(float(second[-1])), abs(float(first[0])))

    def test_cutoff_boundary_validation(self):
        good, issues = validate_input_processing_document(
            {"high_pass": {"enabled": True, "cutoff_hz": 40}}
        )
        bad, bad_issues = validate_input_processing_document(
            {"high_pass": {"enabled": True, "cutoff_hz": 20}}
        )
        self.assertFalse(issues)
        self.assertEqual(good.high_pass.cutoff_hz, 40)
        self.assertTrue(bad_issues)
        self.assertEqual(bad.high_pass.cutoff_hz, 80)


class M80GateTests(unittest.TestCase):
    def test_below_threshold_attenuates_and_above_threshold_passes(self):
        effect = NoiseGateEffect(NoiseGateSettings(enabled=True, threshold_dbfs=-35, release_ms=40))
        quiet = np.ones(SAMPLE_RATE, dtype=np.float32) * db_to_amplitude(-55)
        quiet_out = effect.process(quiet, len(quiet), SAMPLE_RATE)
        effect.reset()
        loud = np.ones(SAMPLE_RATE // 4, dtype=np.float32) * db_to_amplitude(-20)
        loud_out = effect.process(loud, len(loud), SAMPLE_RATE)

        self.assertLess(rms(quiet_out[-SAMPLE_RATE // 4:]), rms(quiet[-SAMPLE_RATE // 4:]) * 0.2)
        self.assertGreater(rms(loud_out[-1000:]), rms(loud[-1000:]) * 0.95)

    def test_attack_release_and_cross_block_continuity(self):
        effect = NoiseGateEffect(NoiseGateSettings(enabled=True, threshold_dbfs=-35, release_ms=100))
        loud = np.ones(2048, dtype=np.float32) * db_to_amplitude(-20)
        quiet = np.ones(4096, dtype=np.float32) * db_to_amplitude(-60)
        loud_out = effect.process(loud, len(loud), SAMPLE_RATE)
        quiet_out = effect.process(quiet, len(quiet), SAMPLE_RATE)

        self.assertGreater(abs(float(loud_out[-1])), abs(float(quiet_out[-1])))
        self.assertLess(abs(float(quiet_out[-1] - quiet_out[-2])), 0.01)

    def test_gate_validation_boundaries(self):
        valid, issues = validate_input_processing_document(
            {"noise_gate": {"threshold_dbfs": -70, "release_ms": 1000}}
        )
        invalid, invalid_issues = validate_input_processing_document(
            {"noise_gate": {"threshold_dbfs": -90, "release_ms": 10}}
        )
        self.assertFalse(issues)
        self.assertEqual(valid.noise_gate.threshold_dbfs, -70)
        self.assertTrue(invalid_issues)
        self.assertEqual(invalid.noise_gate.threshold_dbfs, -45)
        self.assertEqual(invalid.noise_gate.release_ms, 180)


class M80CompressorTests(unittest.TestCase):
    def test_below_threshold_unity_and_makeup_gain(self):
        source = np.ones(SAMPLE_RATE // 2, dtype=np.float32) * db_to_amplitude(-30)
        unity = CompressorEffect(CompressorSettings(enabled=True, threshold_dbfs=-18, makeup_gain_db=0))
        makeup = CompressorEffect(CompressorSettings(enabled=True, threshold_dbfs=-18, makeup_gain_db=6))

        unity_out = unity.process(source, len(source), SAMPLE_RATE)
        makeup_out = makeup.process(source, len(source), SAMPLE_RATE)

        self.assertAlmostEqual(rms(unity_out[-1000:]), rms(source[-1000:]), delta=0.002)
        self.assertAlmostEqual(rms(makeup_out[-1000:]), rms(source[-1000:]) * db_to_amplitude(6), delta=0.01)

    def test_above_threshold_ratio_and_envelope_smoothing(self):
        source = np.ones(SAMPLE_RATE, dtype=np.float32) * db_to_amplitude(-6)
        effect = CompressorEffect(
            CompressorSettings(enabled=True, threshold_dbfs=-18, ratio=3, attack_ms=5, release_ms=80)
        )
        output = effect.process(source, len(source), SAMPLE_RATE)
        expected_peak = db_to_amplitude(-18 + ((-6 + 18) / 3))

        self.assertAlmostEqual(float(np.max(np.abs(output[-1000:]))), expected_peak, delta=0.03)
        self.assertGreater(abs(float(output[10])), abs(float(output[-1])))

    def test_compressor_validation_boundaries(self):
        valid, issues = validate_input_processing_document(
            {"compressor": {"threshold_dbfs": -40, "ratio": 10, "attack_ms": 1, "release_ms": 20, "makeup_gain_db": 12}}
        )
        invalid, invalid_issues = validate_input_processing_document(
            {"compressor": {"threshold_dbfs": -50, "ratio": 11, "attack_ms": 0, "release_ms": 10, "makeup_gain_db": 13}}
        )
        self.assertFalse(issues)
        self.assertEqual(valid.compressor.ratio, 10)
        self.assertTrue(invalid_issues)
        self.assertEqual(invalid.compressor.threshold_dbfs, -18)
        self.assertEqual(invalid.compressor.ratio, 3)


class M80LimiterTests(unittest.TestCase):
    def test_peak_ceiling_release_and_no_gain_increase(self):
        effect = VoiceLimiterEffect(LimiterSettings(enabled=True, ceiling_dbfs=-6, release_ms=40))
        loud = np.ones(SAMPLE_RATE // 4, dtype=np.float32) * 0.9
        safe = np.ones(SAMPLE_RATE // 4, dtype=np.float32) * 0.1
        loud_out = effect.process(loud, len(loud), SAMPLE_RATE)
        safe_out = effect.process(safe, len(safe), SAMPLE_RATE)
        ceiling = db_to_amplitude(-6)

        self.assertLessEqual(float(np.max(np.abs(loud_out))), ceiling + 1e-6)
        self.assertLessEqual(float(np.max(np.abs(safe_out))), 0.1 + 1e-6)

    def test_limiter_validation_boundaries(self):
        valid, issues = validate_input_processing_document(
            {"limiter": {"ceiling_dbfs": -12, "release_ms": 500}}
        )
        invalid, invalid_issues = validate_input_processing_document(
            {"limiter": {"ceiling_dbfs": 0, "release_ms": 10}}
        )
        self.assertFalse(issues)
        self.assertEqual(valid.limiter.ceiling_dbfs, -12)
        self.assertTrue(invalid_issues)
        self.assertEqual(invalid.limiter.ceiling_dbfs, -1)


class M80ChainAndServiceTests(unittest.TestCase):
    def test_exact_chain_order_and_character_order_are_stable(self):
        engine = AudioEngine()
        chain = PluginManager().load_default_effect_chain(engine)
        self.assertEqual(
            chain.effect_names(),
            ["High-Pass", "Noise Gate", "Compressor", "Pitch Shift", "Robot", "Lowpass", "Gain", "Limiter"],
        )
        self.assertEqual(chain.effect_names()[3:7], ["Pitch Shift", "Robot", "Lowpass", "Gain"])

    def test_disabled_processors_reproduce_existing_zero_effect_path(self):
        svc, _presets, _settings = make_service()
        source = sine(440, seconds=0.1, amplitude=0.2)
        svc.apply_effect_parameters(1.0, 0.0, 8000, False, 0.35, 0.7, pitch=0, mark_custom=False)
        output = svc.engine.process_voice(source, len(source))
        self.assertEqual(output.shape, source.shape)
        self.assertTrue(np.all(np.isfinite(output)))

    def test_settings_round_trip_and_legacy_load(self):
        legacy = validate_settings_document({"schema_version": 1})
        self.assertFalse(legacy.issues)
        self.assertFalse(legacy.settings.input_processing.high_pass.enabled)

        configured = validate_settings_document(
            {
                "schema_version": 1,
                "input_processing": {
                    "high_pass": {"enabled": True, "cutoff_hz": 120},
                    "noise_gate": {"enabled": True, "threshold_dbfs": -50, "release_ms": 250},
                    "compressor": {
                        "enabled": True,
                        "threshold_dbfs": -20,
                        "ratio": 4,
                        "attack_ms": 12,
                        "release_ms": 180,
                        "makeup_gain_db": 3,
                    },
                    "limiter": {"enabled": True, "ceiling_dbfs": -2, "release_ms": 90},
                },
            }
        )
        self.assertFalse(configured.issues)
        self.assertEqual(configured.settings.input_processing.high_pass.cutoff_hz, 120)
        self.assertTrue(configured.settings.input_processing.limiter.enabled)

    def test_service_update_reset_and_launch_stopped_preserve_voice_and_route(self):
        router = FakeRouter()
        svc, _presets, settings = make_service(router=router)
        svc.select_preset("Luke Deep")
        svc.start_audio(0, 1, 2)
        before_voice = svc.active_voice_state()
        result = svc.update_input_processing("high_pass", enabled=True, cutoff_hz=140)
        reset = svc.reset_input_processing()
        svc.save_configuration()

        self.assertTrue(result.success)
        self.assertTrue(reset.success)
        self.assertEqual(svc.active_voice_state()["custom_preset"], before_voice["custom_preset"])
        self.assertEqual(router.starts, [(0, 1, 2)])
        self.assertFalse(settings.document["input_processing"]["high_pass"]["enabled"])

    def test_presets_do_not_own_input_processing(self):
        svc, store, _settings = make_service()
        svc.update_input_processing("compressor", enabled=True, threshold_dbfs=-20, ratio=4, attack_ms=10, release_ms=100, makeup_gain_db=2)
        result = svc.save_custom_voice("M8 Custom", {"gain": 10, "robot": 0, "lowpass": 4000, "pitch": 0}, overwrite=True)
        self.assertTrue(result.success)
        self.assertNotIn("input_processing", store.presets["M8 Custom"])

    def test_mixer_receives_processed_voice_after_limiter_and_soundboard_stays_out_of_processed_meter(self):
        svc, _presets, _settings = make_service()
        svc.update_input_processing("limiter", enabled=True, ceiling_dbfs=-12, release_ms=20)
        input_audio = np.ones(128, dtype=np.float32) * 0.9
        voice = svc.engine.process_voice(input_audio, len(input_audio))
        svc.mixer.queue_sound(np.ones(128, dtype=np.float32) * 0.5)
        buses = svc.mixer.mix(voice, len(voice))

        self.assertLessEqual(float(np.max(np.abs(voice))), db_to_amplitude(-12) + 1e-6)
        self.assertGreater(float(np.max(np.abs(buses.main_bus.samples))), float(np.max(np.abs(voice))))

    def test_bypass_uses_actual_bypassed_path_and_does_not_clear_settings(self):
        svc, _presets, _settings = make_service()
        svc.update_input_processing("limiter", enabled=True, ceiling_dbfs=-12, release_ms=20)
        source = np.ones(128, dtype=np.float32) * 0.9
        processed = svc.engine.process_voice(source, len(source))
        svc.set_effects_bypassed(True)
        bypassed = svc.engine.process_voice(source, len(source))

        self.assertLess(float(np.max(np.abs(processed))), 0.9)
        np.testing.assert_allclose(bypassed, source, atol=1e-7)
        self.assertTrue(svc.current_input_processing.limiter.enabled)


class M80UiAndArchitectureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        cls.qt_app = QApplication.instance() or QApplication([])

    def test_offscreen_main_window_smoke_and_reset_cancel(self):
        from voice_lab.ui.main_window import App
        from PySide6.QtWidgets import QMessageBox

        svc, _store, _settings = make_service()
        window = App(svc, on_close=lambda: None)
        self.addCleanup(window.close)
        self.qt_app.processEvents()

        svc.update_input_processing("high_pass", enabled=True, cutoff_hz=100)
        window.sync_input_processing_from_service()
        with patch("voice_lab.ui.main_window.QMessageBox.question", return_value=QMessageBox.Cancel):
            window.reset_input_processing()

        self.assertTrue(svc.current_input_processing.high_pass.enabled)
        self.assertEqual(svc.current_input_processing.high_pass.cutoff_hz, 100)

    def test_ui_prohibited_imports_include_m8_dsp_boundaries(self):
        tree = ast.parse(Path("voice_lab/ui/main_window.py").read_text())
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
        prohibited = (
            "json",
            "sounddevice",
            "voice_lab.engine",
            "voice_lab.effects",
            "voice_lab.plugins",
            "voice_lab.io.audio_io",
            "voice_lab.io.router",
            "voice_lab.config.settings",
            "voice_lab.config.input_processing",
            "numpy",
        )
        self.assertFalse(any(name.startswith(prohibited) for name in imports))

    def test_router_mixer_and_callback_sources_do_not_own_m8_effects_or_io(self):
        router = Path("voice_lab/io/router.py").read_text()
        mixer = Path("voice_lab/mixer/mixer.py").read_text()
        levels = Path("voice_lab/audio_levels.py").read_text()
        for source in (router, mixer):
            self.assertNotIn("HighPass", source)
            self.assertNotIn("NoiseGate", source)
            self.assertNotIn("CompressorEffect", source)
            self.assertNotIn("LimiterEffect", source)
        self.assertNotIn("save_settings", router)
        self.assertNotIn("query_devices", levels)

    def test_bounded_repeated_processing_keeps_fixed_state_shape_and_finite_output(self):
        effect = CompressorEffect(
            CompressorSettings(enabled=True, threshold_dbfs=-24, ratio=3, attack_ms=10, release_ms=100)
        )
        source = sine(440, seconds=0.02, amplitude=0.4)
        state_keys = set(effect.__dict__)
        for _ in range(500):
            output = effect.process(source, len(source), SAMPLE_RATE)
            self.assertEqual(output.shape, source.shape)
            self.assertTrue(np.all(np.isfinite(output)))
            self.assertEqual(set(effect.__dict__), state_keys)


class M80LiveCorrectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        cls.qt_app = QApplication.instance() or QApplication([])

    def test_service_enabled_state_reaches_active_effect_chain_and_updates_live(self):
        svc, _store, _settings = make_service()
        status = svc.engine.effect_chain.status()
        self.assertIn("High-Pass", status.disabled_effects)

        result = svc.update_input_processing("high_pass", enabled=True, cutoff_hz=200)
        status = svc.engine.effect_chain.status()

        self.assertTrue(result.success)
        self.assertNotIn("High-Pass", status.disabled_effects)
        self.assertIn("High-Pass", status.active_effects)
        self.assertEqual(svc.engine.input_processing.high_pass.cutoff_hz, 200)

        svc.update_input_processing("high_pass", enabled=True, cutoff_hz=120)
        self.assertEqual(svc.engine.input_processing.high_pass.cutoff_hz, 120)

    def test_enabled_processors_measurably_change_diagnostic_inputs_and_bypass_restores_dry_path(self):
        svc, _store, _settings = make_service()
        source = np.ones(512, dtype=np.float32) * 0.9
        svc.update_input_processing("limiter", enabled=True, ceiling_dbfs=-12, release_ms=100)
        processed = svc.engine.process_voice(source, len(source))

        svc.set_effects_bypassed(True)
        bypassed = svc.engine.process_voice(source, len(source))
        bypass_activity = svc.input_processing_activity()
        svc.set_effects_bypassed(False)
        restored = svc.engine.process_voice(source, len(source))

        self.assertLess(float(np.max(np.abs(processed))), 0.3)
        np.testing.assert_allclose(bypassed, source, atol=1e-7)
        self.assertTrue(bypass_activity["bypassed"])
        self.assertTrue(bypass_activity["limiter"]["bypassed"])
        self.assertLess(float(np.max(np.abs(restored))), 0.3)
        self.assertTrue(svc.current_input_processing.limiter.enabled)

    def test_activity_snapshot_is_latest_finite_bounded_and_resets_on_stop(self):
        svc, _store, _settings = make_service()
        svc.update_input_processing("noise_gate", enabled=True, threshold_dbfs=-25, release_ms=100)
        quiet = np.ones(48000, dtype=np.float32) * db_to_amplitude(-45)
        svc.engine.process_voice(quiet, len(quiet))
        first = svc.input_processing_activity()
        keys = set(svc.engine.effect_chain.effects[1].__dict__)

        svc.engine.process_voice(quiet, len(quiet))
        second = svc.input_processing_activity()
        svc.stop_audio()
        stopped = svc.input_processing_activity()

        self.assertEqual(set(svc.engine.effect_chain.effects[1].__dict__), keys)
        self.assertEqual(first["noise_gate"]["state"], "Reducing")
        self.assertGreater(first["noise_gate"]["gain_reduction_db"], 10.0)
        self.assertTrue(np.isfinite(second["noise_gate"]["gain_reduction_db"]))
        self.assertEqual(stopped["noise_gate"]["state"], "Ready")

    def test_compressor_and_limiter_activity_correspond_to_signal_behavior(self):
        svc, _store, _settings = make_service()
        loud = np.ones(48000, dtype=np.float32) * db_to_amplitude(-10)
        svc.update_input_processing(
            "compressor",
            enabled=True,
            threshold_dbfs=-35,
            ratio=10,
            attack_ms=2,
            release_ms=250,
            makeup_gain_db=0,
        )
        svc.engine.process_voice(loud, len(loud))
        compressor = svc.input_processing_activity()["compressor"]

        svc.update_input_processing(
            "compressor",
            enabled=False,
            threshold_dbfs=-35,
            ratio=10,
            attack_ms=2,
            release_ms=250,
            makeup_gain_db=0,
        )
        svc.update_input_processing("limiter", enabled=True, ceiling_dbfs=-12, release_ms=100)
        svc.engine.process_voice(np.ones(512, dtype=np.float32) * 0.9, 512)
        limiter = svc.input_processing_activity()["limiter"]

        self.assertEqual(compressor["state"], "Reducing")
        self.assertGreater(compressor["gain_reduction_db"], 10.0)
        self.assertEqual(limiter["state"], "Limiting")
        self.assertTrue(limiter["ceiling_hit"])

    def test_tabbed_layout_and_processor_controls_are_reachable_without_global_checkbox(self):
        from voice_lab.ui.main_window import App

        svc, _store, _settings = make_service()
        window = App(svc, on_close=lambda: None)
        self.addCleanup(window.close)
        window.show()
        self.qt_app.processEvents()

        tab_names = [window.tabs.tabText(index) for index in range(window.tabs.count())]

        self.assertEqual(tab_names, ["Voice", "Input Processing", "Routing", "Soundboard", "Diagnostics"])
        self.assertFalse(hasattr(window, "input_processing_toggle"))
        self.assertTrue(window.start_button.isVisible())
        self.assertTrue(window.stop_button.isVisible())
        self.assertTrue(window.bypass_check.isVisible())
        for processor, controls in window.input_processing_controls.items():
            self.assertIn("enabled", controls)
            self.assertIn("status", controls)
            self.assertTrue(controls["status"].text().startswith("State:"))
            controls["enabled"].setChecked(False)
            window._set_input_processing_params_enabled(processor)
            self.assertTrue(all(not slider.isEnabled() for slider in controls["params"].values()))

    def test_programmatic_input_processing_refresh_does_not_write_settings(self):
        svc, _store, settings = make_service()
        from voice_lab.ui.main_window import App

        window = App(svc, on_close=lambda: None)
        self.addCleanup(window.close)
        before = len(settings.saved)
        window.sync_input_processing_from_service()

        self.assertEqual(len(settings.saved), before)


if __name__ == "__main__":
    unittest.main()
