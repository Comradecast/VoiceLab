import ast
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QMessageBox

from voice_lab.app.service import ApplicationService
from voice_lab.config.service import ConfigurationService
from voice_lab.config.settings import validate_settings_document
from voice_lab.config.voice_characters import protected_voice_names
from voice_lab.engine.audio_engine import AudioEngine
from voice_lab.plugins import PluginManager
from voice_lab.telemetry import TelemetryService
from voice_lab.tests.test_m6_3_device_failure_recovery import FakeHotkeys, FakeRouter, FakeSoundboard
from voice_lab.tests.test_m6_5_operator_settings import SettingsAudioIO


BASE_PRESETS = {
    "Natural": {"gain": 10, "robot": 0, "lowpass": 4000, "pitch": 0},
    "Deep Voice": {"gain": 9, "robot": 0, "lowpass": 2200, "pitch": -4},
    "Luke Deep": {"gain": 11, "robot": 5, "lowpass": 2500, "pitch": -3},
    "Bright Custom": {"gain": 8, "robot": 0, "lowpass": 6500, "pitch": 3},
}


class PresetStore:
    def __init__(self, presets=None):
        self.presets = dict(presets or BASE_PRESETS)
        self.saved = []

    def load(self):
        return dict(self.presets)

    def save(self, presets):
        self.presets = dict(presets)
        self.saved.append(dict(presets))


class SettingsStore:
    def __init__(self, document=None):
        self.document = document or {"schema_version": 1}
        self.saved = []

    def load(self):
        return validate_settings_document(dict(self.document))

    def save(self, settings):
        self.document = settings.asdict()
        self.saved.append(settings)


def make_service(presets=None, settings=None, router=None):
    preset_store = PresetStore(presets)
    settings_store = SettingsStore(settings)
    config = ConfigurationService(
        load_func=preset_store.load,
        save_func=preset_store.save,
        settings_load_func=settings_store.load,
        settings_save_func=settings_store.save,
    )
    svc = ApplicationService(
        telemetry=TelemetryService(),
        config=config,
        plugins=PluginManager(),
        engine=AudioEngine(),
        audio_io=SettingsAudioIO(),
        router=router or FakeRouter(),
        hotkeys=FakeHotkeys(),
        soundboard=FakeSoundboard(),
    )
    return svc, preset_store, settings_store


class M72ServiceTests(unittest.TestCase):
    def test_built_ins_and_existing_customs_are_classified_without_renaming_built_ins(self):
        svc, _presets, _settings = make_service()

        entries = svc.voice_selector_entries()
        built_ins = [entry["label"] for entry in entries if entry["kind"] == "built_in"]
        customs = [entry["label"] for entry in entries if entry["kind"] == "custom"]

        self.assertEqual(
            built_ins,
            ["Natural", "Deep", "Heavy Bass", "Higher", "Robot", "Radio", "Muffled"],
        )
        self.assertIn("Luke Deep", customs)
        self.assertTrue(protected_voice_names())

    def test_rename_custom_voice_succeeds_preserves_params_removes_old_and_updates_active(self):
        svc, store, _settings = make_service()
        self.assertTrue(svc.select_preset("Luke Deep").success)

        result = svc.rename_custom_voice("Luke Deep", "  Luke Low  ")

        self.assertTrue(result.success)
        self.assertNotIn("Luke Deep", store.presets)
        self.assertEqual(store.presets["Luke Low"], {"gain": 11, "robot": 5, "lowpass": 2500, "pitch": -3})
        self.assertEqual(svc.active_voice_state()["custom_preset"], "Luke Low")

    def test_rename_survives_reload_through_existing_presets_and_settings(self):
        svc, store, settings = make_service(settings={"schema_version": 1, "selected_preset": "Luke Deep"})
        self.assertTrue(svc.rename_custom_voice("Luke Deep", "Luke Low").success)
        svc.save_configuration()

        reloaded, _store2, _settings2 = make_service(store.presets, settings.document)

        self.assertEqual(reloaded.active_voice_state()["kind"], "custom")
        self.assertEqual(reloaded.active_voice_state()["custom_preset"], "Luke Low")

    def test_rename_rejects_empty_reserved_and_conflicting_names(self):
        svc, _store, _settings = make_service()

        self.assertFalse(svc.rename_custom_voice("Luke Deep", " ").success)
        self.assertFalse(svc.rename_custom_voice("Luke Deep", "Natural").success)
        self.assertFalse(svc.rename_custom_voice("Luke Deep", "Bright Custom").success)
        self.assertFalse(svc.rename_custom_voice("Luke Deep", "Custom - Unsaved").success)

    def test_duplicate_custom_voice_preserves_source_copies_params_selects_new_and_survives_reload(self):
        svc, store, settings = make_service()

        result = svc.duplicate_custom_voice("Luke Deep", "Luke Copy")
        svc.save_configuration()
        reloaded, _store2, _settings2 = make_service(store.presets, settings.document)

        self.assertTrue(result.success)
        self.assertIn("Luke Deep", store.presets)
        self.assertEqual(store.presets["Luke Copy"], store.presets["Luke Deep"])
        self.assertEqual(svc.active_voice_state()["custom_preset"], "Luke Copy")
        self.assertEqual(reloaded.active_voice_state()["custom_preset"], "Luke Copy")

    def test_duplicate_rejects_invalid_names(self):
        svc, _store, _settings = make_service()

        self.assertFalse(svc.duplicate_custom_voice("Luke Deep", "").success)
        self.assertFalse(svc.duplicate_custom_voice("Luke Deep", "Robot").success)
        self.assertFalse(svc.duplicate_custom_voice("Luke Deep", "Bright Custom").success)

    def test_delete_rejects_built_in_and_active_custom_resolves_to_natural_without_route_changes(self):
        router = FakeRouter()
        svc, store, _settings = make_service(router=router)
        svc.apply_effect_parameters(1.0, 0.0, 4000, True, 0.22, 0.44, pitch=0, mark_custom=False)
        svc.start_audio(0, 1, 2)
        svc.select_preset("Luke Deep")

        built_in = svc.delete_custom_voice("Robot")
        deleted = svc.delete_custom_voice("Luke Deep")

        self.assertFalse(built_in.success)
        self.assertTrue(deleted.success)
        self.assertNotIn("Luke Deep", store.presets)
        self.assertEqual(svc.active_voice_state()["kind"], "character")
        self.assertEqual(svc.current_character_id, "natural")
        self.assertTrue(svc.current_monitor_enabled)
        self.assertEqual(svc.current_monitor_volume, 0.22)
        self.assertEqual(svc.current_soundboard_volume, 0.44)
        self.assertEqual(router.starts, [(0, 1, 2)])

    def test_delete_survives_reload(self):
        svc, store, _settings = make_service()

        self.assertTrue(svc.delete_custom_voice("Luke Deep").success)
        reloaded, _store2, _settings2 = make_service(store.presets)

        self.assertNotIn("Luke Deep", reloaded.custom_preset_names())

    def test_overwrite_requires_authorization_and_replaces_intended_voice_only(self):
        svc, store, _settings = make_service()
        replacement = {"gain": 13, "robot": 0, "lowpass": 3000, "pitch": 1}

        blocked = svc.save_preset("Luke Deep", replacement)
        existing = dict(store.presets["Luke Deep"])
        overwritten = svc.save_custom_voice("Luke Deep", replacement, overwrite=True)

        self.assertFalse(blocked.success)
        self.assertEqual(existing, {"gain": 11, "robot": 5, "lowpass": 2500, "pitch": -3})
        self.assertTrue(overwritten.success)
        self.assertEqual(store.presets["Luke Deep"], replacement)
        self.assertEqual(len([name for name in store.presets if name.casefold() == "luke deep"]), 1)

    def test_settings_compatibility_and_launch_stopped_remain(self):
        svc, _store, _settings = make_service(settings={"schema_version": 1, "selected_preset": "Luke Deep"})

        self.assertEqual(svc.active_voice_state()["kind"], "custom")
        self.assertEqual(svc.operator_status().processing, "Stopped")

    def test_bypass_remains_separate_from_voice_identity(self):
        svc, _store, _settings = make_service()
        svc.select_preset("Luke Deep")
        svc.set_effects_bypassed(True)

        state = svc.active_voice_state()

        self.assertEqual(state["kind"], "custom")
        self.assertEqual(state["custom_preset"], "Luke Deep")
        self.assertTrue(state["effects_bypassed"])


class M72StateTests(unittest.TestCase):
    def test_manual_change_produces_unsaved_and_reset_preserves_runtime_state(self):
        router = FakeRouter()
        svc, _store, _settings = make_service(router=router)
        svc.apply_effect_parameters(1.0, 0.0, 4000, True, 0.3, 0.5, pitch=0, mark_custom=False)
        svc.start_audio(0, 1, 2)
        svc.select_preset("Luke Deep")

        svc.apply_effect_parameters(1.4, 0.0, 2600, True, 0.3, 0.5, pitch=-2)
        result = svc.reset_voice()

        self.assertEqual(svc.active_voice_state()["kind"], "character")
        self.assertTrue(result.success)
        self.assertTrue(svc.current_monitor_enabled)
        self.assertEqual(router.starts, [(0, 1, 2)])


class M72UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        cls.qt_app = QApplication.instance() or QApplication([])

    def make_window(self):
        from voice_lab.ui.main_window import App

        svc, store, settings = make_service()
        window = App(svc, on_close=lambda: None)
        self.addCleanup(window.close)
        self.qt_app.processEvents()
        return window, svc, store, settings

    def test_selector_has_non_selectable_sections_and_custom_entries(self):
        window, _svc, _store, _settings = self.make_window()

        data = [window.character_box.itemData(index) for index in range(window.character_box.count())]

        self.assertIn(("section", None), data)
        self.assertIn(("built_in", "natural"), data)
        self.assertIn(("custom", "Luke Deep"), data)

    def test_custom_action_enabled_state_tracks_saved_custom_voice(self):
        window, svc, _store, _settings = self.make_window()

        svc.select_preset("Luke Deep")
        window.sync_voice_controls_from_service()
        self.assertTrue(window.rename_preset_button.isEnabled())
        self.assertTrue(window.duplicate_preset_button.isEnabled())
        self.assertTrue(window.delete_preset_button.isEnabled())

        svc.select_voice_character("deep")
        window.sync_voice_controls_from_service()
        self.assertFalse(window.rename_preset_button.isEnabled())
        self.assertFalse(window.duplicate_preset_button.isEnabled())
        self.assertFalse(window.delete_preset_button.isEnabled())

    def test_delete_cancel_preserves_voice(self):
        window, svc, store, _settings = self.make_window()
        svc.select_preset("Luke Deep")
        window.sync_voice_controls_from_service()

        with patch.object(window, "confirm_delete_custom_voice", return_value=False):
            window.delete_current_preset()

        self.assertIn("Luke Deep", store.presets)
        self.assertEqual(svc.active_voice_state()["custom_preset"], "Luke Deep")

    def test_overwrite_cancel_preserves_existing_voice(self):
        window, _svc, store, _settings = self.make_window()
        window.gain.setValue(13)

        with (
            patch("voice_lab.ui.main_window.QInputDialog.getText", return_value=("Luke Deep", True)),
            patch.object(window, "confirm_overwrite_custom_voice", return_value=False),
        ):
            window.save_current_as_preset()

        self.assertEqual(store.presets["Luke Deep"], {"gain": 11, "robot": 5, "lowpass": 2500, "pitch": -3})

    def test_unsaved_selector_cancel_preserves_params_and_state(self):
        window, svc, _store, _settings = self.make_window()
        svc.select_voice_character("deep")
        svc.apply_effect_parameters(1.3, 0.0, 2200, False, 0.35, 0.7, pitch=-4)
        window.sync_voice_controls_from_service()
        before = dict(svc.current_effect_params)

        with patch.object(window, "confirm_discard_unsaved_changes", return_value=False):
            window.set_combo(window.character_box, ("built_in", "higher"))
            window.select_voice_character()

        self.assertEqual(svc.active_voice_state()["kind"], "unsaved")
        self.assertEqual(svc.current_effect_params, before)

    def test_unsaved_selector_discard_and_reset_discard_continue(self):
        window, svc, _store, _settings = self.make_window()
        svc.select_voice_character("deep")
        svc.apply_effect_parameters(1.3, 0.0, 2200, False, 0.35, 0.7, pitch=-4)
        window.sync_voice_controls_from_service()

        with patch.object(window, "confirm_discard_unsaved_changes", return_value=True):
            window.set_combo(window.character_box, ("built_in", "higher"))
            window.select_voice_character()
        self.assertEqual(svc.current_character_id, "higher")

        svc.apply_effect_parameters(1.3, 0.0, 2200, False, 0.35, 0.7, pitch=-4)
        with patch.object(window, "confirm_discard_unsaved_changes", return_value=True):
            window.reset_voice()
        self.assertEqual(svc.current_character_id, "natural")

    def test_ui_prohibited_imports_remain(self):
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
            "numpy",
        )
        self.assertFalse(any(name.startswith(prohibited) for name in imports))


if __name__ == "__main__":
    unittest.main()
