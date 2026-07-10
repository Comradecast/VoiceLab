import os
import threading
import unittest
from unittest.mock import patch

import numpy as np

from voice_lab.app.lifecycle import ApplicationLifecycle
from voice_lab.app.service import ApplicationService
from voice_lab.effects.signalsmith_backend import SignalsmithBackendStatus
from voice_lab.engine.audio_engine import AudioEngine
from voice_lab.io.audio_io import AudioIO
from voice_lab.plugins import PluginManager
from voice_lab.telemetry import TelemetryService


class FakeStream:
    def __init__(self, fail_stop=False, fail_close=False):
        self.fail_stop = fail_stop
        self.fail_close = fail_close
        self.stopped = False
        self.closed = False

    def stop(self):
        self.stopped = True
        if self.fail_stop:
            raise RuntimeError("stop failed")

    def close(self):
        self.closed = True
        if self.fail_close:
            raise RuntimeError("close failed")


class FakeRouter:
    def __init__(self, audio_io=None, fail_start=False):
        self.audio_io = audio_io
        self.fail_start = fail_start
        self.starts = 0
        self.stops = 0
        self.running = False

    def start(self, *args, **kwargs):
        self.starts += 1
        if self.fail_start:
            raise RuntimeError("route unavailable")
        self.running = True

    def stop(self):
        self.stops += 1
        self.running = False


class FakeConfig:
    def __init__(self):
        self.flush_count = 0

    def validate_effect_parameters(self, gain, robot, lowpass, pitch=0.0):
        from voice_lab.config.validation import validate_effect_parameters

        return validate_effect_parameters(gain, robot, lowpass, pitch)

    def preset_names(self):
        return ["Clean", "Deep Voice"]

    def select_preset(self, name):
        from voice_lab.config.service import PresetSelectionResult
        from voice_lab.config.validation import validate_preset_parameters

        presets = {
            "Clean": {"gain": 10, "robot": 0, "lowpass": 4000, "pitch": 0},
            "Deep Voice": {"gain": 9, "robot": 0, "lowpass": 2200, "pitch": -4},
        }
        validation = validate_preset_parameters(presets[name])
        return PresetSelectionResult(
            True,
            preset=validation.preset,
            effect_parameters=validation.effect_parameters,
        )

    def flush(self):
        self.flush_count += 1


class FakeHotkeys:
    def __init__(self):
        self.commands = None
        self.register_count = 0
        self.unregister_count = 0
        self.status_signal = self

    def connect(self, slot):
        self._slot = slot

    def set_commands(self, commands):
        self.commands = commands

    def register(self):
        self.register_count += 1

    def unregister(self):
        self.unregister_count += 1


class FakeSignalsmithBackend:
    def __init__(self, sample_rate, block_size, channels=1):
        self.semitones = 0.0
        self.closed = False

    def set_semitones(self, semitones):
        self.semitones = float(semitones)

    def process(self, samples):
        return np.asarray(samples, dtype=np.float32)

    def reset(self):
        pass

    def latency_frames(self):
        return 128

    def input_latency_frames(self):
        return 64

    def output_latency_frames(self):
        return 64

    def close(self):
        self.closed = True


def _available_status():
    return SignalsmithBackendStatus(True, "signalsmith", "active")


def _block():
    return np.linspace(-0.25, 0.25, 1024, dtype=np.float32)


class M55LifecycleReadinessTests(unittest.TestCase):
    def test_service_start_stop_and_restart(self):
        router = FakeRouter()
        service = ApplicationService(
            telemetry=TelemetryService(),
            plugins=PluginManager(),
            engine=AudioEngine(),
            router=router,
        )

        self.assertTrue(service.start_audio(0, 1).success)
        self.assertTrue(service.stop_audio().success)
        self.assertTrue(service.start_audio(0, 1).success)
        self.assertTrue(service.stop_audio().success)
        self.assertEqual(router.starts, 2)
        self.assertEqual(router.stops, 2)

    def test_idempotent_stop_behavior_and_resource_closure(self):
        stream = FakeStream()
        monitor = FakeStream()
        audio_io = AudioIO()
        audio_io.stream = stream
        audio_io.monitor_stream = monitor

        audio_io.close()
        audio_io.close()

        self.assertTrue(stream.stopped)
        self.assertTrue(stream.closed)
        self.assertTrue(monitor.stopped)
        self.assertTrue(monitor.closed)
        self.assertIsNone(audio_io.stream)
        self.assertIsNone(audio_io.monitor_stream)

    def test_partial_startup_failure_cleanup_and_retry(self):
        created = {"router": None, "attempts": 0}

        def router_factory(audio_io):
            created["router"] = FakeRouter(audio_io)
            return created["router"]

        def service_factory(**kwargs):
            created["attempts"] += 1
            if created["attempts"] == 1:
                raise RuntimeError("service construction failed")
            return ApplicationService(**kwargs)

        lifecycle = ApplicationLifecycle(
            router_factory=router_factory,
            service_factory=service_factory,
            hotkey_factory=FakeHotkeys,
        )

        with self.assertRaises(RuntimeError):
            lifecycle.startup()
        self.assertIsNone(lifecycle.state.service)
        self.assertEqual(created["router"].stops, 1)

        service = lifecycle.startup()
        self.assertIsNotNone(service)

    def test_startup_failure_followed_by_successful_route_retry(self):
        router = FakeRouter(fail_start=True)
        service = ApplicationService(
            telemetry=TelemetryService(),
            plugins=PluginManager(),
            engine=AudioEngine(),
            router=router,
        )

        failed = service.start_audio(0, 1)
        router.fail_start = False
        retried = service.start_audio(0, 1)

        self.assertFalse(failed.success)
        self.assertTrue(retried.success)
        self.assertEqual(service.telemetry_snapshot().route_status, "running")

    def test_lifecycle_flushes_telemetry_and_configuration(self):
        configs = []

        def config_factory():
            config = FakeConfig()
            configs.append(config)
            return config

        lifecycle = ApplicationLifecycle(config_factory=config_factory, hotkey_factory=FakeHotkeys)
        service = lifecycle.startup()
        lifecycle.shutdown()

        self.assertIsNone(lifecycle.state.service)
        self.assertIn("flush_telemetry", lifecycle.state.shutdown_steps)
        self.assertIn("save_configuration", lifecycle.state.shutdown_steps)
        self.assertEqual(configs[0].flush_count, 1)
        self.assertFalse(service.telemetry_snapshot().audio_running)

    def test_shutdown_with_buffered_pitch_state_keeps_telemetry_readable(self):
        with (
            patch("voice_lab.effects.pitch_shift.signalsmith_status", _available_status),
            patch("voice_lab.effects.pitch_shift.SignalsmithPitchBackend", FakeSignalsmithBackend),
        ):
            service = ApplicationService(
                telemetry=TelemetryService(),
                plugins=PluginManager(),
                engine=AudioEngine(),
                router=FakeRouter(),
            )
            service.apply_effect_parameters(1.0, 0.0, 4000, False, 0.35, 0.7, pitch=4.0)
            service.engine.process_voice(_block(), 1024)
            self.assertTrue(service.stop_audio().success)
            snapshot = service.telemetry_snapshot()

        self.assertEqual(snapshot.metadata["pitch_buffer_status"]["backend"], "signalsmith")
        self.assertEqual(snapshot.metadata["pitch_buffer_status"]["backend_status"], "active")

    def test_shutdown_with_monitor_enabled_and_disabled(self):
        router = FakeRouter()
        service = ApplicationService(
            telemetry=TelemetryService(),
            plugins=PluginManager(),
            engine=AudioEngine(),
            router=router,
        )

        service.apply_effect_parameters(1.0, 0.0, 4000, False, 0.35, 0.7, pitch=0.0)
        self.assertTrue(service.start_audio(0, 1, None).success)
        self.assertTrue(service.stop_audio().success)

        service.apply_effect_parameters(1.0, 0.0, 4000, True, 0.35, 0.7, pitch=0.0)
        self.assertTrue(service.start_audio(0, 1, 2).success)
        self.assertTrue(service.stop_audio().success)
        self.assertEqual(router.starts, 2)

    def test_ui_close_routes_through_lifecycle(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        from voice_lab.ui.main_window import App

        app = QApplication.instance() or QApplication([])
        lifecycle = ApplicationLifecycle(hotkey_factory=FakeHotkeys)
        service = lifecycle.startup()
        window = App(service, on_close=lifecycle.shutdown)

        window.close()
        app.processEvents()

        self.assertIsNone(lifecycle.state.service)
        self.assertIn("stop_audio", lifecycle.state.shutdown_steps)

    def test_no_duplicate_engine_or_plugin_initialization_after_restart(self):
        counts = {"engine": 0, "plugins": 0}

        def engine_factory():
            counts["engine"] += 1
            return AudioEngine()

        def plugin_factory(**kwargs):
            counts["plugins"] += 1
            return PluginManager(**kwargs)

        lifecycle = ApplicationLifecycle(
            engine_factory=engine_factory,
            plugin_manager_factory=plugin_factory,
            hotkey_factory=FakeHotkeys,
        )

        first = lifecycle.startup()
        self.assertIs(first, lifecycle.startup())
        lifecycle.shutdown()
        second = lifecycle.startup()

        self.assertIsNot(first, second)
        self.assertEqual(counts["engine"], 2)
        self.assertEqual(counts["plugins"], 2)

    def test_no_surviving_non_daemon_application_threads_after_shutdown(self):
        before = {
            thread.ident
            for thread in threading.enumerate()
            if thread.is_alive() and not thread.daemon
        }
        lifecycle = ApplicationLifecycle(hotkey_factory=FakeHotkeys)
        lifecycle.startup()
        lifecycle.shutdown()
        after = {
            thread.ident
            for thread in threading.enumerate()
            if thread.is_alive() and not thread.daemon
        }

        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
