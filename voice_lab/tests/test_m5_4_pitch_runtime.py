import unittest
from unittest.mock import patch

import numpy as np

from voice_lab.app.lifecycle import ApplicationLifecycle
from voice_lab.app.service import ApplicationService
from voice_lab.effects.chain import EffectChain
from voice_lab.effects.pitch_shift import PitchShiftEffect
from voice_lab.effects.signalsmith_backend import SignalsmithBackendStatus
from voice_lab.engine.audio_engine import AudioEngine
from voice_lab.plugins import PluginManager
from voice_lab.telemetry import TelemetryService


class FakeSignalsmithBackend:
    def __init__(self, sample_rate, block_size, channels=1):
        self.sample_rate = int(sample_rate)
        self.block_size = int(block_size)
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


class FakeFallbackAdapter:
    def __init__(self, semitones, sample_rate, processing_window_frames):
        self.semitones = float(semitones)
        self.sample_rate = int(sample_rate)
        self.processing_window_frames = int(processing_window_frames)
        self.process_call_count = 0
        self.reset_count = 0
        self.silence_flush_count = 0

    def reset(self, semitones=None, sample_rate=None):
        if semitones is not None:
            self.semitones = float(semitones)
        self.reset_count += 1

    def process(self, mono, frames, sample_rate):
        self.process_call_count += 1
        return np.asarray(mono, dtype=np.float32)

    def status(self):
        from voice_lab.effects.pitch_shift import PitchBufferStatus

        return PitchBufferStatus(
            backend="pedalboard",
            backend_status="fallback_active",
            backend_available=True,
            backend_reason="test fallback",
            fallback_active=True,
            callback_frames=1024,
            processing_window_frames=self.processing_window_frames,
            configured_block_size=1024,
            configured_interval_size=self.processing_window_frames,
            buffered_input_frames=0,
            buffered_output_frames=0,
            estimated_added_ms=0.0,
            processing_window_ms=0.0,
            first_output_delay_ms=0.0,
            max_buffer_frames=self.processing_window_frames * 2,
            priming=False,
            process_call_count=self.process_call_count,
            reset_count=self.reset_count,
            silence_flush_count=self.silence_flush_count,
            processor_identity=id(self),
        )


class FakeRouter:
    def __init__(self):
        self.running = False
        self.start_count = 0
        self.stop_count = 0

    def start(self, engine, mixer, input_id, output_id, monitor_id=None, monitor_enabled=None):
        self.running = True
        self.start_count += 1

    def stop(self):
        self.running = False
        self.stop_count += 1


class FakeAudioIO:
    def query_devices(self):
        return []


def _block():
    return np.linspace(-0.25, 0.25, 1024, dtype=np.float32)


def _available_status():
    return SignalsmithBackendStatus(True, "signalsmith", "active")


def _missing_status():
    return SignalsmithBackendStatus(
        False,
        "signalsmith",
        "native_module_missing",
        "missing for controlled test",
    )


class M54PitchRuntimeTests(unittest.TestCase):
    def test_signalsmith_reports_active_when_available(self):
        with (
            patch("voice_lab.effects.pitch_shift.signalsmith_status", _available_status),
            patch("voice_lab.effects.pitch_shift.SignalsmithPitchBackend", FakeSignalsmithBackend),
        ):
            effect = PitchShiftEffect(lambda: 4.0)
            output = effect.process(_block(), 1024, 48000)
            status = effect.telemetry()

        self.assertEqual(output.shape, (1024,))
        self.assertEqual(status.backend, "signalsmith")
        self.assertEqual(status.backend_status, "active")
        self.assertFalse(status.fallback_active)
        self.assertEqual(status.latency_frames, 128)

    def test_controlled_signalsmith_unavailable_path(self):
        with patch("voice_lab.effects.pitch_shift.signalsmith_status", _missing_status):
            effect = PitchShiftEffect(lambda: 4.0)
            status = effect.telemetry()

        self.assertEqual(status.backend, "none")
        self.assertEqual(status.backend_status, "native_module_missing")
        self.assertFalse(status.backend_available)
        self.assertIn("missing", status.last_backend_error)

    def test_pedalboard_fallback_state(self):
        with (
            patch("voice_lab.effects.pitch_shift.signalsmith_status", _missing_status),
            patch("voice_lab.effects.pitch_shift.StreamingPitchAdapter", FakeFallbackAdapter),
        ):
            effect = PitchShiftEffect(lambda: -4.0)
            effect.process(_block(), 1024, 48000)
            status = effect.telemetry()

        self.assertEqual(status.backend, "pedalboard")
        self.assertEqual(status.backend_status, "fallback_active")
        self.assertTrue(status.fallback_active)

    def test_no_backend_failure_behavior(self):
        with patch("voice_lab.effects.pitch_shift.signalsmith_status", _missing_status):
            effect = PitchShiftEffect(lambda: 4.0, allow_pedalboard_fallback=False)
            chain = EffectChain([effect])
            output = chain.process(_block(), 1024, 48000)
            chain_status = chain.status()

        self.assertEqual(output.shape, (1024,))
        self.assertIn("Pitch Shift", chain_status.runtime_bypassed_effects)
        self.assertIn("Pitch Shift", chain_status.failed_effects)

    def test_zero_plus_four_and_minus_four_configuration(self):
        semitones = {"value": 0.0}
        with (
            patch("voice_lab.effects.pitch_shift.signalsmith_status", _available_status),
            patch("voice_lab.effects.pitch_shift.SignalsmithPitchBackend", FakeSignalsmithBackend),
        ):
            effect = PitchShiftEffect(lambda: semitones["value"])
            zero = effect.process(_block(), 1024, 48000)
            self.assertTrue(np.allclose(zero, _block()))
            self.assertEqual(effect.telemetry().backend_status, "bypassed")

            semitones["value"] = 4.0
            effect.process(_block(), 1024, 48000)
            self.assertEqual(effect.adapter.semitones, 4.0)

            semitones["value"] = -4.0
            effect.process(_block(), 1024, 48000)
            self.assertEqual(effect.adapter.semitones, -4.0)

    def test_pitch_effect_bypass(self):
        effect = PitchShiftEffect(lambda: 4.0)
        chain = EffectChain([effect])
        chain.set_enabled("Pitch Shift", False)

        output = chain.process(_block(), 1024, 48000)

        self.assertTrue(np.allclose(output, _block()))
        self.assertIn("Pitch Shift", chain.status().disabled_effects)

    def test_application_start_stop_and_restart_lifecycle(self):
        lifecycle = ApplicationLifecycle()

        first = lifecycle.startup()
        lifecycle.shutdown()
        second = lifecycle.startup()
        lifecycle.shutdown()

        self.assertIs(first, second)
        self.assertIn("initialize_application_service", lifecycle.state.startup_steps)
        self.assertEqual(lifecycle.state.shutdown_steps.count("stop_audio"), 2)

    def test_live_semitone_and_preset_change_while_running(self):
        with (
            patch("voice_lab.effects.pitch_shift.signalsmith_status", _available_status),
            patch("voice_lab.effects.pitch_shift.SignalsmithPitchBackend", FakeSignalsmithBackend),
        ):
            router = FakeRouter()
            service = ApplicationService(
                telemetry=TelemetryService(),
                plugins=PluginManager(),
                engine=AudioEngine(),
                router=router,
                audio_io=FakeAudioIO(),
            )

            self.assertTrue(service.start_audio(0, 1).success)
            result = service.apply_effect_parameters(
                1.0,
                0.0,
                4000,
                False,
                0.35,
                0.7,
                pitch=4.0,
            )
            self.assertTrue(result.success)
            self.assertEqual(service.current_effect_params["pitch"], 4.0)
            self.assertTrue(service.select_preset("Deep Voice").success)
            self.assertEqual(service.current_effect_params["pitch"], -4)
            self.assertTrue(router.running)

    def test_shutdown_with_buffered_pitch_and_telemetry_readable(self):
        with (
            patch("voice_lab.effects.pitch_shift.signalsmith_status", _available_status),
            patch("voice_lab.effects.pitch_shift.SignalsmithPitchBackend", FakeSignalsmithBackend),
        ):
            service = ApplicationService(
                telemetry=TelemetryService(),
                plugins=PluginManager(),
                engine=AudioEngine(),
                router=FakeRouter(),
                audio_io=FakeAudioIO(),
            )
            service.apply_effect_parameters(1.0, 0.0, 4000, False, 0.35, 0.7, pitch=4.0)
            service.engine.process_voice(_block(), 1024)

            before = service.telemetry_snapshot()
            result = service.stop_audio()
            after = service.telemetry_snapshot()

        self.assertTrue(result.success)
        self.assertEqual(before.metadata["pitch_buffer_status"]["backend"], "signalsmith")
        self.assertEqual(after.metadata["pitch_buffer_status"]["backend"], "signalsmith")
        self.assertFalse(after.audio_running)


if __name__ == "__main__":
    unittest.main()
