import os
from dataclasses import asdict, is_dataclass

from PySide6.QtCore import QObject, Signal

from voice_lab.app.commands import CommandResult
from voice_lab.config.config import DEFAULT_INPUT_ID, DEFAULT_MONITOR_ID, DEFAULT_OUTPUT_ID, SOUNDS_DIR
from voice_lab.config import ConfigurationService
from voice_lab.controllers.hotkeys import HotkeyManager
from voice_lab.controllers.soundboard import SoundboardController
from voice_lab.engine.audio_engine import AudioEngine
from voice_lab.io import AudioIO, Router
from voice_lab.mixer import Mixer
from voice_lab.plugins import PluginManager
from voice_lab.telemetry import TelemetryService
from voice_lab.app.soundboard_assets import list_sound_files, load_sound


class ApplicationService(QObject):
    status_changed = Signal(str)
    preset_selected = Signal(str, dict)

    def __init__(
        self,
        telemetry=None,
        config=None,
        plugins=None,
        engine=None,
        mixer=None,
        audio_io=None,
        router=None,
        hotkeys=None,
        soundboard=None,
    ):
        super().__init__()
        self.telemetry = telemetry or TelemetryService()
        self.engine = engine or AudioEngine()
        self.plugins = plugins or PluginManager()
        self.engine.set_effect_chain(
            self.plugins.load_default_effect_chain(
                self.engine,
                runtime_failure_handler=self._record_effect_runtime_failure,
            )
        )
        self._refresh_effect_chain_status()
        self.mixer = mixer or Mixer()
        self.audio_io = audio_io or AudioIO()
        self.router = router or Router(self.audio_io)
        self.config = config or ConfigurationService()
        self.hotkeys = hotkeys or HotkeyManager()
        self.soundboard = soundboard or SoundboardController()
        self.current_effect_params = {
            "gain": 1.0,
            "robot": 0.0,
            "lowpass": 4000,
            "pitch": 0.0,
        }
        self.current_monitor_enabled = False
        self.current_monitor_volume = 0.35
        self.current_soundboard_volume = 0.70

        self.hotkeys.set_commands(self)
        self.soundboard.set_commands(self)
        self.hotkeys.status_signal.connect(self.status_changed)

    def devices(self):
        return self.audio_io.query_devices()

    def telemetry_snapshot(self):
        self._refresh_effect_chain_status()
        return self.telemetry.snapshot()

    def _refresh_effect_chain_status(self):
        self.telemetry.set_effect_chain_status(self.engine.effect_chain.status())
        for effect in self.engine.effect_chain.effects:
            if getattr(effect, "name", "") != "Pitch Shift" or not hasattr(effect, "telemetry"):
                continue
            status = effect.telemetry()
            if status is None:
                continue
            self.telemetry.set_metadata(
                "pitch_buffer_status",
                asdict(status) if is_dataclass(status) else status,
            )
            break

    def _record_effect_runtime_failure(self, effect_name, exc):
        self._refresh_effect_chain_status()
        self.telemetry.record_event(
            "effect.runtime_failed",
            "error",
            f"Effect bypassed after runtime failure: {effect_name}",
            effect=effect_name,
            error=str(exc),
        )

    def default_input_id(self):
        return DEFAULT_INPUT_ID

    def default_output_id(self):
        return DEFAULT_OUTPUT_ID

    def default_monitor_id(self):
        return DEFAULT_MONITOR_ID

    def preset_names(self):
        return self.config.preset_names()

    def sound_files(self):
        return list_sound_files()

    def register_hotkeys(self):
        self.hotkeys.register()

    def unregister_hotkeys(self):
        self.hotkeys.unregister()

    def apply_effect_parameters(
        self,
        gain,
        robot,
        lowpass,
        monitor_enabled,
        monitor_volume,
        soundboard_volume,
        pitch=0.0,
    ):
        validation = self.config.validate_effect_parameters(gain, robot, lowpass, pitch)
        if not validation.success:
            result = CommandResult.fail(
                f"Invalid effect parameters: {validation.message}",
                issues=validation.issues,
            )
            self._record_validation_failure(
                "apply_effect_parameters",
                validation.issues,
                gain=gain,
                robot=robot,
                lowpass=lowpass,
                pitch=pitch,
            )
            self.telemetry.record_command_result("apply_effect_parameters", result)
            return result

        gain = validation.gain
        robot = validation.robot
        lowpass = validation.lowpass
        pitch = validation.pitch
        self.current_effect_params = {
            "gain": gain,
            "robot": robot,
            "lowpass": lowpass,
            "pitch": pitch,
        }
        self.current_monitor_enabled = monitor_enabled
        self.current_monitor_volume = monitor_volume
        self.current_soundboard_volume = soundboard_volume
        self.engine.set_params(
            gain=gain,
            robot=robot,
            lowpass=lowpass,
            pitch=pitch,
        )
        self.telemetry.set_metadata("current_pitch_semitones", pitch)
        self.telemetry.set_metadata("current_effect_params", self.current_effect_params)
        self.mixer.set_params(
            soundboard_volume=soundboard_volume,
            monitor_volume=monitor_volume,
        )
        result = CommandResult.ok()
        self.telemetry.record_command_result(
            "apply_effect_parameters",
            result,
            gain=gain,
            robot=robot,
            lowpass=lowpass,
            pitch=pitch,
            monitor_enabled=monitor_enabled,
        )
        return result

    def select_preset(self, name):
        selection = self.config.select_preset(name)
        if not selection.success:
            result = CommandResult.fail(
                selection.message,
                preset=name,
                issues=selection.issues,
            )
            if selection.issues:
                self._record_validation_failure("select_preset", selection.issues, preset=name)
            self.telemetry.record_command_result("select_preset", result, preset=name)
            return result

        effect_parameters = selection.effect_parameters
        self.apply_effect_parameters(
            gain=effect_parameters.gain,
            robot=effect_parameters.robot,
            lowpass=effect_parameters.lowpass,
            pitch=effect_parameters.pitch,
            monitor_enabled=self.current_monitor_enabled,
            monitor_volume=self.current_monitor_volume,
            soundboard_volume=self.current_soundboard_volume,
        )
        result = CommandResult.ok(params=selection.preset.copy())
        self.telemetry.record_command_result("select_preset", result, preset=name)
        return result

    def select_preset_from_hotkey(self, name):
        result = self.select_preset(name)
        if result.success:
            self.preset_selected.emit(name, result.metadata["params"])
            self.status_changed.emit(f"Preset hotkey: {name}")
        else:
            self.status_changed.emit(result.message)
        return result

    def save_preset(self, name, params):
        name = name.strip()
        if not name:
            result = CommandResult.fail("Preset name is required")
            self.telemetry.record_command_result("save_preset", result)
            return result
        saved = self.config.save_preset(name, params)
        if not saved.success:
            result = CommandResult.fail(
                saved.message,
                preset=name,
                issues=saved.issues,
            )
            if saved.issues:
                self._record_validation_failure("save_preset", saved.issues, preset=name)
            self.telemetry.record_command_result("save_preset", result, preset=name)
            return result
        result = CommandResult.ok(saved.message, name=name)
        self.telemetry.record_command_result("save_preset", result, preset=name)
        return result

    def delete_preset(self, name):
        deleted = self.config.delete_preset(name)
        if not deleted.success:
            result = CommandResult.fail(deleted.message)
            self.telemetry.record_command_result("delete_preset", result, preset=name)
            return result
        result = CommandResult.ok(deleted.message, name=name)
        self.telemetry.record_command_result("delete_preset", result, preset=name)
        return result

    def play_sound(self, path):
        try:
            self.mixer.queue_auxiliary(load_sound(path))
        except Exception as exc:
            result = CommandResult.fail(f"Sound error: {exc}")
            self.telemetry.record_command_result("play_sound", result, path=path)
            return result
        result = CommandResult.ok(f"Played: {os.path.basename(path)}")
        self.telemetry.record_command_result("play_sound", result, path=path)
        return result

    def play_sound_file(self, filename):
        return self.play_sound(os.path.join(SOUNDS_DIR, filename))

    def play_sound_by_index(self, index):
        files = self.sound_files()
        if not 0 <= index < len(files):
            result = CommandResult.fail(f"No sound at hotkey index {index}")
            self.telemetry.record_command_result("play_sound_by_index", result, index=index)
            return result

        result = self.play_sound_file(files[index])
        return result

    def start_audio(self, input_id, output_id, monitor_id=None):
        try:
            self.router.start(
                self.engine,
                self.mixer,
                input_id,
                output_id,
                monitor_id,
                monitor_enabled=lambda: self.current_monitor_enabled,
            )
        except Exception as exc:
            result = CommandResult.fail(f"Start failed: {exc}")
            self.telemetry.set_audio_running(False)
            self.telemetry.set_route_status("error")
            self.telemetry.record_event(
                "route.start_failed",
                "error",
                result.message,
                input_id=input_id,
                output_id=output_id,
                monitor_id=monitor_id,
            )
            self.telemetry.record_command_result("start_audio", result)
            return result

        message = (
            f"Running: mic {input_id} → cable {output_id}"
            + (f" + monitor {monitor_id}" if monitor_id is not None else "")
        )
        result = CommandResult.ok(message)
        self.telemetry.set_audio_running(True)
        self.telemetry.set_route_status("running")
        self.telemetry.record_event(
            "audio.started",
            "info",
            message,
            input_id=input_id,
            output_id=output_id,
            monitor_id=monitor_id,
        )
        self.telemetry.record_command_result("start_audio", result)
        return result

    def stop_audio(self):
        try:
            self.router.stop()
            self.engine.stop()
        except Exception as exc:
            result = CommandResult.fail(f"Stop failed: {exc}")
            self.telemetry.record_event("audio.stop_failed", "error", result.message)
            self.telemetry.record_command_result("stop_audio", result)
            return result
        result = CommandResult.ok("Stopped")
        self.telemetry.set_audio_running(False)
        self.telemetry.set_route_status("stopped")
        self.telemetry.record_event("audio.stopped", "info", result.message)
        self.telemetry.record_command_result("stop_audio", result)
        return result

    def flush_telemetry(self):
        self._refresh_effect_chain_status()
        return self.telemetry.flush()

    def save_configuration(self):
        self.config.flush()

    def unload_plugins(self):
        self.engine.stop()

    def _record_validation_failure(self, command_name, issues, **metadata):
        self.telemetry.record_event(
            "config.validation_failed",
            "error",
            f"Validation failed for {command_name}",
            command=command_name,
            issues=tuple(issue.message for issue in issues),
            **metadata,
        )
