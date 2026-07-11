import json
import math
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from voice_lab.app.commands import CommandResult
from voice_lab.app.service import ApplicationService
from voice_lab.config.service import ConfigurationService
from voice_lab.config.settings import (
    OperatorSettings,
    StoredDeviceIdentity,
    load_settings,
    save_settings,
    validate_settings_document,
)
from voice_lab.engine.audio_engine import AudioEngine
from voice_lab.plugins import PluginManager
from voice_lab.telemetry import TelemetryService
from voice_lab.tests.test_m6_1_operator_visibility import snapshot
from voice_lab.tests.test_m6_3_device_failure_recovery import FakeHotkeys, FakeRouter, FakeSoundboard
from voice_lab.tests.test_m6_4_device_refresh import raw_device


PRESETS = {
    "Natural": {"gain": 10, "robot": 0, "lowpass": 4000, "pitch": 0},
    "Deep Voice": {"gain": 9, "robot": 0, "lowpass": 2200, "pitch": -4},
}


class SettingsAudioIO:
    def __init__(self, sequences=None):
        self.sequences = list(sequences or [[
            raw_device("Mic", inputs=1),
            raw_device("Cable", outputs=2),
            raw_device("Monitor", outputs=2),
        ]])
        self.query_count = 0

    def query_devices(self):
        self.query_count += 1
        if len(self.sequences) > 1:
            return self.sequences.pop(0)
        return self.sequences[0]


def identity(name, inputs=0, outputs=0, hostapi=0, samplerate=48000.0):
    return StoredDeviceIdentity(
        name=name,
        hostapi=hostapi,
        max_input_channels=inputs,
        max_output_channels=outputs,
        default_samplerate=samplerate,
    )


def settings_document(**overrides):
    data = {
        "schema_version": 1,
        "devices": {
            "input": identity("Mic", inputs=1).asdict(),
            "virtual_output": identity("Cable", outputs=2).asdict(),
            "monitor_output": identity("Monitor", outputs=2).asdict(),
        },
        "monitor_enabled": True,
        "monitor_volume": 0.42,
        "soundboard_volume": 0.64,
        "selected_preset": "Deep Voice",
    }
    data.update(overrides)
    return data


def config_from_settings(load_result):
    return ConfigurationService(
        load_func=lambda: dict(PRESETS),
        save_func=lambda presets: None,
        settings_load_func=lambda: load_result,
        settings_save_func=lambda settings: None,
    )


def service_with_settings(load_result, audio_io=None, router=None):
    return ApplicationService(
        telemetry=TelemetryService(),
        config=config_from_settings(load_result),
        plugins=PluginManager(),
        engine=AudioEngine(),
        audio_io=audio_io or SettingsAudioIO(),
        router=router or FakeRouter(),
        hotkeys=FakeHotkeys(),
        soundboard=FakeSoundboard(),
    )


class M65SettingsFileTests(unittest.TestCase):
    def test_missing_file_produces_safe_first_run_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = load_settings(str(Path(tmp) / "settings.json"))

        self.assertTrue(result.missing)
        self.assertEqual(result.settings.devices, {})
        self.assertFalse(result.settings.monitor_enabled)

    def test_valid_version_one_file_loads_and_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(json.dumps(settings_document()), encoding="utf-8")

            loaded = load_settings(str(path))
            save_settings(loaded.settings, str(path))
            reloaded = load_settings(str(path))

        self.assertFalse(loaded.issues)
        self.assertEqual(reloaded.settings.devices["input"].identity, identity("Mic", inputs=1).identity)
        self.assertEqual(reloaded.settings.selected_preset, "Deep Voice")

    def test_atomic_save_replaces_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(json.dumps({"schema_version": 1, "monitor_enabled": False}), encoding="utf-8")

            save_settings(validate_settings_document(settings_document()).settings, str(path))
            data = json.loads(path.read_text(encoding="utf-8"))

        self.assertTrue(data["monitor_enabled"])
        self.assertEqual(data["monitor_volume"], 0.42)

    def test_save_failure_leaves_prior_valid_file_intact_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            original = {"schema_version": 1, "monitor_enabled": False}
            path.write_text(json.dumps(original), encoding="utf-8")
            with patch("voice_lab.config.settings.os.replace", side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
                    save_settings(validate_settings_document(settings_document()).settings, str(path))

            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), original)
            self.assertEqual(list(Path(tmp).glob(".settings.*.tmp")), [])

    def test_malformed_empty_wrong_root_and_unsupported_schema_do_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            malformed = Path(tmp) / "malformed.json"
            malformed.write_text("{", encoding="utf-8")
            empty = Path(tmp) / "empty.json"
            empty.write_text("", encoding="utf-8")
            wrong_root = validate_settings_document([])
            unsupported = validate_settings_document({"schema_version": 999})

            self.assertTrue(load_settings(str(malformed)).read_failed)
            self.assertTrue(load_settings(str(empty)).read_failed)
            self.assertTrue(wrong_root.read_failed)
            self.assertTrue(unsupported.unsupported_schema)
            self.assertFalse(unsupported.write_allowed)

    def test_unknown_fields_are_ignored_and_valid_fields_survive_invalid_fields(self):
        result = validate_settings_document(
            settings_document(
                unknown=True,
                monitor_volume=2.0,
                soundboard_volume=0.25,
                devices={"input": identity("Mic", inputs=1).asdict(), "unknown_role": {}},
            )
        )

        self.assertEqual(result.settings.soundboard_volume, 0.25)
        self.assertEqual(result.settings.monitor_volume, 0.35)
        self.assertIn("input", result.settings.devices)
        self.assertTrue(result.issues)

    def test_validation_rejects_invalid_types_nan_and_infinity(self):
        cases = [
            {"monitor_enabled": "yes"},
            {"monitor_volume": -0.1},
            {"monitor_volume": 1.1},
            {"soundboard_volume": -0.1},
            {"soundboard_volume": 1.1},
            {"monitor_volume": math.nan},
            {"soundboard_volume": math.inf},
            {"selected_preset": 7},
            {"devices": {"input": {"name": "", "hostapi": 0, "max_input_channels": 1, "max_output_channels": 0}}},
        ]

        for override in cases:
            with self.subTest(override=override):
                self.assertTrue(validate_settings_document(settings_document(**override)).issues)


class M65SettingsServiceTests(unittest.TestCase):
    def test_stored_devices_resolve_uniquely_at_startup(self):
        svc = service_with_settings(validate_settings_document(settings_document()))
        prefs = svc.operator_preferences()

        self.assertEqual(prefs["selections"], {"input": 0, "virtual_output": 1, "monitor_output": 2})
        self.assertTrue(prefs["monitor_enabled"])
        self.assertEqual(prefs["monitor_volume"], 0.42)
        self.assertEqual(prefs["soundboard_volume"], 0.64)
        self.assertEqual(prefs["selected_preset"], "Deep Voice")

    def test_device_moved_to_new_index_restores_by_identity(self):
        svc = service_with_settings(
            validate_settings_document(settings_document()),
            audio_io=SettingsAudioIO([[
                raw_device("Other", outputs=2),
                raw_device("Mic", inputs=1),
                raw_device("Cable", outputs=2),
                raw_device("Monitor", outputs=2),
            ]]),
        )

        self.assertEqual(svc.operator_preferences()["selections"], {
            "input": 1,
            "virtual_output": 2,
            "monitor_output": 3,
        })

    def test_same_index_different_identity_duplicate_and_missing_do_not_restore(self):
        duplicate = SettingsAudioIO([[
            raw_device("Different", inputs=1),
            raw_device("Cable", outputs=2),
            raw_device("Cable", outputs=2),
        ]])
        svc = service_with_settings(validate_settings_document(settings_document()), audio_io=duplicate)
        prefs = svc.operator_preferences()

        self.assertIsNone(prefs["selections"]["input"])
        self.assertIsNone(prefs["selections"]["virtual_output"])
        self.assertIsNone(prefs["selections"]["monitor_output"])
        self.assertIn("input", prefs["missing_roles"])
        self.assertIn("virtual_output", prefs["missing_roles"])
        self.assertIn("monitor_output", prefs["missing_roles"])

    def test_monitor_enabled_remains_enabled_when_monitor_device_is_missing(self):
        svc = service_with_settings(
            validate_settings_document(settings_document()),
            audio_io=SettingsAudioIO([[raw_device("Mic", inputs=1), raw_device("Cable", outputs=2)]]),
        )

        prefs = svc.operator_preferences()

        self.assertTrue(svc.current_monitor_enabled)
        self.assertIsNone(prefs["selections"]["monitor_output"])
        self.assertIn("Saved monitor output", svc.operator_status().actionable_status)

    def test_first_launch_has_no_numeric_or_first_available_device_selection(self):
        svc = service_with_settings(validate_settings_document({"schema_version": 1}))

        self.assertEqual(svc.operator_preferences()["selections"], {
            "input": None,
            "virtual_output": None,
            "monitor_output": None,
        })
        self.assertIsNone(svc.default_input_id())
        self.assertFalse(svc.start_audio(None, None).success)

    def test_returning_preferred_identity_restores_on_refresh_without_substitution(self):
        audio_io = SettingsAudioIO([
            [raw_device("Other Mic", inputs=1), raw_device("Other Output", outputs=2)],
            [raw_device("Mic", inputs=1), raw_device("Cable", outputs=2), raw_device("Monitor", outputs=2)],
        ])
        svc = service_with_settings(validate_settings_document(settings_document()), audio_io=audio_io)
        self.assertIsNone(svc.operator_preferences()["selections"]["input"])

        result = svc.refresh_devices(None, None, None)

        self.assertTrue(result.success)
        self.assertEqual(result.metadata["selections"], {"input": 0, "virtual_output": 1, "monitor_output": 2})

    def test_explicit_device_and_preset_changes_update_settings_and_shutdown_flushes(self):
        saved = []
        config = ConfigurationService(
            load_func=lambda: dict(PRESETS),
            save_func=lambda presets: None,
            settings_load_func=lambda: validate_settings_document({"schema_version": 1}),
            settings_save_func=lambda settings: saved.append(settings),
        )
        svc = ApplicationService(
            telemetry=TelemetryService(),
            config=config,
            plugins=PluginManager(),
            engine=AudioEngine(),
            audio_io=SettingsAudioIO(),
            router=FakeRouter(),
            hotkeys=FakeHotkeys(),
            soundboard=FakeSoundboard(),
        )

        self.assertTrue(svc.record_device_selection("input", 0).success)
        self.assertTrue(svc.select_preset("Deep Voice").success)
        svc.apply_effect_parameters(1.0, 0.0, 4000, True, 0.5, 0.25, pitch=0)
        svc.save_configuration()

        self.assertEqual(saved[-1].devices["input"].name, "Mic")
        self.assertEqual(saved[-1].selected_preset, "Deep Voice")
        self.assertTrue(saved[-1].monitor_enabled)
        self.assertEqual(saved[-1].monitor_volume, 0.5)

    def test_save_failure_reports_telemetry_without_preventing_stop(self):
        def fail_save(settings):
            raise OSError("disk full")

        config = ConfigurationService(
            load_func=lambda: dict(PRESETS),
            save_func=lambda presets: None,
            settings_load_func=lambda: validate_settings_document({"schema_version": 1}),
            settings_save_func=fail_save,
        )
        svc = ApplicationService(
            telemetry=TelemetryService(),
            config=config,
            plugins=PluginManager(),
            engine=AudioEngine(),
            audio_io=SettingsAudioIO(),
            router=FakeRouter(),
            hotkeys=FakeHotkeys(),
            soundboard=FakeSoundboard(),
        )
        svc.apply_effect_parameters(1.0, 0.0, 4000, True, 0.5, 0.25, pitch=0)

        self.assertTrue(svc.stop_audio().success)
        with self.assertRaises(OSError):
            svc.save_configuration()
        self.assertTrue(any(event.event_type == "settings.save_failed" for event in svc.telemetry_snapshot().recent_events))

    def test_unsupported_schema_is_not_overwritten_on_startup_flush(self):
        saved = []
        config = ConfigurationService(
            load_func=lambda: dict(PRESETS),
            save_func=lambda presets: None,
            settings_load_func=lambda: validate_settings_document({"schema_version": 999}),
            settings_save_func=lambda settings: saved.append(settings),
        )
        svc = ApplicationService(
            telemetry=TelemetryService(),
            config=config,
            plugins=PluginManager(),
            engine=AudioEngine(),
            audio_io=SettingsAudioIO(),
            router=FakeRouter(),
            hotkeys=FakeHotkeys(),
            soundboard=FakeSoundboard(),
        )

        svc.save_configuration()

        self.assertEqual(saved, [])
        self.assertIn("unsupported schema", svc.operator_status().actionable_status)


class SignalStub:
    def connect(self, slot):
        self.slot = slot


class UiSettingsService:
    def __init__(self):
        self.status_changed = SignalStub()
        self.preset_selected = SignalStub()
        self.device_selections = []
        self.apply_calls = []
        self.closed = False

    def devices(self):
        from voice_lab.app.devices import describe_devices

        return describe_devices([
            raw_device("Mic", inputs=1),
            raw_device("Cable", outputs=2),
            raw_device("Monitor", outputs=2),
        ])

    def operator_preferences(self):
        return {
            "selections": {"input": 0, "virtual_output": 1, "monitor_output": 2},
            "monitor_enabled": True,
            "monitor_volume": 0.55,
            "soundboard_volume": 0.25,
            "selected_preset": "Deep Voice",
        }

    def default_input_id(self):
        return None

    def default_output_id(self):
        return None

    def default_monitor_id(self):
        return None

    def preset_names(self):
        return ["Natural", "Deep Voice"]

    def select_preset(self, name, persist=True):
        return CommandResult.ok(params=PRESETS[name])

    def apply_effect_parameters(self, **kwargs):
        self.apply_calls.append(kwargs)
        return CommandResult.ok()

    def record_device_selection(self, role, selected_id):
        self.device_selections.append((role, selected_id))
        return CommandResult.ok()

    def sound_files(self):
        return []

    def play_sound_file(self, filename):
        return CommandResult.ok()

    def play_sound_by_index(self, index):
        return CommandResult.ok()

    def save_preset(self, name, params):
        return CommandResult.ok("Saved")

    def delete_preset(self, name):
        return CommandResult.ok("Deleted")

    def start_audio(self, input_id, output_id, monitor_id=None):
        return CommandResult.ok("Running")

    def stop_audio(self):
        return CommandResult.ok("Stopped")

    def refresh_devices(self, input_id=None, output_id=None, monitor_id=None):
        return CommandResult.ok(
            "Audio devices refreshed.",
            selections={"input": input_id, "virtual_output": output_id, "monitor_output": monitor_id},
        )

    def operator_status(self):
        from voice_lab.app.operator_status import build_operator_status

        return build_operator_status(snapshot(), "stopped")


class M65SettingsUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        cls.qt_app = QApplication.instance() or QApplication([])

    def test_ui_restores_preferences_through_service_and_starts_stopped(self):
        from voice_lab.ui.main_window import App

        service = UiSettingsService()
        window = App(service, on_close=lambda: setattr(service, "closed", True))
        self.addCleanup(window.close)
        self.qt_app.processEvents()

        self.assertEqual(window.input_box.currentData(), 0)
        self.assertEqual(window.output_box.currentData(), 1)
        self.assertEqual(window.monitor_box.currentData(), 2)
        self.assertTrue(window.monitor_check.isChecked())
        self.assertEqual(window.monitor_volume.value(), 55)
        self.assertEqual(window.soundboard_volume.value(), 25)
        self.assertEqual(window.preset_box.currentText(), "Deep Voice")
        self.assertEqual(window.processing_status.text(), "Processing: Stopped")
        self.assertFalse(any(call.get("persist_settings") for call in service.apply_calls[:1]))

    def test_explicit_ui_device_change_updates_preferred_identity(self):
        from voice_lab.ui.main_window import App

        service = UiSettingsService()
        window = App(service, on_close=lambda: None)
        self.addCleanup(window.close)

        window.input_box.setCurrentIndex(0)
        self.qt_app.processEvents()

        self.assertIn(("input", None), service.device_selections)


if __name__ == "__main__":
    unittest.main()
