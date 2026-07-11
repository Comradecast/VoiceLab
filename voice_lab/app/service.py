import os
from dataclasses import asdict, is_dataclass

from PySide6.QtCore import QObject, Signal

from voice_lab.app.commands import CommandResult
from voice_lab.app.devices import describe_devices, resolve_stored_identity
from voice_lab.app.operator_status import build_operator_status
from voice_lab.config.config import DEFAULT_INPUT_ID, DEFAULT_MONITOR_ID, DEFAULT_OUTPUT_ID, SOUNDS_DIR
from voice_lab.config import ConfigurationService
from voice_lab.controllers.hotkeys import HotkeyManager
from voice_lab.controllers.soundboard import SoundboardController
from voice_lab.engine.audio_engine import AudioEngine
from voice_lab.io import AudioIO, Router
from voice_lab.io.device_errors import DeviceFailure, DeviceFailureError
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
        settings = self._operator_settings()
        self.current_monitor_enabled = settings.monitor_enabled
        self.current_monitor_volume = settings.monitor_volume
        self.current_soundboard_volume = settings.soundboard_volume
        self.current_selected_preset = settings.selected_preset
        self._processing_state = "stopped"
        self._active_route = {
            "virtual_mic_active": False,
            "monitor_active": False,
            "input_id": None,
            "output_id": None,
            "monitor_id": None,
        }
        self._device_descriptors = None
        self._settings_event_keys = set()

        self.hotkeys.set_commands(self)
        self.soundboard.set_commands(self)
        self.hotkeys.status_signal.connect(self.status_changed)
        self._record_settings_load()

    def devices(self):
        if self._device_descriptors is None:
            self._device_descriptors = describe_devices(self.audio_io.query_devices())
        return self._device_descriptors

    def refresh_devices(self, input_id=None, output_id=None, monitor_id=None):
        if self._processing_state not in {"stopped", "failed"}:
            result = CommandResult.fail(
                "Stop processing before refreshing audio devices.",
                processing_state=self._processing_state,
            )
            self.telemetry.record_command_result("refresh_devices", result)
            return result

        old_devices = tuple(self.devices())
        try:
            new_devices = describe_devices(self.audio_io.query_devices())
        except Exception as exc:
            failure = {
                "category": "device_enumeration_failed",
                "operator_message": (
                    "VoiceLab could not refresh audio devices. Check Windows audio services and try again."
                ),
                "technical_detail": str(exc),
                "recoverable": True,
            }
            result = CommandResult.fail(failure["operator_message"], refresh_failure=failure)
            self.telemetry.record_event(
                "devices.refresh_failed",
                "error",
                failure["operator_message"],
                **failure,
            )
            self.telemetry.record_command_result("refresh_devices", result)
            return result

        selections = {
            "input": self._preserve_selection(old_devices, new_devices, input_id, "input"),
            "virtual_output": self._preserve_selection(
                old_devices,
                new_devices,
                output_id,
                "output",
            ),
            "monitor_output": self._preserve_selection(old_devices, new_devices, monitor_id, "output"),
        }
        preferred = self._preferred_device_identities()
        for role, capability in (
            ("input", "input"),
            ("virtual_output", "output"),
            ("monitor_output", "output"),
        ):
            if selections[role] is None:
                selections[role] = resolve_stored_identity(new_devices, preferred.get(role), capability)
        missing_roles = tuple(
            role
            for role, old_id in (
                ("input", input_id),
                ("virtual_output", output_id),
                ("monitor_output", monitor_id),
            )
            if (old_id is not None or preferred.get(role) is not None) and selections[role] is None
        )
        self._device_descriptors = new_devices
        self._update_settings_warning(missing_roles)
        message = self._refresh_message(missing_roles)
        result = CommandResult.ok(
            message,
            devices=tuple(device.asdict() for device in new_devices),
            selections=selections,
            missing_roles=missing_roles,
        )
        self.telemetry.record_event(
            "devices.refreshed",
            "info",
            message,
            missing_roles=missing_roles,
            device_count=len(new_devices),
        )
        self.telemetry.record_command_result("refresh_devices", result)
        return result

    def telemetry_snapshot(self):
        self._refresh_effect_chain_status()
        return self.telemetry.snapshot()

    def operator_status(self):
        return build_operator_status(
            self.telemetry_snapshot(),
            self._processing_state,
            active_route=self._active_route,
        )

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
        return None

    def default_output_id(self):
        return None

    def default_monitor_id(self):
        return None

    def legacy_default_ids(self):
        return {
            "input": DEFAULT_INPUT_ID,
            "virtual_output": DEFAULT_OUTPUT_ID,
            "monitor_output": DEFAULT_MONITOR_ID,
        }

    def operator_preferences(self):
        devices = self.devices()
        preferred = self._preferred_device_identities()
        selections = {
            "input": resolve_stored_identity(devices, preferred.get("input"), "input"),
            "virtual_output": resolve_stored_identity(devices, preferred.get("virtual_output"), "output"),
            "monitor_output": resolve_stored_identity(devices, preferred.get("monitor_output"), "output"),
        }
        missing_roles = tuple(
            role
            for role, identity in preferred.items()
            if identity is not None and selections.get(role) is None
        )
        preset = self.current_selected_preset
        preset_available = bool(preset and preset in self.preset_names())
        if preset and not preset_available:
            self._record_once(
                f"preset-unavailable:{preset}",
                "settings.preset_unavailable",
                "warning",
                "Saved preset is not currently available.",
                preset=preset,
            )
        self._update_settings_warning(missing_roles, preset_missing=bool(preset and not preset_available))
        load_result = getattr(self.config, "settings_load_result", lambda: None)()
        issues = tuple(issue.message for issue in load_result.issues) if load_result else ()
        return {
            "selections": selections,
            "preferred_devices": {
                role: identity.asdict() if identity is not None else None
                for role, identity in preferred.items()
            },
            "missing_roles": missing_roles,
            "monitor_enabled": self.current_monitor_enabled,
            "monitor_volume": self.current_monitor_volume,
            "soundboard_volume": self.current_soundboard_volume,
            "selected_preset": preset if preset_available else None,
            "selected_preset_missing": preset if preset and not preset_available else None,
            "settings_issues": issues,
        }

    def record_device_selection(self, role, selected_id):
        if role not in {"input", "virtual_output", "monitor_output"}:
            result = CommandResult.fail(f"Unsupported device role: {role}")
            self.telemetry.record_command_result("record_device_selection", result, role=role)
            return result
        identity = None
        if selected_id is not None:
            device = self._device_by_index(self.devices(), selected_id)
            if device is None:
                result = CommandResult.fail("Selected device is not currently available.", role=role)
                self.telemetry.record_command_result("record_device_selection", result, role=role)
                return result
            identity = device.stored_identity()
        setter = getattr(self.config, "set_preferred_device", None)
        if setter is not None:
            setter(role, identity)
        self._update_settings_warning(())
        result = CommandResult.ok("Device preference updated.", role=role)
        self.telemetry.record_command_result("record_device_selection", result, role=role)
        return result

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
        persist_settings=True,
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
        if persist_settings:
            self._update_operator_settings(
                monitor_enabled=monitor_enabled,
                monitor_volume=monitor_volume,
                soundboard_volume=soundboard_volume,
            )
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

    def select_preset(self, name, persist=True):
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
        if persist:
            self.current_selected_preset = name
            self._update_operator_settings(selected_preset=name)
        self.apply_effect_parameters(
            gain=effect_parameters.gain,
            robot=effect_parameters.robot,
            lowpass=effect_parameters.lowpass,
            pitch=effect_parameters.pitch,
            monitor_enabled=self.current_monitor_enabled,
            monitor_volume=self.current_monitor_volume,
            soundboard_volume=self.current_soundboard_volume,
            persist_settings=persist,
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
        self._processing_state = "starting"
        selection_failure = self._validate_start_selection(input_id, output_id, monitor_id)
        if selection_failure is not None:
            return self._handle_start_failure(selection_failure, input_id, output_id, monitor_id)
        try:
            self.router.start(
                self.engine,
                self.mixer,
                input_id,
                output_id,
                monitor_id,
                monitor_enabled=lambda: self.current_monitor_enabled,
            )
        except DeviceFailureError as exc:
            return self._handle_start_failure(exc.failure, input_id, output_id, monitor_id)
        except Exception as exc:
            failure = DeviceFailure(
                category="route_startup_failed",
                role="route",
                technical_detail=str(exc),
            )
            return self._handle_start_failure(failure, input_id, output_id, monitor_id)

        message = (
            f"Running: mic {input_id} → cable {output_id}"
            + (f" + monitor {monitor_id}" if monitor_id is not None else "")
        )
        result = CommandResult.ok(message)
        self._processing_state = "running"
        self._active_route = {
            "virtual_mic_active": True,
            "monitor_active": monitor_id is not None and self.current_monitor_enabled,
            "input_id": input_id,
            "output_id": output_id,
            "monitor_id": monitor_id,
        }
        self.telemetry.set_audio_running(True)
        self.telemetry.set_route_status("running")
        self.telemetry.set_metadata("active_route", self._active_route)
        self.telemetry.set_metadata("active_start_failure", None)
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
        previous_state = self._processing_state
        self._processing_state = "stopping"
        try:
            self.router.stop()
            self.engine.stop()
        except Exception as exc:
            result = CommandResult.fail(f"Stop failed: {exc}")
            self._processing_state = "failed" if previous_state != "running" else "running"
            self.telemetry.record_event("audio.stop_failed", "error", result.message)
            self.telemetry.record_command_result("stop_audio", result)
            return result
        result = CommandResult.ok("Stopped")
        if previous_state != "running":
            result = CommandResult.ok("Already stopped")
        self._processing_state = "stopped"
        self._active_route = {
            "virtual_mic_active": False,
            "monitor_active": False,
            "input_id": None,
            "output_id": None,
            "monitor_id": None,
        }
        self.telemetry.set_audio_running(False)
        self.telemetry.set_route_status("stopped")
        self.telemetry.set_metadata("active_route", self._active_route)
        if previous_state == "running":
            self.telemetry.set_metadata("active_start_failure", None)
        self.telemetry.record_event("audio.stopped", "info", result.message)
        self.telemetry.record_command_result("stop_audio", result)
        return result

    def flush_telemetry(self):
        self._refresh_effect_chain_status()
        return self.telemetry.flush()

    def save_configuration(self):
        try:
            self.config.flush()
        except Exception as exc:
            self.telemetry.record_event(
                "settings.save_failed",
                "error",
                "Settings could not be saved.",
                technical_detail=str(exc),
            )
            raise
        self.telemetry.record_event("settings.saved", "info", "Settings saved.")

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

    def _preserve_selection(self, old_devices, new_devices, selected_id, capability):
        if selected_id is None:
            return None
        old_device = self._device_by_index(old_devices, selected_id)
        if old_device is None:
            return None
        same_index = self._device_by_index(new_devices, selected_id)
        if (
            same_index is not None
            and same_index.identity == old_device.identity
            and self._has_capability(same_index, capability)
        ):
            return same_index.index

        matches = [
            device
            for device in new_devices
            if device.identity == old_device.identity and self._has_capability(device, capability)
        ]
        if len(matches) == 1:
            return matches[0].index
        return None

    def _device_by_index(self, devices, index):
        for device in devices:
            if device.index == index:
                return device
        return None

    def _has_capability(self, device, capability):
        if capability == "input":
            return device.input_capable
        if capability == "output":
            return device.output_capable
        return False

    def _refresh_message(self, missing_roles):
        if not missing_roles:
            return "Audio devices refreshed."
        labels = {
            "input": "microphone",
            "virtual_output": "virtual microphone",
            "monitor_output": "monitor",
        }
        missing = [labels[role] for role in missing_roles]
        if len(missing) == 1:
            return f"Audio devices refreshed; {missing[0]} selection is no longer available."
        if len(missing) == 2:
            joined = " and ".join(missing)
        else:
            joined = ", ".join(missing[:-1]) + f", and {missing[-1]}"
        return f"Audio devices refreshed; {joined} selections require attention."

    def _operator_settings(self):
        getter = getattr(self.config, "operator_settings", None)
        if getter is not None:
            return getter()
        from voice_lab.config.settings import OperatorSettings

        return OperatorSettings()

    def _preferred_device_identities(self):
        settings = self._operator_settings()
        return {
            "input": settings.devices.get("input"),
            "virtual_output": settings.devices.get("virtual_output"),
            "monitor_output": settings.devices.get("monitor_output"),
        }

    def _update_operator_settings(self, **changes):
        updater = getattr(self.config, "update_operator_settings", None)
        if updater is None:
            return ()
        issues = updater(**changes)
        if issues:
            self._record_validation_failure("update_operator_settings", issues, **changes)
        return issues

    def _record_settings_load(self):
        load_result_getter = getattr(self.config, "settings_load_result", None)
        if load_result_getter is None:
            return
        load_result = load_result_getter()
        if load_result.missing:
            self.telemetry.record_event("settings.first_run", "info", "No saved operator settings found.")
            return
        if load_result.unsupported_schema:
            self.telemetry.record_event(
                "settings.unsupported_schema",
                "warning",
                "Saved settings use an unsupported schema version.",
                issues=tuple(issue.message for issue in load_result.issues),
            )
            self.telemetry.set_metadata(
                "operator_settings_warning",
                "Saved settings use an unsupported schema version.",
            )
            return
        if load_result.read_failed:
            self.telemetry.record_event(
                "settings.read_failed",
                "warning",
                "Saved settings could not be read.",
                issues=tuple(issue.message for issue in load_result.issues),
            )
            self.telemetry.set_metadata("operator_settings_warning", "Saved settings could not be read.")
            return
        severity = "warning" if load_result.issues else "info"
        event_type = "settings.validation_warning" if load_result.issues else "settings.loaded"
        message = "Saved settings loaded with warnings." if load_result.issues else "Saved settings loaded."
        self.telemetry.record_event(
            event_type,
            severity,
            message,
            issues=tuple(issue.message for issue in load_result.issues),
        )

    def _update_settings_warning(self, missing_roles, preset_missing=False):
        messages = []
        labels = {
            "input": "Saved microphone is not currently available.",
            "virtual_output": "Saved virtual microphone output is not currently available.",
            "monitor_output": "Saved monitor output is not currently available.",
        }
        for role in missing_roles:
            message = labels[role]
            messages.append(message)
            self._record_once(
                f"device-unavailable:{role}",
                "settings.device_unavailable",
                "warning",
                message,
                role=role,
            )
        if preset_missing:
            messages.append("Saved preset is not currently available.")
        self.telemetry.set_metadata("operator_settings_warning", " ".join(messages))

    def _record_once(self, key, event_type, severity, message, **metadata):
        if key in self._settings_event_keys:
            return
        self._settings_event_keys.add(key)
        self.telemetry.record_event(event_type, severity, message, **metadata)

    def _validate_start_selection(self, input_id, output_id, monitor_id):
        if input_id is None:
            return DeviceFailure(category="missing_selection", role="input")
        if output_id is None:
            return DeviceFailure(category="missing_selection", role="virtual_output")
        if self.current_monitor_enabled and monitor_id is None:
            return DeviceFailure(category="missing_selection", role="monitor_output")
        return None

    def _handle_start_failure(self, failure, input_id, output_id, monitor_id):
        normalized = self._normalize_device_failure(failure, input_id, output_id, monitor_id)
        result = CommandResult.fail(
            normalized["operator_message"],
            failure=normalized,
        )
        self._processing_state = "failed"
        self._active_route = {
            "virtual_mic_active": False,
            "monitor_active": False,
            "input_id": input_id,
            "output_id": output_id,
            "monitor_id": monitor_id,
        }
        self.telemetry.set_audio_running(False)
        self.telemetry.set_route_status("error")
        self.telemetry.set_metadata("active_route", self._active_route)
        self.telemetry.set_metadata("active_start_failure", normalized)
        self.telemetry.record_event(
            "route.start_failed",
            "error",
            normalized["operator_message"],
            input_id=input_id,
            output_id=output_id,
            monitor_id=monitor_id,
            **normalized,
        )
        self.telemetry.record_command_result("start_audio", result)
        return result

    def _normalize_device_failure(self, failure, input_id, output_id, monitor_id):
        category = failure.category
        role = failure.role
        selected_device_id = failure.selected_device_id
        if selected_device_id is None:
            selected_device_id = {
                "input": input_id,
                "virtual_output": output_id,
                "monitor_output": monitor_id,
            }.get(role)
        operator_message, suggested_action = self._device_failure_message(category, role)
        return {
            "category": category,
            "role": role,
            "selected_device_id": selected_device_id,
            "recoverable": failure.recoverable,
            "operator_message": operator_message,
            "suggested_action": suggested_action,
            "technical_detail": failure.technical_detail,
        }

    def _device_failure_message(self, category, role):
        if category == "missing_selection" and role == "input":
            return (
                "Select a microphone input before starting processing.",
                "Choose an input device and try again.",
            )
        if category == "missing_selection" and role == "virtual_output":
            return (
                "Select a virtual microphone output before starting processing.",
                "Choose a virtual microphone output and try again.",
            )
        if category == "missing_selection" and role == "monitor_output":
            return (
                "Select a monitor output device or disable monitor output.",
                "Choose a monitor output or uncheck Enable monitor output.",
            )
        if category == "device_not_found" and role == "input":
            return (
                "The selected microphone is no longer available.",
                "Reconnect it or select another microphone input.",
            )
        if category == "device_not_found" and role == "virtual_output":
            return (
                "The selected virtual microphone output is no longer available.",
                "Check the selected device and VB-CABLE configuration.",
            )
        if category == "device_not_found" and role == "monitor_output":
            return (
                "The selected monitor output is no longer available.",
                "Select another monitor output or disable monitor output.",
            )
        if category == "unsupported_configuration" and role == "input":
            return (
                "The selected microphone does not support the required input configuration.",
                "Select a microphone input that supports recording.",
            )
        if category == "unsupported_configuration" and role == "virtual_output":
            return (
                "The selected virtual microphone output does not support the required output configuration.",
                "Select a valid virtual microphone output.",
            )
        if category == "unsupported_configuration" and role == "monitor_output":
            return (
                "The selected monitor output does not support the required output configuration.",
                "Select another monitor output or disable monitor output.",
            )
        if category in {"device_open_failed", "device_unavailable"} and role == "input":
            return (
                "The selected microphone could not be opened. Check that it is connected and not being used exclusively by another application.",
                "Check the microphone connection and close other apps that may be using it.",
            )
        if category in {"device_open_failed", "device_unavailable"} and role == "virtual_output":
            return (
                "The selected virtual microphone output could not be opened. Check the selected device and VB-CABLE configuration.",
                "Check the virtual microphone device and try again.",
            )
        if category in {"device_open_failed", "device_unavailable"} and role == "monitor_output":
            return (
                "The selected monitor output could not be opened. Select another output or disable monitor output.",
                "Select another monitor output or uncheck Enable monitor output.",
            )
        if category == "partial_start_cleanup_failed":
            return (
                "VoiceLab could not cleanly recover from a partial audio startup failure.",
                "Close VoiceLab if retry does not work, then reopen it.",
            )
        return (
            "VoiceLab could not start audio processing. Check the selected devices and try again.",
            "Check the selected devices and try again.",
        )
