import ast
import os
import unittest
from pathlib import Path

from voice_lab.app.commands import CommandResult
from voice_lab.app.devices import describe_devices
from voice_lab.app.operator_status import build_operator_status
from voice_lab.app.service import ApplicationService
from voice_lab.engine.audio_engine import AudioEngine
from voice_lab.io.device_errors import DeviceFailure
from voice_lab.plugins import PluginManager
from voice_lab.telemetry import TelemetryService
from voice_lab.tests.test_m6_3_device_failure_recovery import (
    FakeConfig,
    FakeHotkeys,
    FakeRouter,
    FakeSoundboard,
)
from voice_lab.tests.test_m6_1_operator_visibility import snapshot


def raw_device(name, inputs=0, outputs=0, hostapi=0, samplerate=48000.0):
    return {
        "name": name,
        "hostapi": hostapi,
        "max_input_channels": inputs,
        "max_output_channels": outputs,
        "default_samplerate": samplerate,
    }


class RefreshAudioIO:
    def __init__(self, sequences=None, fail=False):
        self.sequences = list(sequences or [[
            raw_device("Mic", inputs=1),
            raw_device("Cable", outputs=2),
            raw_device("Monitor", outputs=2),
        ]])
        self.fail = fail
        self.query_count = 0

    def query_devices(self):
        self.query_count += 1
        if self.fail:
            raise RuntimeError("PortAudio enumeration traceback detail")
        if len(self.sequences) > 1:
            return self.sequences.pop(0)
        return self.sequences[0]


def service(audio_io=None, router=None):
    return ApplicationService(
        telemetry=TelemetryService(),
        plugins=PluginManager(),
        engine=AudioEngine(),
        router=router or FakeRouter(),
        audio_io=audio_io or RefreshAudioIO(),
        config=FakeConfig(),
        hotkeys=FakeHotkeys(),
        soundboard=FakeSoundboard(),
    )


class M64DeviceRefreshServiceTests(unittest.TestCase):
    def test_refresh_is_available_while_stopped_and_failed(self):
        self.assertTrue(build_operator_status(snapshot(), "stopped").refresh_enabled)
        self.assertTrue(build_operator_status(snapshot(route_status="error"), "failed").refresh_enabled)

    def test_refresh_is_disabled_while_starting_running_and_stopping(self):
        self.assertFalse(build_operator_status(snapshot(), "starting").refresh_enabled)
        self.assertFalse(build_operator_status(snapshot(audio_running=True), "running").refresh_enabled)
        self.assertFalse(build_operator_status(snapshot(), "stopping").refresh_enabled)

    def test_service_rejects_refresh_while_running(self):
        svc = service()
        self.assertTrue(svc.start_audio(0, 1).success)

        result = svc.refresh_devices(0, 1, 2)

        self.assertFalse(result.success)
        self.assertEqual(result.message, "Stop processing before refreshing audio devices.")

    def test_service_rejects_refresh_while_starting_and_stopping(self):
        svc = service()
        svc._processing_state = "starting"
        self.assertFalse(svc.refresh_devices(0, 1, 2).success)
        svc._processing_state = "stopping"
        self.assertFalse(svc.refresh_devices(0, 1, 2).success)

    def test_successful_refresh_updates_device_model_and_role_lists(self):
        audio_io = RefreshAudioIO(sequences=[
            [raw_device("Old Mic", inputs=1), raw_device("Old Cable", outputs=2)],
            [
                raw_device("New Mic", inputs=1),
                raw_device("Duplex", inputs=1, outputs=2),
                raw_device("New Monitor", outputs=2),
            ],
        ])
        svc = service(audio_io=audio_io)
        svc.devices()

        result = svc.refresh_devices(None, None, None)

        self.assertTrue(result.success)
        devices = result.metadata["devices"]
        self.assertEqual([device["name"] for device in devices], ["New Mic", "Duplex", "New Monitor"])
        self.assertTrue(devices[0]["input_capable"])
        self.assertTrue(devices[1]["input_capable"])
        self.assertTrue(devices[1]["output_capable"])
        self.assertTrue(devices[2]["output_capable"])

    def test_same_index_same_identity_selection_is_preserved(self):
        devices = [raw_device("Mic", inputs=1), raw_device("Cable", outputs=2)]
        svc = service(audio_io=RefreshAudioIO(sequences=[devices, list(devices)]))
        svc.devices()

        result = svc.refresh_devices(0, 1, None)

        self.assertEqual(result.metadata["selections"]["input"], 0)
        self.assertEqual(result.metadata["selections"]["virtual_output"], 1)

    def test_unique_identity_at_new_index_is_preserved(self):
        svc = service(audio_io=RefreshAudioIO(sequences=[
            [raw_device("Mic", inputs=1), raw_device("Cable", outputs=2)],
            [raw_device("Other", outputs=2), raw_device("Mic", inputs=1), raw_device("Cable", outputs=2)],
        ]))
        svc.devices()

        result = svc.refresh_devices(0, 1, None)

        self.assertEqual(result.metadata["selections"]["input"], 1)
        self.assertEqual(result.metadata["selections"]["virtual_output"], 2)

    def test_same_index_different_identity_is_not_preserved(self):
        svc = service(audio_io=RefreshAudioIO(sequences=[
            [raw_device("Mic", inputs=1), raw_device("Cable", outputs=2)],
            [raw_device("Different", inputs=1), raw_device("Cable", outputs=2)],
        ]))
        svc.devices()

        result = svc.refresh_devices(0, 1, None)

        self.assertIsNone(result.metadata["selections"]["input"])
        self.assertIn("input", result.metadata["missing_roles"])

    def test_duplicate_identity_ambiguity_does_not_select_replacement(self):
        svc = service(audio_io=RefreshAudioIO(sequences=[
            [raw_device("Mic", inputs=1), raw_device("Cable", outputs=2)],
            [raw_device("Other", outputs=2), raw_device("Mic", inputs=1), raw_device("Mic", inputs=1)],
        ]))
        svc.devices()

        result = svc.refresh_devices(0, 1, None)

        self.assertIsNone(result.metadata["selections"]["input"])
        self.assertIn("input", result.metadata["missing_roles"])

    def test_missing_roles_are_cleared_and_reported(self):
        svc = service(audio_io=RefreshAudioIO(sequences=[
            [raw_device("Mic", inputs=1), raw_device("Cable", outputs=2), raw_device("Monitor", outputs=2)],
            [raw_device("Other", inputs=1), raw_device("Speaker", outputs=2)],
        ]))
        svc.devices()

        result = svc.refresh_devices(0, 1, 2)

        self.assertEqual(result.metadata["selections"], {
            "input": None,
            "virtual_output": None,
            "monitor_output": None,
        })
        self.assertEqual(
            result.message,
            "Audio devices refreshed; microphone, virtual microphone, and monitor selections require attention.",
        )

    def test_monitor_and_effect_state_remain_unchanged(self):
        svc = service(audio_io=RefreshAudioIO())
        svc.apply_effect_parameters(1.2, 0.3, 3000, True, 0.22, 0.44, pitch=4)
        before_params = dict(svc.current_effect_params)

        svc.refresh_devices(0, 1, 2)

        self.assertTrue(svc.current_monitor_enabled)
        self.assertEqual(svc.current_monitor_volume, 0.22)
        self.assertEqual(svc.current_soundboard_volume, 0.44)
        self.assertEqual(svc.current_effect_params, before_params)

    def test_enumeration_failure_preserves_old_devices_and_selections(self):
        audio_io = RefreshAudioIO()
        svc = service(audio_io=audio_io)
        old_devices = svc.devices()
        audio_io.fail = True

        result = svc.refresh_devices(0, 1, 2)

        self.assertFalse(result.success)
        self.assertEqual(svc.devices(), old_devices)
        self.assertIn("could not refresh audio devices", result.message)

    def test_enumeration_failure_records_technical_detail(self):
        audio_io = RefreshAudioIO()
        svc = service(audio_io=audio_io)
        svc.devices()
        audio_io.fail = True

        result = svc.refresh_devices(0, 1, 2)

        self.assertIn("PortAudio enumeration", result.metadata["refresh_failure"]["technical_detail"])
        events = svc.telemetry_snapshot().recent_events
        self.assertTrue(any(event.event_type == "devices.refresh_failed" for event in events))

    def test_retry_after_enumeration_failure_can_succeed(self):
        audio_io = RefreshAudioIO(sequences=[
            [raw_device("Mic", inputs=1), raw_device("Cable", outputs=2)],
            [raw_device("Mic", inputs=1), raw_device("Cable", outputs=2), raw_device("Monitor", outputs=2)],
        ])
        svc = service(audio_io=audio_io)
        svc.devices()
        audio_io.fail = True
        self.assertFalse(svc.refresh_devices(0, 1, None).success)
        audio_io.fail = False

        result = svc.refresh_devices(0, 1, None)

        self.assertTrue(result.success)
        self.assertEqual(len(result.metadata["devices"]), 3)

    def test_refresh_does_not_clear_unresolved_start_failure(self):
        svc = service(router=FakeRouter([DeviceFailure("device_open_failed", "input")]))
        svc.start_audio(0, 1)

        svc.refresh_devices(0, 1, None)

        self.assertIn("microphone could not be opened", svc.operator_status().actionable_status)

    def test_successful_start_after_corrected_selection_clears_start_failure(self):
        router = FakeRouter([DeviceFailure("device_open_failed", "input")])
        svc = service(router=router)
        svc.start_audio(0, 1)
        svc.refresh_devices(0, 1, None)

        result = svc.start_audio(0, 1)

        self.assertTrue(result.success)
        self.assertEqual(svc.operator_status().actionable_status, "")

    def test_status_polling_does_not_trigger_device_refresh(self):
        audio_io = RefreshAudioIO()
        svc = service(audio_io=audio_io)
        svc.devices()
        before = audio_io.query_count

        svc.operator_status()
        svc.operator_status()

        self.assertEqual(audio_io.query_count, before)


class FakeRefreshService:
    def __init__(self, result=None, statuses=None):
        self.status_changed = SignalStub()
        self.preset_selected = SignalStub()
        self._devices = describe_devices([
            raw_device("Mic", inputs=1),
            raw_device("Cable", outputs=2),
            raw_device("Monitor", outputs=2),
        ])
        self.result = result
        self.statuses = list(statuses or [build_operator_status(snapshot(), "stopped")])
        self.refresh_calls = 0
        self.apply_calls = 0
        self.closed = False

    def devices(self):
        return self._devices

    def default_input_id(self):
        return 0

    def default_output_id(self):
        return 1

    def default_monitor_id(self):
        return 2

    def preset_names(self):
        return ["Clean"]

    def select_preset(self, name):
        return CommandResult.ok(params={"gain": 10, "pitch": 0, "robot": 0, "lowpass": 4000})

    def apply_effect_parameters(self, **kwargs):
        self.apply_calls += 1
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
        self.refresh_calls += 1
        if self.result is not None:
            return self.result
        self._devices = describe_devices([
            raw_device("Mic", inputs=1),
            raw_device("Cable", outputs=2),
            raw_device("New Monitor", outputs=2),
        ])
        return CommandResult.ok(
            "Audio devices refreshed; monitor selection is no longer available.",
            selections={"input": input_id, "virtual_output": output_id, "monitor_output": None},
        )

    def operator_status(self):
        return self.statuses[-1]


class SignalStub:
    def connect(self, slot):
        self.slot = slot


class M64DeviceRefreshUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        cls.qt_app = QApplication.instance() or QApplication([])

    def make_window(self, service):
        from voice_lab.ui.main_window import App

        window = App(service, on_close=lambda: setattr(service, "closed", True))
        self.addCleanup(window.close)
        self.qt_app.processEvents()
        return window

    def test_refresh_button_enabled_only_in_permitted_states(self):
        service = FakeRefreshService()
        window = self.make_window(service)
        self.assertTrue(window.refresh_devices_button.isEnabled())

        service.statuses[:] = [build_operator_status(snapshot(audio_running=True), "running")]
        window.refresh_operator_status()
        self.assertFalse(window.refresh_devices_button.isEnabled())

        service.statuses[:] = [build_operator_status(snapshot(route_status="error"), "failed")]
        window.refresh_operator_status()
        self.assertTrue(window.refresh_devices_button.isEnabled())

    def test_successful_refresh_atomically_repopulates_and_clears_missing_monitor(self):
        service = FakeRefreshService()
        window = self.make_window(service)

        window.refresh_devices()

        self.assertEqual(service.refresh_calls, 1)
        self.assertEqual(window.input_box.currentData(), 0)
        self.assertEqual(window.output_box.currentData(), 1)
        self.assertIsNone(window.monitor_box.currentData())
        self.assertIn("monitor selection", window.status.text())

    def test_enumeration_failure_preserves_combo_contents_and_selections(self):
        result = CommandResult.fail(
            "VoiceLab could not refresh audio devices. Check Windows audio services and try again.",
            refresh_failure={"technical_detail": "PortAudio traceback"},
        )
        service = FakeRefreshService(result=result)
        window = self.make_window(service)
        before = [window.input_box.itemText(i) for i in range(window.input_box.count())]
        before_selection = window.input_box.currentData()

        window.refresh_devices()

        after = [window.input_box.itemText(i) for i in range(window.input_box.count())]
        self.assertEqual(after, before)
        self.assertEqual(window.input_box.currentData(), before_selection)
        self.assertIn("could not refresh audio devices", window.status.text())

    def test_combo_signals_are_blocked_during_refresh_repopulation(self):
        service = FakeRefreshService()
        window = self.make_window(service)
        calls = {"count": 0}
        window.monitor_box.currentIndexChanged.connect(lambda index: calls.__setitem__("count", calls["count"] + 1))

        window.refresh_devices()

        self.assertEqual(calls["count"], 0)

    def test_status_polling_does_not_refresh_devices(self):
        service = FakeRefreshService()
        window = self.make_window(service)

        window.refresh_operator_status()
        window.refresh_operator_status()

        self.assertEqual(service.refresh_calls, 0)

    def test_offscreen_ui_refresh_and_close_is_safe(self):
        service = FakeRefreshService()
        window = self.make_window(service)

        window.refresh_devices()
        window.close()
        self.qt_app.processEvents()

        self.assertTrue(service.closed)

    def test_ui_has_no_audioio_router_or_sounddevice_imports(self):
        tree = ast.parse(Path("voice_lab/ui/main_window.py").read_text())
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")

        self.assertFalse(any(name.startswith("sounddevice") for name in imports))
        self.assertFalse(any(name.startswith("voice_lab.io.audio_io") for name in imports))
        self.assertFalse(any(name.startswith("voice_lab.io.router") for name in imports))


if __name__ == "__main__":
    unittest.main()
