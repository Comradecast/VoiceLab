import os
import unittest

from voice_lab.app.commands import CommandResult
from voice_lab.app.operator_status import build_operator_status
from voice_lab.effects.chain import EffectChainStatus, EffectFailureStatus
from voice_lab.telemetry.events import make_event
from voice_lab.telemetry.snapshot import TelemetrySnapshot


def snapshot(
    *,
    audio_running=False,
    route_status="stopped",
    semitones=0.0,
    pitch_status=None,
    events=(),
    command_result=None,
    effect_chain_status=None,
):
    metadata = {"current_pitch_semitones": semitones}
    if pitch_status is not None:
        metadata["pitch_buffer_status"] = pitch_status
    return TelemetrySnapshot(
        latest_status="",
        recent_events=tuple(events),
        last_command_result=command_result,
        audio_running=audio_running,
        route_status=route_status,
        effect_chain_status=effect_chain_status,
        metadata=metadata,
    )


def signalsmith_status(semitones, latency=2.666):
    return {
        "backend": "signalsmith",
        "backend_status": "active",
        "backend_available": True,
        "fallback_active": False,
        "estimated_added_ms": latency,
        "configured_block_size": 1024,
        "configured_interval_size": 1024,
        "input_latency_frames": 64,
        "output_latency_frames": 64,
        "latency_frames": 128,
        "last_backend_error": "",
    }


class M61OperatorProjectionTests(unittest.TestCase):
    def test_initial_stopped_state(self):
        status = build_operator_status(snapshot(), "stopped")

        self.assertEqual(status.processing, "Stopped")
        self.assertEqual(status.route, "Routes stopped")
        self.assertTrue(status.start_enabled)
        self.assertFalse(status.stop_enabled)

    def test_running_processing_state(self):
        status = build_operator_status(
            snapshot(audio_running=True, route_status="running"),
            "running",
            {"virtual_mic_active": True},
        )

        self.assertEqual(status.processing, "Running")
        self.assertFalse(status.start_enabled)
        self.assertTrue(status.stop_enabled)

    def test_stopped_route_state(self):
        status = build_operator_status(snapshot(route_status="stopped"), "stopped")

        self.assertEqual(status.route, "Routes stopped")

    def test_virtual_mic_only_route_presentation(self):
        status = build_operator_status(
            snapshot(audio_running=True, route_status="running"),
            "running",
            {"virtual_mic_active": True, "monitor_active": False},
        )

        self.assertEqual(status.route, "Virtual mic active")

    def test_virtual_mic_plus_monitor_route_presentation(self):
        status = build_operator_status(
            snapshot(audio_running=True, route_status="running"),
            "running",
            {"virtual_mic_active": True, "monitor_active": True},
        )

        self.assertEqual(status.route, "Virtual mic and monitor active")

    def test_pitch_off_at_zero_semitones_is_not_error(self):
        status = build_operator_status(
            snapshot(
                semitones=0,
                pitch_status={"backend": "none", "backend_status": "bypassed"},
            ),
            "stopped",
        )

        self.assertEqual(status.pitch, "Pitch: Off")
        self.assertEqual(status.actionable_status, "")

    def test_signalsmith_ready_available_state(self):
        status = build_operator_status(
            snapshot(
                semitones=4,
                pitch_status={
                    "backend": "signalsmith",
                    "backend_status": "available",
                    "fallback_active": False,
                    "estimated_added_ms": 0.0,
                },
            ),
            "stopped",
        )

        self.assertEqual(status.pitch, "Pitch: Signalsmith ready (+4 semitones)")

    def test_signalsmith_active_at_positive_pitch(self):
        status = build_operator_status(
            snapshot(semitones=4, pitch_status=signalsmith_status(4)),
            "running",
        )

        self.assertEqual(status.pitch, "Pitch: Signalsmith (+4 semitones)")

    def test_signalsmith_active_at_negative_pitch(self):
        status = build_operator_status(
            snapshot(semitones=-4, pitch_status=signalsmith_status(-4)),
            "running",
        )

        self.assertEqual(status.pitch, "Pitch: Signalsmith (-4 semitones)")

    def test_pedalboard_fallback_warning(self):
        status = build_operator_status(
            snapshot(
                semitones=4,
                pitch_status={
                    "backend": "pedalboard",
                    "backend_status": "fallback_active",
                    "fallback_active": True,
                    "estimated_added_ms": 21.333,
                },
            ),
            "running",
        )

        self.assertEqual(status.pitch, "Pitch: Pedalboard fallback (+4 semitones)")
        self.assertIn("Pedalboard fallback active", status.actionable_status)

    def test_no_backend_error_with_nonzero_pitch(self):
        status = build_operator_status(
            snapshot(
                semitones=4,
                pitch_status={
                    "backend": "none",
                    "backend_status": "native_module_missing",
                    "fallback_active": False,
                    "last_backend_error": "missing",
                },
            ),
            "running",
        )

        self.assertEqual(status.pitch, "Pitch: Unavailable")
        self.assertEqual(status.actionable_status, "No usable pitch backend")

    def test_backend_runtime_error_presentation(self):
        chain_status = EffectChainStatus(
            chain_order=("Pitch Shift",),
            active_effects=(),
            disabled_effects=(),
            runtime_bypassed_effects=("Pitch Shift",),
            failed_effects=("Pitch Shift",),
            failures=(EffectFailureStatus("Pitch Shift", "backend exploded"),),
        )
        status = build_operator_status(
            snapshot(semitones=4, pitch_status=signalsmith_status(4), effect_chain_status=chain_status),
            "running",
        )

        self.assertEqual(status.pitch, "Pitch: Unavailable")
        self.assertIn("backend exploded", status.actionable_status)

    def test_estimated_dsp_latency_formatting(self):
        status = build_operator_status(
            snapshot(semitones=4, pitch_status=signalsmith_status(4, latency=2.666)),
            "running",
        )

        self.assertEqual(status.latency, "Estimated pitch DSP latency: 2.7 ms")

    def test_latency_is_not_described_as_round_trip(self):
        status = build_operator_status(
            snapshot(semitones=4, pitch_status=signalsmith_status(4)),
            "running",
        )

        self.assertNotIn("round-trip", status.latency.lower())
        self.assertIn("pitch DSP latency", status.latency)

    def test_last_actionable_error_remains_visible(self):
        events = (
            make_event("route.start_failed", "error", "Virtual microphone route failed"),
            make_event("command.apply_effect_parameters", "info", "apply succeeded"),
        )
        status = build_operator_status(snapshot(events=events), "failed")

        self.assertEqual(status.actionable_status, "Virtual microphone route failed")

    def test_successful_command_status_is_separate_from_error_state(self):
        events = (make_event("route.start_failed", "error", "Audio start failed"),)
        status = build_operator_status(
            snapshot(events=events, command_result=CommandResult.ok("Preset saved")),
            "failed",
        )

        self.assertEqual(status.command_status, "Preset saved")
        self.assertEqual(status.actionable_status, "Audio start failed")


class SignalStub:
    def connect(self, slot):
        self.slot = slot


class FakeOperatorService:
    def __init__(self, statuses=None, fail_refresh=False):
        self.status_changed = SignalStub()
        self.preset_selected = SignalStub()
        self.statuses = list(statuses or [])
        self.fail_refresh = fail_refresh
        self.operator_status_calls = 0
        self.start_calls = 0
        self.stop_calls = 0
        self.apply_calls = 0
        self.closed = False

    def devices(self):
        return [
            {"name": "Mic", "max_input_channels": 1, "max_output_channels": 0},
            {"name": "Cable", "max_input_channels": 0, "max_output_channels": 2},
            {"name": "Monitor", "max_input_channels": 0, "max_output_channels": 2},
        ]

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
        return CommandResult.ok(f"Played: {filename}")

    def play_sound_by_index(self, index):
        return CommandResult.ok(f"Played index {index}")

    def save_preset(self, name, params):
        return CommandResult.ok("Saved")

    def delete_preset(self, name):
        return CommandResult.ok("Deleted")

    def start_audio(self, input_id, output_id, monitor_id=None):
        self.start_calls += 1
        return CommandResult.ok("Running")

    def stop_audio(self):
        self.stop_calls += 1
        return CommandResult.ok("Stopped")

    def operator_status(self):
        self.operator_status_calls += 1
        if self.fail_refresh:
            raise RuntimeError("refresh failed")
        if self.statuses:
            return self.statuses[-1]
        return build_operator_status(snapshot(), "stopped")


class M61OperatorUiTests(unittest.TestCase):
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

    def test_start_stop_enabled_state_transitions(self):
        stopped = build_operator_status(snapshot(), "stopped")
        running = build_operator_status(
            snapshot(audio_running=True, route_status="running"),
            "running",
            {"virtual_mic_active": True},
        )
        service = FakeOperatorService([stopped])
        window = self.make_window(service)

        self.assertTrue(window.start_button.isEnabled())
        self.assertFalse(window.stop_button.isEnabled())

        service.statuses[:] = [running]
        window.refresh_operator_status()

        self.assertFalse(window.start_button.isEnabled())
        self.assertTrue(window.stop_button.isEnabled())

    def test_failed_start_restores_usable_controls(self):
        failed = build_operator_status(snapshot(route_status="error"), "failed")
        service = FakeOperatorService([failed])
        window = self.make_window(service)

        self.assertTrue(window.start_button.isEnabled())
        self.assertFalse(window.stop_button.isEnabled())
        self.assertEqual(window.processing_status.text(), "Processing: Error")

    def test_failed_telemetry_refresh_does_not_crash_ui(self):
        service = FakeOperatorService(fail_refresh=True)
        window = self.make_window(service)

        window.refresh_operator_status()

        self.assertIn("Status unavailable", window.processing_status.text())
        self.assertIn("Status refresh failed", window.warning_status.text())

    def test_timer_stops_during_close(self):
        service = FakeOperatorService()
        window = self.make_window(service)

        self.assertTrue(window.status_timer.isActive())
        window.close()
        self.qt_app.processEvents()

        self.assertFalse(window.status_timer.isActive())
        self.assertTrue(service.closed)

    def test_ui_obtains_state_only_through_service_projection(self):
        service = FakeOperatorService()
        window = self.make_window(service)

        window.refresh_operator_status()

        self.assertGreaterEqual(service.operator_status_calls, 1)

    def test_existing_controls_still_call_service(self):
        service = FakeOperatorService()
        window = self.make_window(service)

        window.apply_current_parameters()
        window.start()
        window.stop()

        self.assertGreater(service.apply_calls, 0)
        self.assertEqual(service.start_calls, 1)
        self.assertEqual(service.stop_calls, 1)

    def test_offscreen_ui_construction_and_close(self):
        service = FakeOperatorService()
        window = self.make_window(service)

        self.assertEqual(window.windowTitle(), "VoiceLab")
        window.close()
        self.qt_app.processEvents()
        self.assertTrue(service.closed)


if __name__ == "__main__":
    unittest.main()
