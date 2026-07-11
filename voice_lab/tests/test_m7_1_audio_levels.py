import ast
import os
import unittest
from pathlib import Path

import numpy as np

from voice_lab.audio_levels import (
    AudioLevelMonitor,
    AudioLevelSnapshot,
    DBFS_FLOOR,
    LevelReading,
    calculate_level_reading,
)
from voice_lab.app.commands import CommandResult
from voice_lab.app.service import ApplicationService
from voice_lab.config.service import ConfigurationService
from voice_lab.config.settings import validate_settings_document
from voice_lab.core import AudioContext, AudioFrame, AuxiliaryAudio
from voice_lab.engine.audio_engine import AudioEngine
from voice_lab.io.capture import Capture
from voice_lab.io.router import Router
from voice_lab.mixer import Mixer
from voice_lab.plugins import PluginManager
from voice_lab.telemetry import TelemetryService
from voice_lab.tests.test_m6_3_device_failure_recovery import FakeHotkeys, FakeRouter, FakeSoundboard
from voice_lab.tests.test_m6_5_operator_settings import SettingsAudioIO
from voice_lab.ui.level_display import LevelDisplayModel, db_to_percent


def frame(samples, stage="capture"):
    samples = np.asarray(samples, dtype=np.float32)
    context = AudioContext(
        sample_rate=48000,
        block_size=samples.shape[0],
        frame_count=samples.shape[0],
        sample_format="float32",
        input_channel_count=1,
        output_channel_count=1 if samples.ndim == 1 else samples.shape[1],
        processing_stage=stage,
    )
    return AudioFrame(
        samples=samples,
        sample_rate=48000,
        channel_count=context.output_channel_count,
        frame_count=context.frame_count,
        sample_format="float32",
        context=context,
    )


def config():
    return ConfigurationService(
        load_func=lambda: {
            "Natural": {"gain": 10, "robot": 0, "lowpass": 4000, "pitch": 0},
            "Custom": {"gain": 12, "robot": 0, "lowpass": 4000, "pitch": 0},
        },
        save_func=lambda presets: None,
        settings_load_func=lambda: validate_settings_document({"schema_version": 1}),
        settings_save_func=lambda settings: None,
    )


def service(router=None, telemetry=None):
    return ApplicationService(
        telemetry=telemetry or TelemetryService(),
        config=config(),
        plugins=PluginManager(),
        engine=AudioEngine(),
        audio_io=SettingsAudioIO(),
        router=router or FakeRouter(),
        hotkeys=FakeHotkeys(),
        soundboard=FakeSoundboard(),
    )


class M71MeterMathTests(unittest.TestCase):
    def test_silence_produces_floor(self):
        reading = calculate_level_reading(np.zeros(8, dtype=np.float32))

        self.assertEqual(reading.rms_dbfs, DBFS_FLOOR)
        self.assertEqual(reading.peak_dbfs, DBFS_FLOOR)
        self.assertFalse(reading.signal_present)

    def test_full_scale_and_half_scale_dbfs(self):
        full = calculate_level_reading(np.array([1.0], dtype=np.float32))
        half = calculate_level_reading(np.array([0.5], dtype=np.float32))

        self.assertAlmostEqual(full.peak_dbfs, 0.0, places=3)
        self.assertAlmostEqual(half.peak_dbfs, -6.0206, places=2)

    def test_known_rms_negative_and_multichannel_values(self):
        reading = calculate_level_reading(np.array([[0.5, -0.5], [0.5, -0.5]], dtype=np.float32))

        self.assertAlmostEqual(reading.rms_dbfs, -6.0206, places=2)
        self.assertAlmostEqual(reading.peak_dbfs, -6.0206, places=2)

    def test_empty_nan_and_infinity_fail_safely(self):
        for samples in (
            np.array([], dtype=np.float32),
            np.array([np.nan], dtype=np.float32),
            np.array([np.inf], dtype=np.float32),
            np.array([-np.inf], dtype=np.float32),
        ):
            with self.subTest(samples=samples):
                reading = calculate_level_reading(samples)
                self.assertTrue(np.isfinite(reading.rms_dbfs))
                self.assertTrue(np.isfinite(reading.peak_dbfs))

    def test_meter_does_not_mutate_input_or_audio_output(self):
        samples = np.array([0.25, -0.5, 0.75], dtype=np.float32)
        before = samples.copy()

        reading = calculate_level_reading(samples)

        self.assertIsInstance(reading, LevelReading)
        self.assertTrue(np.array_equal(samples, before))


class M71SnapshotTests(unittest.TestCase):
    def test_default_snapshot_is_immutable_and_stopped(self):
        monitor = AudioLevelMonitor()
        snapshot = monitor.snapshot()

        self.assertIsInstance(snapshot, AudioLevelSnapshot)
        self.assertEqual(snapshot.processing_state, "stopped")
        with self.assertRaises(Exception):
            snapshot.sequence = 9

    def test_sequence_increases_and_only_latest_is_retained(self):
        clock = {"now": 1.0}
        monitor = AudioLevelMonitor(publication_hz=0, clock=lambda: clock["now"])

        first = monitor.publish(input_frame=frame([0.1]))
        clock["now"] = 2.0
        second = monitor.publish(input_frame=frame([0.5]))

        self.assertGreater(second.sequence, first.sequence)
        self.assertEqual(monitor.snapshot().sequence, second.sequence)
        self.assertAlmostEqual(monitor.snapshot().input.peak_dbfs, -6.0206, places=2)

    def test_publication_cadence_is_bounded(self):
        clock = {"now": 1.0}
        monitor = AudioLevelMonitor(publication_hz=25, clock=lambda: clock["now"])

        first = monitor.publish(input_frame=frame([0.1]))
        second = monitor.publish(input_frame=frame([0.9]))
        clock["now"] += 0.05
        third = monitor.publish(input_frame=frame([0.9]))

        self.assertEqual(second.sequence, first.sequence)
        self.assertGreater(third.sequence, second.sequence)

    def test_no_raw_array_is_exposed(self):
        monitor = AudioLevelMonitor(publication_hz=0, clock=lambda: 1.0)
        snapshot = monitor.publish(input_frame=frame([0.25]))

        self.assertIsInstance(snapshot.input, LevelReading)
        self.assertFalse(hasattr(snapshot.input, "samples"))


class M71PipelineStageTests(unittest.TestCase):
    def test_router_publishes_truthful_callback_stages(self):
        class FakeAudioIO:
            def __init__(self):
                self.main_callback = None
                self.monitor_callback = None
                self.written = []

            def query_devices(self):
                return [
                    {"name": "Mic", "max_input_channels": 1, "max_output_channels": 0},
                    {"name": "Cable", "max_input_channels": 0, "max_output_channels": 2},
                    {"name": "Monitor", "max_input_channels": 0, "max_output_channels": 2},
                ]

            def open_output_stream(self, output_id, callback):
                self.monitor_callback = callback

            def open_duplex_stream(self, input_id, output_id, callback):
                self.main_callback = callback

            def write_frame(self, outdata, output_frame):
                self.written.append(output_frame)
                outdata[:] = 0

            def close(self):
                pass

        audio_io = FakeAudioIO()
        router = Router(audio_io, capture=Capture())
        monitor = AudioLevelMonitor(publication_hz=0, clock=lambda: 1.0)
        router.set_level_monitor(monitor)
        mixer = Mixer()
        engine = AudioEngine()
        router.start(engine, mixer, 0, 1, 2, monitor_enabled=lambda: True)
        indata = np.full((8, 1), 0.5, dtype=np.float32)
        outdata = np.zeros((8, 2), dtype=np.float32)

        audio_io.main_callback(indata, outdata, 8, None, None)
        snapshot = monitor.snapshot()

        self.assertIsNotNone(snapshot.input)
        self.assertIsNotNone(snapshot.processed)
        self.assertIsNotNone(snapshot.output)
        self.assertIsNotNone(snapshot.monitor)

    def test_soundboard_only_updates_output_not_input_or_processed(self):
        mixer = Mixer()
        mixer.queue_auxiliary(
            AuxiliaryAudio(
                samples=np.full(8, 0.5, dtype=np.float32),
                sample_rate=48000,
                channel_count=1,
                frame_count=8,
                sample_format="float32",
                source_type="test",
            )
        )
        voice = frame(np.zeros(8, dtype=np.float32), stage="engine")
        buses = mixer.mix(voice)
        monitor = AudioLevelMonitor(publication_hz=0, clock=lambda: 1.0)

        snapshot = monitor.publish(input_frame=frame(np.zeros(8)), processed_frame=voice, output_frame=buses.main_bus)

        self.assertFalse(snapshot.input.signal_present)
        self.assertFalse(snapshot.processed.signal_present)
        self.assertTrue(snapshot.output.signal_present)

    def test_bypass_processed_reading_is_truthful(self):
        engine = AudioEngine()
        engine.set_effects_bypassed(True)
        input_frame = frame(np.full(8, 0.25, dtype=np.float32))

        processed = engine.process_voice(input_frame)

        self.assertTrue(np.allclose(processed.samples, input_frame.samples))


class M71ServiceAndUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        cls.qt_app = QApplication.instance() or QApplication([])

    def test_service_snapshot_resets_on_stop_and_failure(self):
        svc = service()
        svc.level_monitor.publish(input_frame=frame([0.5]))

        svc.stop_audio()
        stopped = svc.audio_level_snapshot()
        svc.start_audio(None, 1)
        failed = svc.audio_level_snapshot()

        self.assertEqual(stopped.processing_state, "stopped")
        self.assertIsNone(stopped.input)
        self.assertEqual(failed.processing_state, "failed")

    def test_meter_polling_is_passive(self):
        telemetry = TelemetryService()
        svc = service(telemetry=telemetry)
        before_events = len(telemetry.snapshot().recent_events)
        character = svc.current_character_id
        route = dict(svc._active_route)

        snapshot = svc.audio_level_snapshot()

        self.assertEqual(snapshot.processing_state, "stopped")
        self.assertEqual(len(telemetry.snapshot().recent_events), before_events)
        self.assertEqual(svc.current_character_id, character)
        self.assertEqual(svc._active_route, route)

    def test_meter_metadata_is_projected_passively_to_operator_status(self):
        svc = service()
        svc.level_monitor.publish(input_frame=frame([0.5]))
        svc.audio_level_snapshot()

        status = svc.operator_status()

        self.assertIn("audio_level_sequence", status.diagnostics)
        self.assertIn("audio_input_peak_dbfs", status.diagnostics)

    def test_ui_meters_exist_timer_polls_and_close_stops_timers(self):
        from voice_lab.ui.main_window import App

        svc = service()
        window = App(svc, on_close=lambda: None)
        self.addCleanup(window.close)
        self.qt_app.processEvents()

        self.assertIn("input", window.level_widgets)
        self.assertIn("processed", window.level_widgets)
        self.assertIn("output", window.level_widgets)
        self.assertEqual(window.meter_timer.interval(), 50)
        self.assertTrue(window.meter_timer.isActive())
        self.assertLessEqual(window.minimumSizeHint().height(), 720)
        window.close()
        self.qt_app.processEvents()
        self.assertFalse(window.meter_timer.isActive())

    def test_display_mapping_peak_hold_overload_and_no_signal(self):
        model = LevelDisplayModel()
        quiet = LevelReading(-60.0, -60.0, False, False)
        loud = LevelReading(-3.0, -0.5, True, True)

        waiting = model.update(None, processing_state="running", captured_at=None, now=0.0)
        active = model.update(loud, processing_state="running", captured_at=0.0, now=0.1)
        latched = model.update(quiet, processing_state="running", captured_at=1.0, now=1.0)
        cleared = model.update(quiet, processing_state="running", captured_at=2.1, now=2.1)

        self.assertEqual(waiting.state_text, "Waiting for signal")
        self.assertEqual(active.state_text, "Overload")
        self.assertTrue(latched.overload_active)
        self.assertFalse(cleared.overload_active)
        self.assertEqual(db_to_percent(-60), 0)
        self.assertEqual(db_to_percent(0), 100)


class M71ArchitectureGuardTests(unittest.TestCase):
    def test_ui_uses_service_boundary_and_has_no_prohibited_imports(self):
        tree = ast.parse(Path("voice_lab/ui/main_window.py").read_text())
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")

        prohibited = (
            "numpy",
            "sounddevice",
            "voice_lab.engine",
            "voice_lab.effects",
            "voice_lab.plugins",
            "voice_lab.io.audio_io",
            "voice_lab.io.router",
            "voice_lab.mixer",
        )
        self.assertFalse(any(name.startswith(prohibited) for name in imports))

    def test_callback_path_has_no_qt_file_settings_or_device_query_in_meter_publish(self):
        router_source = Path("voice_lab/io/router.py").read_text()
        levels_source = Path("voice_lab/audio_levels.py").read_text()

        self.assertNotIn("Signal(", router_source)
        self.assertNotIn("PySide6", router_source + levels_source)
        self.assertNotIn("open(", levels_source)
        self.assertNotIn("query_devices", levels_source)
        self.assertNotIn("update_operator_settings", levels_source)

    def test_audio_output_is_identical_with_metering(self):
        engine = AudioEngine()
        mixer = Mixer()
        input_frame = frame(np.linspace(-0.25, 0.25, 8, dtype=np.float32))

        processed = engine.process_voice(input_frame)
        without_meter = mixer.mix(processed).main_bus.samples.copy()
        monitor = AudioLevelMonitor(publication_hz=0, clock=lambda: 1.0)
        monitor.publish(input_frame=input_frame, processed_frame=processed, output_frame=frame(without_meter))
        with_meter = mixer.mix(processed).main_bus.samples

        self.assertTrue(np.allclose(with_meter, without_meter))


if __name__ == "__main__":
    unittest.main()
