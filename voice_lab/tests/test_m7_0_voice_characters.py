import ast
import math
import os
import unittest
from pathlib import Path

import numpy as np

from voice_lab.app.commands import CommandResult
from voice_lab.app.operator_status import build_operator_status
from voice_lab.app.service import ApplicationService
from voice_lab.config.service import ConfigurationService
from voice_lab.config.settings import validate_settings_document
from voice_lab.config.voice_characters import (
    BUILT_IN_CHARACTERS,
    NATURAL_CHARACTER_ID,
    character_by_compatibility_preset,
    character_by_id,
    protected_voice_names,
    resolve_character_parameters,
    validate_character_catalog,
)
from voice_lab.core import AudioContext, AudioFrame
from voice_lab.effects.chain import EffectChain
from voice_lab.engine.audio_engine import AudioEngine
from voice_lab.plugins import PluginManager
from voice_lab.telemetry import TelemetryService
from voice_lab.tests.test_m6_1_operator_visibility import snapshot
from voice_lab.tests.test_m6_3_device_failure_recovery import FakeHotkeys, FakeRouter, FakeSoundboard
from voice_lab.tests.test_m6_5_operator_settings import SettingsAudioIO


PRESETS = {
    "Natural": {"gain": 10, "robot": 0, "lowpass": 4000, "pitch": 0},
    "Deep Voice": {"gain": 9, "robot": 0, "lowpass": 2200, "pitch": -4},
    "High Voice": {"gain": 9, "robot": 0, "lowpass": 6500, "pitch": 4},
    "Clean": {"gain": 10, "robot": 0, "lowpass": 4000, "pitch": 0},
    "Luke Deep": {"gain": 11, "robot": 5, "lowpass": 2500, "pitch": -3},
}


def config(settings=None, saved=None):
    return ConfigurationService(
        load_func=lambda: dict(saved or PRESETS),
        save_func=lambda presets: None,
        settings_load_func=lambda: validate_settings_document(settings or {"schema_version": 1}),
        settings_save_func=lambda settings: None,
    )


def service(settings=None, engine=None, router=None):
    return ApplicationService(
        telemetry=TelemetryService(),
        config=config(settings=settings),
        plugins=PluginManager(),
        engine=engine or AudioEngine(),
        audio_io=SettingsAudioIO(),
        router=router or FakeRouter(),
        hotkeys=FakeHotkeys(),
        soundboard=FakeSoundboard(),
    )


class M70CharacterCatalogTests(unittest.TestCase):
    def test_required_characters_are_unique_and_valid(self):
        self.assertTrue(validate_character_catalog())
        ids = [character.id for character in BUILT_IN_CHARACTERS]
        names = [character.display_name for character in BUILT_IN_CHARACTERS]

        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(
            set(names),
            {"Natural", "Deep", "Heavy Bass", "Higher", "Robot", "Radio", "Muffled"},
        )

    def test_character_definitions_are_immutable_and_aliases_resolve(self):
        character = character_by_id("deep")
        with self.assertRaises(Exception):
            character.id = "changed"

        self.assertEqual(character_by_compatibility_preset("Deep Voice").id, "deep")
        self.assertEqual(character_by_compatibility_preset("High Voice").id, "higher")
        self.assertIn("Robot", protected_voice_names())

    def test_all_targets_validate_and_unknown_character_fails(self):
        for character in BUILT_IN_CHARACTERS:
            preset, effect = resolve_character_parameters(character.id, 100)
            self.assertIn("gain", preset)
            self.assertIsNotNone(effect.gain)

        with self.assertRaises(ValueError):
            resolve_character_parameters("telephone", 100)

    def test_ui_does_not_own_character_parameter_maps(self):
        source = Path("voice_lab/ui/main_window.py").read_text()
        self.assertNotIn("Heavy Bass", source)
        self.assertNotIn('"pitch": -6', source)


class M70StrengthResolverTests(unittest.TestCase):
    def test_zero_equals_natural_and_hundred_equals_target(self):
        natural, _ = resolve_character_parameters("deep", 0)
        target, _ = resolve_character_parameters("deep", 100)

        self.assertEqual(natural, {"gain": 10, "robot": 0, "lowpass": 4000, "pitch": 0})
        self.assertEqual(target, {"gain": 9, "robot": 0, "lowpass": 2200, "pitch": -4})

    def test_midpoint_interpolation_is_deterministic(self):
        midpoint, effect = resolve_character_parameters("robot", 50)

        self.assertEqual(midpoint["gain"], 11)
        self.assertEqual(midpoint["robot"], 50)
        self.assertEqual(midpoint["pitch"], 0)
        self.assertEqual(midpoint["lowpass"], 4000)
        self.assertEqual(effect.robot, 0.5)

    def test_lowpass_log_interpolation_for_deep(self):
        midpoint, _ = resolve_character_parameters("deep", 50)
        expected = int(round(math.exp(math.log(4000) + (math.log(2200) - math.log(4000)) * 0.5)))

        self.assertEqual(midpoint["lowpass"], expected)

    def test_invalid_strength_is_rejected(self):
        for value in (-1, 101, math.nan, math.inf):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    resolve_character_parameters("deep", value)

    def test_natural_strength_has_no_effect(self):
        zero, _ = resolve_character_parameters("natural", 0)
        hundred, _ = resolve_character_parameters("natural", 100)

        self.assertEqual(zero, hundred)


class M70ServiceBehaviorTests(unittest.TestCase):
    def test_selecting_character_applies_parameters_without_starting_audio(self):
        svc = service()
        result = svc.select_voice_character("deep", strength=75)

        self.assertTrue(result.success)
        self.assertEqual(svc.current_character_id, "deep")
        self.assertEqual(svc.current_character_strength, 75)
        self.assertEqual(svc.current_effect_params["pitch"], -3)
        self.assertEqual(svc.operator_status().processing, "Stopped")

    def test_character_change_while_running_does_not_restart_routing(self):
        router = FakeRouter()
        svc = service(router=router)
        self.assertTrue(svc.start_audio(0, 1).success)

        self.assertTrue(svc.select_voice_character("higher").success)

        self.assertEqual(router.starts, [(0, 1, None)])
        self.assertEqual(svc.operator_status().processing, "Running")

    def test_strength_change_applies_live_and_does_not_mark_custom(self):
        svc = service()
        svc.select_voice_character("deep", strength=25)

        result = svc.set_character_strength(50)

        self.assertTrue(result.success)
        self.assertEqual(svc.active_voice_state()["kind"], "character")
        self.assertIn("Deep", svc.active_voice_state()["text"])

    def test_manual_advanced_change_marks_unsaved_custom(self):
        svc = service()
        svc.select_voice_character("deep")

        svc.apply_effect_parameters(1.2, 0.0, 2200, False, 0.35, 0.7, pitch=-4)

        self.assertEqual(svc.active_voice_state()["kind"], "unsaved")
        self.assertIn("Unsaved", svc.active_voice_state()["text"])

    def test_selecting_custom_preset_marks_custom(self):
        svc = service()
        result = svc.select_preset("Luke Deep")

        self.assertTrue(result.success)
        self.assertEqual(svc.active_voice_state()["kind"], "custom")
        self.assertIn("Luke Deep", svc.active_voice_state()["text"])

    def test_invalid_character_leaves_prior_state_intact(self):
        svc = service()
        svc.select_voice_character("deep")

        result = svc.select_voice_character("unknown")

        self.assertFalse(result.success)
        self.assertEqual(svc.current_character_id, "deep")

    def test_reset_selects_natural_turns_bypass_off_and_preserves_volume(self):
        svc = service()
        svc.apply_effect_parameters(1.0, 0.0, 4000, True, 0.22, 0.44, pitch=0, mark_custom=False)
        svc.select_voice_character("robot")
        svc.set_effects_bypassed(True)

        result = svc.reset_voice()

        self.assertTrue(result.success)
        self.assertEqual(svc.current_character_id, NATURAL_CHARACTER_ID)
        self.assertFalse(svc.effects_bypassed)
        self.assertTrue(svc.current_monitor_enabled)
        self.assertEqual(svc.current_monitor_volume, 0.22)
        self.assertEqual(svc.current_soundboard_volume, 0.44)

    def test_built_in_voice_cannot_be_saved_or_deleted(self):
        svc = service()

        self.assertFalse(svc.save_preset("Deep", {"gain": 10, "robot": 0, "lowpass": 4000, "pitch": 0}).success)
        self.assertFalse(svc.delete_preset("Robot").success)

    def test_character_state_is_projected_through_operator_status(self):
        svc = service()
        svc.select_voice_character("radio", strength=100)

        status = svc.operator_status()

        self.assertIn("Radio", status.active_voice)
        self.assertEqual(status.diagnostics["active_voice_character_id"], "radio")


class M70BypassTests(unittest.TestCase):
    def test_bypass_defaults_off_and_does_not_persist(self):
        svc = service(settings={"schema_version": 1, "selected_character_id": "deep", "character_strength": 75})

        self.assertFalse(svc.effects_bypassed)
        self.assertFalse(svc.active_voice_state()["effects_bypassed"])

    def test_raw_array_bypass_preserves_shape_dtype_and_effect_chain_state(self):
        engine = AudioEngine(EffectChain([]))
        block = np.linspace(-0.25, 0.25, 8, dtype=np.float32)
        engine.set_effects_bypassed(True)

        output = engine.process_voice(block, 8)

        self.assertEqual(output.shape, block.shape)
        self.assertEqual(output.dtype, np.float32)
        self.assertTrue(np.allclose(output, block))
        self.assertEqual(engine.effect_chain.status().disabled_effects, ())
        self.assertEqual(engine.effect_chain.status().runtime_bypassed_effects, ())

    def test_audio_frame_bypass_preserves_contract(self):
        context = AudioContext(
            sample_rate=48000,
            block_size=8,
            frame_count=8,
            input_channel_count=1,
            output_channel_count=1,
            sample_format="float32",
            block_index=7,
            timestamp=1.25,
        )
        frame = AudioFrame(
            samples=np.linspace(-0.1, 0.1, 8, dtype=np.float32),
            sample_rate=48000,
            channel_count=1,
            frame_count=8,
            sample_format="float32",
            block_index=7,
            timestamp=1.25,
            context=context,
        )
        engine = AudioEngine()
        engine.set_effects_bypassed(True)

        output = engine.process_voice(frame)

        self.assertIsInstance(output, AudioFrame)
        self.assertEqual(output.frame_count, frame.frame_count)
        self.assertEqual(output.sample_rate, frame.sample_rate)
        self.assertEqual(output.sample_format, "float32")
        self.assertEqual(output.context, frame.context)
        self.assertTrue(np.allclose(output.samples, frame.samples))

    def test_bypass_does_not_stop_routing_or_change_character(self):
        router = FakeRouter()
        svc = service(router=router)
        svc.start_audio(0, 1)
        svc.select_voice_character("deep")

        svc.set_effects_bypassed(True)
        enabled = svc.active_voice_state()
        svc.set_effects_bypassed(False)

        self.assertEqual(router.starts, [(0, 1, None)])
        self.assertEqual(svc.current_character_id, "deep")
        self.assertIn("bypassed", enabled["text"])
        self.assertFalse(svc.effects_bypassed)

    def test_operator_status_distinguishes_bypass_from_failure(self):
        svc = service()
        svc.select_voice_character("deep")
        svc.set_effects_bypassed(True)

        status = svc.operator_status()

        self.assertIn("bypassed", status.active_voice)
        self.assertNotIn("Unavailable", status.pitch)


class M70PersistenceTests(unittest.TestCase):
    def test_selected_character_and_strength_restore_from_settings(self):
        svc = service(settings={"schema_version": 1, "selected_character_id": "deep", "character_strength": 75})

        self.assertEqual(svc.current_character_id, "deep")
        self.assertEqual(svc.current_character_strength, 75)
        self.assertEqual(svc.active_voice_state()["kind"], "character")

    def test_older_settings_without_strength_remain_valid(self):
        svc = service(settings={"schema_version": 1, "selected_preset": "Deep Voice"})

        self.assertEqual(svc.current_character_id, "deep")
        self.assertEqual(svc.current_character_strength, 100)

    def test_custom_preset_restores_as_custom(self):
        svc = service(settings={"schema_version": 1, "selected_preset": "Luke Deep"})

        self.assertEqual(svc.active_voice_state()["kind"], "custom")
        self.assertIn("Luke Deep", svc.active_voice_state()["text"])

    def test_missing_selected_character_falls_back_safely(self):
        svc = service(settings={"schema_version": 1, "selected_character_id": "missing"})

        self.assertEqual(svc.current_character_id, NATURAL_CHARACTER_ID)
        self.assertFalse(svc.effects_bypassed)
        self.assertEqual(svc.operator_status().processing, "Stopped")


class M70UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        cls.qt_app = QApplication.instance() or QApplication([])

    def make_window(self):
        from voice_lab.ui.main_window import App

        svc = service()
        window = App(svc, on_close=lambda: None)
        self.addCleanup(window.close)
        self.qt_app.processEvents()
        return window, svc

    def test_character_controls_exist_and_advanced_starts_collapsed(self):
        window, _svc = self.make_window()

        self.assertGreater(window.character_box.count(), 0)
        self.assertIn("Active voice", window.active_voice_status.text())
        self.assertFalse(window.advanced_toggle.isChecked())
        self.assertTrue(window.gain.isHidden())

    def test_character_selection_strength_bypass_and_reset_update_ui(self):
        window, svc = self.make_window()

        window.set_combo(window.character_box, "deep")
        window.select_voice_character()
        window.character_strength.setValue(50)
        window.bypass_check.setChecked(True)
        window.reset_voice()

        self.assertEqual(svc.current_character_id, NATURAL_CHARACTER_ID)
        self.assertFalse(svc.effects_bypassed)
        self.assertIn("Natural", window.active_voice_status.text())

    def test_manual_slider_change_marks_unsaved_custom(self):
        window, svc = self.make_window()
        window.advanced_toggle.setChecked(True)
        window.gain.setValue(12)
        self.qt_app.processEvents()

        self.assertEqual(svc.active_voice_state()["kind"], "unsaved")

    def test_advanced_can_expand_and_custom_voice_controls_work(self):
        window, _svc = self.make_window()

        window.advanced_toggle.setChecked(True)

        self.assertFalse(window.gain.isHidden())
        self.assertFalse(window.preset_box.isHidden())
        self.assertEqual(window.bypass_check.text(), "Bypass Effects")

    def test_ui_prohibited_imports(self):
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
        )
        self.assertFalse(any(name.startswith(prohibited) for name in imports))


if __name__ == "__main__":
    unittest.main()
