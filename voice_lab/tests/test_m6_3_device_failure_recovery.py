import os
import unittest

from voice_lab.app.commands import CommandResult
from voice_lab.app.service import ApplicationService
from voice_lab.engine.audio_engine import AudioEngine
from voice_lab.io.device_errors import DeviceFailure, DeviceFailureError
from voice_lab.io.router import Router
from voice_lab.plugins import PluginManager
from voice_lab.telemetry import TelemetryService


class FakeAudioIO:
    def __init__(self, devices=None, fail_monitor=None, fail_duplex=None, close_raises=False):
        self.devices = devices if devices is not None else [
            {"name": "Mic", "max_input_channels": 1, "max_output_channels": 0},
            {"name": "Cable", "max_input_channels": 0, "max_output_channels": 2},
            {"name": "Monitor", "max_input_channels": 0, "max_output_channels": 2},
        ]
        self.fail_monitor = fail_monitor
        self.fail_duplex = fail_duplex
        self.close_raises = close_raises
        self.monitor_opened = False
        self.duplex_opened = False
        self.closed = 0

    def query_devices(self):
        return self.devices

    def open_output_stream(self, output_id, callback):
        self.monitor_opened = True
        if self.fail_monitor is not None:
            raise self.fail_monitor

    def open_duplex_stream(self, input_id, output_id, callback):
        self.duplex_opened = True
        if self.fail_duplex is not None:
            raise self.fail_duplex

    def close(self):
        self.closed += 1
        self.monitor_opened = False
        self.duplex_opened = False
        if self.close_raises:
            raise RuntimeError("cleanup failed")


class FakeRouter:
    def __init__(self, failures=None):
        self.failures = list(failures or [])
        self.starts = []
        self.stops = 0

    def start(self, engine, mixer, input_id, output_id, monitor_id=None, monitor_enabled=None):
        self.starts.append((input_id, output_id, monitor_id))
        if self.failures:
            failure = self.failures.pop(0)
            if isinstance(failure, Exception):
                raise failure
            raise DeviceFailureError(failure)

    def stop(self):
        self.stops += 1


class FakeConfig:
    def validate_effect_parameters(self, gain, robot, lowpass, pitch=0.0):
        from voice_lab.config.validation import validate_effect_parameters

        return validate_effect_parameters(gain, robot, lowpass, pitch)

    def preset_names(self):
        return ["Clean", "Deep Voice"]

    def select_preset(self, name):
        from voice_lab.config.service import PresetSelectionResult
        from voice_lab.config.validation import validate_preset_parameters

        validation = validate_preset_parameters(
            {"gain": 10, "robot": 0, "lowpass": 4000, "pitch": 0}
        )
        return PresetSelectionResult(
            True,
            preset=validation.preset,
            effect_parameters=validation.effect_parameters,
        )

    def save_preset(self, name, params):
        return CommandResult.ok("Saved")

    def delete_preset(self, name):
        return CommandResult.ok("Deleted")

    def flush(self):
        pass


class FakeHotkeys:
    def __init__(self):
        self.status_signal = self
        self.commands = None

    def connect(self, slot):
        self.slot = slot

    def set_commands(self, commands):
        self.commands = commands

    def register(self):
        pass

    def unregister(self):
        pass


class FakeSoundboard:
    def set_commands(self, commands):
        self.commands = commands


def service(router=None, audio_io=None):
    return ApplicationService(
        telemetry=TelemetryService(),
        plugins=PluginManager(),
        engine=AudioEngine(),
        router=router or FakeRouter(),
        audio_io=audio_io or FakeAudioIO(),
        config=FakeConfig(),
        hotkeys=FakeHotkeys(),
        soundboard=FakeSoundboard(),
    )


class M63DeviceFailureRecoveryTests(unittest.TestCase):
    def test_missing_input_selection(self):
        result = service().start_audio(None, 1)

        self.assertFalse(result.success)
        self.assertEqual(result.metadata["failure"]["category"], "missing_selection")
        self.assertEqual(result.metadata["failure"]["role"], "input")
        self.assertEqual(result.message, "Select a microphone input before starting processing.")

    def test_missing_virtual_output_selection(self):
        result = service().start_audio(0, None)

        self.assertFalse(result.success)
        self.assertEqual(result.metadata["failure"]["role"], "virtual_output")
        self.assertEqual(result.message, "Select a virtual microphone output before starting processing.")

    def test_monitor_enabled_without_monitor_selection(self):
        svc = service()
        svc.apply_effect_parameters(1.0, 0.0, 4000, True, 0.35, 0.7, pitch=0)
        result = svc.start_audio(0, 1, None)

        self.assertFalse(result.success)
        self.assertEqual(result.metadata["failure"]["role"], "monitor_output")
        self.assertEqual(result.message, "Select a monitor output device or disable monitor output.")

    def test_input_device_not_found_classification(self):
        audio_io = FakeAudioIO()
        result = service(router=Router(audio_io), audio_io=audio_io).start_audio(99, 1)

        self.assertFalse(result.success)
        self.assertEqual(result.metadata["failure"]["category"], "device_not_found")
        self.assertEqual(result.metadata["failure"]["role"], "input")

    def test_output_device_not_found_classification(self):
        audio_io = FakeAudioIO()
        result = service(router=Router(audio_io), audio_io=audio_io).start_audio(0, 99)

        self.assertFalse(result.success)
        self.assertEqual(result.metadata["failure"]["category"], "device_not_found")
        self.assertEqual(result.metadata["failure"]["role"], "virtual_output")

    def test_monitor_device_not_found_classification(self):
        audio_io = FakeAudioIO()
        svc = service(router=Router(audio_io), audio_io=audio_io)
        svc.apply_effect_parameters(1.0, 0.0, 4000, True, 0.35, 0.7, pitch=0)
        result = svc.start_audio(0, 1, 99)

        self.assertFalse(result.success)
        self.assertEqual(result.metadata["failure"]["category"], "device_not_found")
        self.assertEqual(result.metadata["failure"]["role"], "monitor_output")

    def test_generic_input_open_failure(self):
        failure = DeviceFailure(
            category="device_open_failed",
            role="input",
            selected_device_id=0,
            technical_detail="PortAudioError: input traceback detail",
        )
        result = service(router=FakeRouter([failure])).start_audio(0, 1)

        self.assertFalse(result.success)
        self.assertIn("microphone could not be opened", result.message)
        self.assertNotIn("PortAudioError", result.message)

    def test_generic_output_open_failure(self):
        failure = DeviceFailure(
            category="device_open_failed",
            role="virtual_output",
            selected_device_id=1,
            technical_detail="PortAudioError: output trace",
        )
        result = service(router=FakeRouter([failure])).start_audio(0, 1)

        self.assertFalse(result.success)
        self.assertIn("virtual microphone output could not be opened", result.message)

    def test_generic_monitor_open_failure(self):
        failure = DeviceFailure(
            category="device_open_failed",
            role="monitor_output",
            selected_device_id=2,
            technical_detail="PortAudioError: monitor trace",
        )
        svc = service(router=FakeRouter([failure]))
        svc.apply_effect_parameters(1.0, 0.0, 4000, True, 0.35, 0.7, pitch=0)
        result = svc.start_audio(0, 1, 2)

        self.assertFalse(result.success)
        self.assertIn("monitor output could not be opened", result.message)
        self.assertTrue(svc.current_monitor_enabled)

    def test_unsupported_configuration(self):
        audio_io = FakeAudioIO(devices=[
            {"name": "NoInput", "max_input_channels": 0, "max_output_channels": 0},
            {"name": "Cable", "max_input_channels": 0, "max_output_channels": 2},
        ])
        result = service(router=Router(audio_io), audio_io=audio_io).start_audio(0, 1)

        self.assertFalse(result.success)
        self.assertEqual(result.metadata["failure"]["category"], "unsupported_configuration")

    def test_unknown_startup_failure_fallback_wording(self):
        result = service(router=FakeRouter([RuntimeError("raw backend object traceback")])).start_audio(0, 1)

        self.assertFalse(result.success)
        self.assertEqual(
            result.message,
            "VoiceLab could not start audio processing. Check the selected devices and try again.",
        )
        self.assertNotIn("traceback", result.message)

    def test_unknown_device_error_category_uses_safe_fallback_wording(self):
        result = service(
            router=FakeRouter([
                DeviceFailure(
                    category="unknown_device_error",
                    role="route",
                    technical_detail="raw device backend traceback",
                )
            ])
        ).start_audio(0, 1)

        self.assertFalse(result.success)
        self.assertEqual(result.metadata["failure"]["category"], "unknown_device_error")
        self.assertEqual(
            result.message,
            "VoiceLab could not start audio processing. Check the selected devices and try again.",
        )
        self.assertNotIn("traceback", result.message)

    def test_technical_detail_retained_in_telemetry(self):
        result = service(
            router=FakeRouter([
                DeviceFailure(
                    category="device_open_failed",
                    role="input",
                    technical_detail="PortAudio backend detail",
                )
            ])
        ).start_audio(0, 1)

        failure = result.metadata["failure"]
        self.assertEqual(failure["technical_detail"], "PortAudio backend detail")

    def test_failed_start_reports_not_running_and_routes_not_active(self):
        svc = service(router=FakeRouter([DeviceFailure("device_open_failed", "input")]))
        svc.start_audio(0, 1)
        status = svc.operator_status()

        self.assertEqual(status.processing, "Error")
        self.assertEqual(status.route, "Route error")
        self.assertTrue(status.start_enabled)
        self.assertFalse(status.stop_enabled)

    def test_partial_start_resources_are_closed(self):
        audio_io = FakeAudioIO(fail_duplex=DeviceFailureError(DeviceFailure("device_open_failed", "route")))
        router = Router(audio_io)

        with self.assertRaises(DeviceFailureError):
            router.start(object(), object(), 0, 1, 2, monitor_enabled=lambda: True)

        self.assertGreaterEqual(audio_io.closed, 2)
        self.assertFalse(audio_io.monitor_opened)

    def test_partial_start_cleanup_failure_is_classified(self):
        audio_io = FakeAudioIO(
            fail_duplex=DeviceFailureError(DeviceFailure("device_open_failed", "route")),
        )
        close_calls = {"count": 0}

        def fail_second_close():
            close_calls["count"] += 1
            audio_io.monitor_opened = False
            audio_io.duplex_opened = False
            if close_calls["count"] > 1:
                raise RuntimeError("cleanup failed")

        audio_io.close = fail_second_close
        router = Router(audio_io)

        with self.assertRaises(DeviceFailureError) as context:
            router.start(object(), object(), 0, 1, 2, monitor_enabled=lambda: True)

        self.assertEqual(context.exception.failure.category, "partial_start_cleanup_failed")

    def test_repeated_stop_after_failure_is_safe(self):
        svc = service(router=FakeRouter([DeviceFailure("device_open_failed", "input")]))
        svc.start_audio(0, 1)
        result = svc.stop_audio()

        self.assertTrue(result.success)
        self.assertEqual(result.message, "Already stopped")
        self.assertEqual(svc.operator_status().actionable_status, "The selected microphone could not be opened. Check that it is connected and not being used exclusively by another application.")

    def test_retry_succeeds_after_initial_failure_and_clears_primary_failure(self):
        router = FakeRouter([DeviceFailure("device_open_failed", "virtual_output")])
        svc = service(router=router)
        failed = svc.start_audio(0, 1)
        retried = svc.start_audio(0, 1)

        self.assertFalse(failed.success)
        self.assertTrue(retried.success)
        self.assertEqual(svc.operator_status().processing, "Running")
        self.assertEqual(svc.operator_status().actionable_status, "")
        self.assertEqual(router.starts, [(0, 1, None), (0, 1, None)])

    def test_failure_history_remains_in_telemetry_after_successful_retry(self):
        router = FakeRouter([DeviceFailure("device_open_failed", "virtual_output")])
        svc = service(router=router)
        svc.start_audio(0, 1)
        svc.start_audio(0, 1)
        events = svc.telemetry_snapshot().recent_events

        self.assertTrue(any(event.event_type == "route.start_failed" for event in events))

    def test_no_automatic_replacement_device_is_chosen(self):
        router = FakeRouter([DeviceFailure("device_not_found", "input", selected_device_id=7)])
        svc = service(router=router)
        result = svc.start_audio(7, 1)

        self.assertFalse(result.success)
        self.assertEqual(router.starts, [(7, 1, None)])

    def test_monitor_failure_does_not_silently_disable_monitoring(self):
        router = FakeRouter([DeviceFailure("device_open_failed", "monitor_output")])
        svc = service(router=router)
        svc.apply_effect_parameters(1.0, 0.0, 4000, True, 0.35, 0.7, pitch=0)
        svc.start_audio(0, 1, 2)

        self.assertTrue(svc.current_monitor_enabled)

    def test_polling_continues_after_start_failure(self):
        svc = service(router=FakeRouter([DeviceFailure("device_open_failed", "input")]))
        svc.start_audio(0, 1)

        self.assertEqual(svc.operator_status().processing, "Error")
        self.assertIn("microphone", svc.operator_status().actionable_status)

    def test_offscreen_ui_start_failure_refresh_close(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from voice_lab.ui.main_window import App

        app = QApplication.instance() or QApplication([])
        svc = service(router=FakeRouter([DeviceFailure("device_open_failed", "input")]))
        window = App(svc, on_close=lambda: None)
        self.addCleanup(window.close)
        window.input_box.setCurrentIndex(1)
        window.output_box.setCurrentIndex(1)

        window.start()
        window.refresh_operator_status()

        self.assertIn("could not be opened", window.warning_status.text())
        self.assertTrue(window.start_button.isEnabled())
        self.assertFalse(window.stop_button.isEnabled())
        window.close()
        app.processEvents()


if __name__ == "__main__":
    unittest.main()
