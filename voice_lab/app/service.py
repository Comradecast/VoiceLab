import math
import os
from dataclasses import asdict, is_dataclass
from numbers import Real

from PySide6.QtCore import QObject, Signal

from voice_lab.analysis import F0_MAX_HZ, F0_MIN_HZ, SourceVoiceAnalyzer
from voice_lab.audio_levels import AudioLevelMonitor
from voice_lab.calibrate_lock import (
    ADAPTIVE_CONTINUOUS,
    ADAPTIVE_MODES,
    ADAPTIVE_OFF,
    CalibrationSourceProfile,
    LockedTransformationSnapshot,
    ManualTransformationTrim,
    StableTransformationControlSnapshot,
    SuggestedTransformationSnapshot,
    apply_manual_trim,
    manual_trim,
    trim_projection,
)
from voice_lab.app.commands import CommandResult
from voice_lab.app.devices import describe_devices, resolve_stored_identity
from voice_lab.app.operator_status import build_operator_status
from voice_lab.config.config import DEFAULT_INPUT_ID, DEFAULT_MONITOR_ID, DEFAULT_OUTPUT_ID, SOUNDS_DIR
from voice_lab.config import ConfigurationService
from voice_lab.config.input_processing import (
    DEFAULT_INPUT_PROCESSING_SETTINGS,
    input_processing_ranges,
    update_input_processing,
)
from voice_lab.config.voice_characters import (
    DEFAULT_CHARACTER_STRENGTH,
    NATURAL_CHARACTER_ID,
    character_by_compatibility_preset,
    character_by_id,
    protected_voice_names,
    resolve_character_parameters,
    validate_strength,
    voice_characters,
)
from voice_lab.controllers.hotkeys import HotkeyManager
from voice_lab.controllers.soundboard import SoundboardController
from voice_lab.engine.audio_engine import AudioEngine
from voice_lab.execution import (
    EXECUTION_CONTROLLER_CADENCE_HZ,
    TransformationExecutionController,
    TransformationExecutionRuntime,
    TransformationExecutor,
)
from voice_lab.io import AudioIO, Router
from voice_lab.io.device_errors import DeviceFailure, DeviceFailureError
from voice_lab.mixer import Mixer
from voice_lab.planner import (
    DEFAULT_TARGET_PROFILE,
    HIGHER_BRIGHTER_REFERENCE,
    LOWER_WEIGHTIER_REFERENCE,
    TransformationPlanner,
    replace_target,
)
from voice_lab.plugins import PluginManager
from voice_lab.telemetry import TelemetryService
from voice_lab.app.soundboard_assets import list_sound_files, load_sound


RESERVED_CUSTOM_VOICE_NAMES = frozenset({"Custom - Unsaved", "Custom — Unsaved"})
STALE_SOURCE_AGE_SECONDS = 1.5
INVALID_CALIBRATION_RELIABILITIES = {
    "",
    "analyzer failure",
    "analyzer unavailable",
    "collecting",
    "insufficient level",
    "insufficient voiced speech",
    "stale",
}


class _StableExecutionPlanProvider:
    def __init__(self, service):
        self.service = service

    def plan(self, source_snapshot, target_profile, strength):
        return self.service._stable_execution_plan(source_snapshot, target_profile, strength)


def _required_calibration_number(value, label, *, minimum=None, maximum=None):
    if value is None:
        return False, f"{label} is missing."
    ok, number_or_reason = _calibration_number(value, label)
    if not ok:
        return False, number_or_reason
    number = number_or_reason
    if minimum is not None and number < minimum:
        return False, f"{label} is out of range."
    if maximum is not None and number > maximum:
        return False, f"{label} is out of range."
    return True, number


def _optional_calibration_number(value, label):
    if value is None:
        return True, None
    return _calibration_number(value, label)


def _calibration_number(value, label):
    if isinstance(value, bool) or not isinstance(value, Real):
        return False, f"{label} is not numeric."
    number = float(value)
    if not math.isfinite(number):
        return False, f"{label} is not finite."
    return True, number


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
        formant_lab=False,
        voice_analysis_lab=False,
        target_planner_lab=False,
        transformation_execution_lab=False,
        calibrate_lock_lab=False,
    ):
        super().__init__()
        self.telemetry = telemetry or TelemetryService()
        self.level_monitor = AudioLevelMonitor()
        self.engine = engine or AudioEngine()
        self.plugins = plugins or PluginManager()
        self.calibrate_lock_lab_enabled = bool(calibrate_lock_lab)
        self.transformation_execution_lab_enabled = bool(transformation_execution_lab or calibrate_lock_lab)
        self.formant_lab_enabled = bool(formant_lab or transformation_execution_lab or calibrate_lock_lab)
        self.target_planner_lab_enabled = bool(target_planner_lab or transformation_execution_lab or calibrate_lock_lab)
        self.voice_analysis_lab_enabled = bool(
            voice_analysis_lab or target_planner_lab or transformation_execution_lab or calibrate_lock_lab
        )
        self.target_planner = TransformationPlanner() if self.target_planner_lab_enabled else None
        self.current_target_profile = DEFAULT_TARGET_PROFILE
        self.target_planner_strength = 1.0
        self.source_voice_analyzer = SourceVoiceAnalyzer() if self.voice_analysis_lab_enabled else None
        self.execution_enabled = False
        self.stable_adaptive_mode = ADAPTIVE_OFF
        self._calibration_generation = 0
        self._suggestion_generation = 0
        self._lock_generation = 0
        self._trim_generation = 0
        self._current_calibration = None
        self._current_suggestion = None
        self._locked_transformation = None
        self._manual_trim = manual_trim()
        self.transformation_executor = TransformationExecutor() if self.transformation_execution_lab_enabled else None
        self.transformation_execution_runtime = (
            TransformationExecutionRuntime(self.engine.input_processing)
            if self.transformation_execution_lab_enabled
            else None
        )
        if self.transformation_execution_runtime is not None:
            self.engine.set_transformation_execution_runtime(self.transformation_execution_runtime)
        self.transformation_execution_controller = None
        runtime_failure_handler = (
            self.transformation_execution_runtime.record_effect_runtime_failure
            if self.transformation_execution_runtime is not None
            else self._record_effect_runtime_failure
        )
        self.engine.set_effect_chain(
            self.plugins.load_default_effect_chain(
                self.engine,
                runtime_failure_handler=runtime_failure_handler,
                formant_lab=self.formant_lab_enabled,
            )
        )
        self._refresh_effect_chain_status()
        self.mixer = mixer or Mixer()
        self.audio_io = audio_io or AudioIO()
        self.router = router or Router(self.audio_io)
        if hasattr(self.router, "set_level_monitor"):
            self.router.set_level_monitor(self.level_monitor)
        if self.source_voice_analyzer is not None and hasattr(self.router, "set_analysis_tap"):
            self.router.set_analysis_tap(self.source_voice_analyzer.tap)
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
        self.current_input_processing = settings.input_processing
        self.engine.set_input_processing(self.current_input_processing)
        if self.transformation_execution_runtime is not None:
            self.transformation_execution_runtime.set_baseline(self.current_input_processing)
            self.transformation_execution_controller = TransformationExecutionController(
                runtime=self.transformation_execution_runtime,
                executor=self.transformation_executor,
                planner=(
                    _StableExecutionPlanProvider(self)
                    if self.calibrate_lock_lab_enabled
                    else self.target_planner
                ),
                source_snapshot_getter=lambda: self.source_analysis_snapshot(),
                target_profile_getter=lambda: self.current_target_profile,
                strength_getter=lambda: self.target_planner_strength,
                baseline_getter=lambda: self.current_input_processing,
                enabled_getter=lambda: self.execution_enabled,
                bypass_getter=lambda: self.effects_bypassed,
                cadence_hz=EXECUTION_CONTROLLER_CADENCE_HZ,
            )
        self.current_monitor_enabled = settings.monitor_enabled
        self.current_monitor_volume = settings.monitor_volume
        self.current_soundboard_volume = settings.soundboard_volume
        self.current_selected_preset = settings.selected_preset
        restored_character = character_by_id(settings.selected_character_id)
        if restored_character is None:
            restored_character = character_by_compatibility_preset(settings.selected_preset)
        self.current_character_id = restored_character.id if restored_character else NATURAL_CHARACTER_ID
        self.current_character_strength = settings.character_strength
        self.current_custom_preset = None if restored_character else settings.selected_preset
        self.active_voice_kind = "character" if restored_character or not settings.selected_preset else "custom"
        self.effects_bypassed = False
        self.engine.set_effects_bypassed(False)
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
        self._restore_voice_state()

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

    def audio_level_snapshot(self):
        snapshot = self.level_monitor.snapshot(self._processing_state)
        self.telemetry.set_metadata("audio_levels", snapshot.asdict())
        return snapshot

    def source_analysis_snapshot(self):
        if self.source_voice_analyzer is None:
            return None
        snapshot = self.source_voice_analyzer.snapshot()
        self.telemetry.set_metadata("source_voice_analysis", snapshot.asdict())
        return snapshot.asdict()

    def reset_source_analysis(self):
        if self.source_voice_analyzer is None:
            result = CommandResult.fail("Source Analysis Lab is not enabled.")
            self.telemetry.record_command_result("reset_source_analysis", result)
            return result
        self.source_voice_analyzer.reset()
        snapshot = self.source_analysis_snapshot()
        result = CommandResult.ok("Source analysis reset.", source_analysis=snapshot)
        self.telemetry.record_command_result("reset_source_analysis", result)
        return result

    def target_planner_state(self):
        if self.target_planner is None:
            return None
        snapshot = self.source_analysis_snapshot()
        plan = self.target_planner.plan(snapshot, self.current_target_profile, self.target_planner_strength)
        state = {
            "lab": "Experimental - Planning Only - Audio Is Not Modified",
            "strength_percent": self.target_planner_strength * 100.0,
            "target_profile": self.current_target_profile.asdict(),
            "plan": plan.asdict(),
            "references": {
                "neutral": DEFAULT_TARGET_PROFILE.asdict(),
                "higher_brighter": HIGHER_BRIGHTER_REFERENCE.asdict(),
                "lower_weightier": LOWER_WEIGHTIER_REFERENCE.asdict(),
            },
        }
        self.telemetry.set_metadata("target_planner", state)
        return state

    def execution_lab_state(self):
        if not self.transformation_execution_lab_enabled:
            return None
        return self.transformation_execution_snapshot()

    def calibrate_lock_state(self):
        if not self.calibrate_lock_lab_enabled:
            return None
        return self.stable_control_snapshot()

    def stable_control_snapshot(self):
        if not self.calibrate_lock_lab_enabled:
            return None
        self._refresh_stable_suggestion()
        projection_plan = self._locked_transformation.plan if self._locked_transformation is not None else None
        _, projection = apply_manual_trim(projection_plan, self._manual_trim)
        target_name = getattr(self.current_target_profile, "display_name", self.current_target_profile.target_id)
        newer = self._newer_suggestion_available()
        snapshot = StableTransformationControlSnapshot(
            lab="Experimental - Calibrate, Lock, and Manual Trim",
            adaptive_mode=self.stable_adaptive_mode,
            execution_authority="live adaptive plan" if self.stable_adaptive_mode == ADAPTIVE_CONTINUOUS else "locked plan",
            calibration=self._current_calibration,
            suggestion=self._current_suggestion,
            locked=self._locked_snapshot(newer_suggestion_available=newer),
            trim=self._manual_trim,
            execution_enabled=self.execution_enabled,
            calibration_generation=self._calibration_generation,
            suggestion_generation=self._suggestion_generation,
            lock_generation=self._lock_generation,
            current_target_id=self.current_target_profile.target_id,
            current_target_name=target_name,
            current_strength=self.target_planner_strength,
            suggestion_differs_from_lock=self._suggestion_differs_from_lock(),
            newer_suggestion_available=newer,
            manual_trim_active=self._manual_trim.pitch_changed_from_zero or self._manual_trim.formant_changed_from_zero,
            live_source_readiness_matters=self.stable_adaptive_mode == ADAPTIVE_CONTINUOUS,
            locked_plan_available_for_off=self._locked_transformation is not None,
            target_changed_after_lock=self._target_changed_after_lock(),
            strength_changed_after_lock=self._strength_changed_after_lock(),
            calibration_changed_after_lock=self._calibration_changed_after_lock(),
            **projection,
        )
        self.telemetry.set_metadata("calibrate_lock", snapshot.asdict())
        return snapshot

    def capture_calibration(self):
        return self._capture_calibration("capture_calibration")

    def recalibrate(self):
        return self._capture_calibration("recalibrate")

    def lock_suggested_transformation(self):
        if not self.calibrate_lock_lab_enabled:
            result = CommandResult.fail("Calibrate/Lock Lab is not enabled.")
            self.telemetry.record_command_result("lock_suggested_transformation", result)
            return result
        self._refresh_stable_suggestion()
        suggestion = self._current_suggestion
        if suggestion is None or not suggestion.valid or suggestion.plan is None:
            result = CommandResult.fail("No valid suggested transformation is available.")
            self.telemetry.record_command_result("lock_suggested_transformation", result)
            return result
        if suggestion.planner_status in {"planner_failure", "invalid_target"}:
            result = CommandResult.fail("Suggested transformation is not lockable.")
            self.telemetry.record_command_result("lock_suggested_transformation", result)
            return result
        self._lock_generation += 1
        supported = tuple(name for name in suggestion.plan.required_capabilities if name in ("adaptive_pitch_center", "formant_shift", "compressor", "limiter"))
        unsupported = tuple(name for name in suggestion.plan.required_capabilities if name not in supported)
        self._locked_transformation = LockedTransformationSnapshot(
            valid=True,
            lock_id=self._lock_generation,
            locked_at=self.target_planner.clock(),
            source_calibration_id=suggestion.calibration_id,
            suggestion_id=suggestion.suggestion_id,
            target_id=suggestion.target_id,
            target_version=suggestion.target_version,
            character_strength=suggestion.character_strength,
            plan=suggestion.plan,
            supported_capabilities=supported,
            unsupported_capabilities=unsupported,
            warnings=suggestion.warnings,
            newer_suggestion_available=False,
        )
        self._refresh_execution_target()
        state = self.stable_control_snapshot()
        result = CommandResult.ok("Suggested transformation locked.", stable_control=state)
        self.telemetry.record_command_result("lock_suggested_transformation", result)
        return result

    def set_pitch_trim(self, semitones):
        return self._set_manual_trim(pitch_trim=semitones, command_name="set_pitch_trim")

    def set_formant_trim(self, semitones):
        return self._set_manual_trim(formant_trim=semitones, command_name="set_formant_trim")

    def return_to_suggested_plan(self):
        if not self.calibrate_lock_lab_enabled:
            result = CommandResult.fail("Calibrate/Lock Lab is not enabled.")
            self.telemetry.record_command_result("return_to_suggested_plan", result)
            return result
        self._trim_generation += 1
        self._manual_trim = manual_trim(generation=self._trim_generation)
        self._refresh_execution_target()
        state = self.stable_control_snapshot()
        result = CommandResult.ok("Manual trims returned to suggested plan.", stable_control=state)
        self.telemetry.record_command_result("return_to_suggested_plan", result)
        return result

    def set_adaptive_updating_mode(self, mode):
        if not self.calibrate_lock_lab_enabled:
            result = CommandResult.fail("Calibrate/Lock Lab is not enabled.")
            self.telemetry.record_command_result("set_adaptive_updating_mode", result)
            return result
        normalized = str(mode or "").strip().casefold()
        if normalized not in ADAPTIVE_MODES:
            result = CommandResult.fail("Adaptive Updating must be Off or Continuous.")
            self.telemetry.record_command_result("set_adaptive_updating_mode", result)
            return result
        self.stable_adaptive_mode = normalized
        self._refresh_execution_target()
        state = self.stable_control_snapshot()
        result = CommandResult.ok("Adaptive Updating updated.", stable_control=state)
        self.telemetry.record_command_result("set_adaptive_updating_mode", result)
        return result

    def transformation_execution_snapshot(self):
        if self.transformation_execution_runtime is None:
            return None
        self._refresh_execution_target()
        snapshot = self.transformation_execution_runtime.snapshot()
        self.telemetry.set_metadata("transformation_execution", snapshot.to_telemetry_dict())
        return snapshot

    def set_plan_execution_enabled(self, enabled):
        if not self.transformation_execution_lab_enabled:
            result = CommandResult.fail("Transformation Execution Lab is not enabled.")
            self.telemetry.record_command_result("set_plan_execution_enabled", result)
            return result
        self.execution_enabled = bool(enabled)
        state = self.transformation_execution_snapshot()
        result = CommandResult.ok(
            "Plan execution enabled." if self.execution_enabled else "Plan execution disabled.",
            transformation_execution=state,
        )
        self.telemetry.record_command_result("set_plan_execution_enabled", result)
        return result

    def return_transformation_to_neutral(self):
        if not self.transformation_execution_lab_enabled:
            result = CommandResult.fail("Transformation Execution Lab is not enabled.")
            self.telemetry.record_command_result("return_transformation_to_neutral", result)
            return result
        self.execution_enabled = False
        if self.transformation_execution_runtime is not None:
            self.transformation_execution_runtime.reset()
        state = self.transformation_execution_snapshot()
        result = CommandResult.ok("Plan execution returned to neutral.", transformation_execution=state)
        self.telemetry.record_command_result("return_transformation_to_neutral", result)
        return result

    def _refresh_execution_target(self):
        if self.transformation_execution_controller is None:
            return
        try:
            self.transformation_execution_controller.recalculate_once()
        except Exception as exc:
            self.transformation_execution_runtime.set_worker_status("failed", str(exc))

    def _capture_calibration(self, command_name):
        if not self.calibrate_lock_lab_enabled:
            result = CommandResult.fail("Calibrate/Lock Lab is not enabled.")
            self.telemetry.record_command_result(command_name, result)
            return result
        snapshot = self.source_analysis_snapshot()
        ok, reason = self._validate_calibration_source(snapshot)
        if not ok:
            result = CommandResult.fail(reason, stable_control=self.stable_control_snapshot())
            self.telemetry.record_command_result(command_name, result)
            return result
        profile = snapshot["profile"]
        status = snapshot["status"]
        self._calibration_generation += 1
        warnings = []
        if profile.get("f1_hz") is not None or profile.get("f2_hz") is not None or profile.get("f3_hz") is not None:
            warnings.append("resonance estimates are weak descriptors")
        self._current_calibration = CalibrationSourceProfile(
            calibration_id=self._calibration_generation,
            captured_at=self.target_planner.clock(),
            source_snapshot_age_seconds=status.get("latest_snapshot_age_seconds"),
            source_reliability=str(profile.get("reliability") or "ready"),
            ready=bool(profile.get("ready")),
            voiced_duration_seconds=float(profile.get("voiced_duration_seconds") or 0.0),
            voiced_frame_count=int(profile.get("voiced_frame_count") or 0),
            voiced_frame_ratio=float(profile.get("voiced_frame_ratio") or 0.0),
            median_f0_hz=float(profile.get("median_f0_hz")),
            lower_f0_hz=float(profile.get("lower_f0_hz")),
            upper_f0_hz=float(profile.get("upper_f0_hz")),
            pitch_span_semitones=float(profile.get("pitch_span_semitones")),
            chest_energy_ratio=float(profile.get("chest_energy_ratio") or 0.0),
            low_mid_energy_ratio=float(profile.get("low_mid_energy_ratio") or 0.0),
            presence_energy_ratio=float(profile.get("presence_energy_ratio") or 0.0),
            brightness_energy_ratio=float(profile.get("brightness_energy_ratio") or 0.0),
            sibilance_energy_ratio=float(profile.get("sibilance_energy_ratio") or 0.0),
            spectral_tilt_db=profile.get("median_spectral_tilt_db"),
            f1_hz=profile.get("f1_hz"),
            f2_hz=profile.get("f2_hz"),
            f3_hz=profile.get("f3_hz"),
            resonance_confidence=float(profile.get("resonance_confidence") or 0.0),
            warnings=tuple(warnings),
        )
        self._refresh_stable_suggestion(force=True)
        state = self.stable_control_snapshot()
        result = CommandResult.ok("Source calibration captured.", stable_control=state)
        self.telemetry.record_command_result(command_name, result)
        return result

    def _validate_calibration_source(self, snapshot):
        if not snapshot:
            return False, "Source analysis is unavailable."
        status = dict(snapshot.get("status") or {})
        profile = dict(snapshot.get("profile") or {})
        if status.get("last_failure"):
            return False, "Source analyzer failure prevents calibration."
        if not status.get("active"):
            return False, "Source analyzer is not active."
        age = status.get("latest_snapshot_age_seconds")
        ok, age_or_reason = _required_calibration_number(
            age,
            "calibration source snapshot age",
            minimum=0.0,
        )
        if not ok:
            return False, age_or_reason
        if age_or_reason > STALE_SOURCE_AGE_SECONDS:
            return False, "Source profile is stale."
        if not profile.get("ready"):
            return False, "Source profile is still collecting."
        reliability = str(profile.get("reliability") or "").strip().casefold()
        if reliability in INVALID_CALIBRATION_RELIABILITIES:
            return False, "Calibration source reliability is not ready."
        required = (
            ("voiced_duration_seconds", "calibration voiced duration", 0.0, None),
            ("voiced_frame_count", "calibration voiced frame count", 1.0, None),
            ("voiced_frame_ratio", "calibration voiced frame ratio", 0.0, None),
            ("median_f0_hz", "calibration median F0", F0_MIN_HZ, F0_MAX_HZ),
            ("lower_f0_hz", "calibration lower F0", F0_MIN_HZ, F0_MAX_HZ),
            ("upper_f0_hz", "calibration upper F0", F0_MIN_HZ, F0_MAX_HZ),
            ("pitch_span_semitones", "calibration pitch span", 0.0, None),
        )
        values = {}
        for key, label, minimum, maximum in required:
            ok, value_or_reason = _required_calibration_number(
                profile.get(key),
                label,
                minimum=minimum,
                maximum=maximum,
            )
            if not ok:
                return False, value_or_reason
            values[key] = value_or_reason
        if values["lower_f0_hz"] > values["median_f0_hz"] or values["median_f0_hz"] > values["upper_f0_hz"]:
            return False, "Calibration pitch range is inconsistent."
        optional = (
            ("chest_energy_ratio", "calibration chest descriptor"),
            ("low_mid_energy_ratio", "calibration low-mid descriptor"),
            ("presence_energy_ratio", "calibration presence descriptor"),
            ("brightness_energy_ratio", "calibration brightness descriptor"),
            ("sibilance_energy_ratio", "calibration sibilance descriptor"),
            ("median_spectral_tilt_db", "calibration spectral tilt descriptor"),
            ("f1_hz", "calibration F1 descriptor"),
            ("f2_hz", "calibration F2 descriptor"),
            ("f3_hz", "calibration F3 descriptor"),
            ("resonance_confidence", "calibration resonance confidence"),
        )
        for key, label in optional:
            ok, reason = _optional_calibration_number(profile.get(key), label)
            if not ok:
                return False, reason
        return True, ""

    def _refresh_stable_suggestion(self, force=False):
        if not self.calibrate_lock_lab_enabled or self._current_calibration is None:
            return
        if not force and self._current_suggestion is not None:
            if (
                self._current_suggestion.calibration_id == self._current_calibration.calibration_id
                and self._current_suggestion.target_id == self.current_target_profile.target_id
                and self._current_suggestion.target_version == self.current_target_profile.schema_version
                and self._current_suggestion.character_strength == self.target_planner_strength
            ):
                return
        plan = self.target_planner.plan(
            self._current_calibration.source_snapshot(),
            self.current_target_profile,
            self.target_planner_strength,
        )
        self._suggestion_generation += 1
        valid = bool(plan.ready or plan.status == "degraded")
        differs = self._locked_transformation is None or plan != self._locked_transformation.plan
        self._current_suggestion = SuggestedTransformationSnapshot(
            valid=valid,
            suggestion_id=self._suggestion_generation,
            generated_at=self.target_planner.clock(),
            calibration_id=self._current_calibration.calibration_id,
            target_id=self.current_target_profile.target_id,
            target_version=self.current_target_profile.schema_version,
            character_strength=self.target_planner_strength,
            planner_status=plan.status,
            planner_confidence=plan.aggregate_confidence,
            plan=plan,
            differs_from_lock=differs,
            warnings=tuple(plan.warnings),
        )

    def _stable_execution_plan(self, source_snapshot, target_profile, strength):
        if self.stable_adaptive_mode == ADAPTIVE_CONTINUOUS:
            plan = self.target_planner.plan(source_snapshot, target_profile, strength)
            if not getattr(plan, "ready", False):
                return plan
            adjusted, _ = apply_manual_trim(plan, self._manual_trim)
            return adjusted
        if self._locked_transformation is None or not self._locked_transformation.valid:
            return None
        adjusted, _ = apply_manual_trim(self._locked_transformation.plan, self._manual_trim)
        return adjusted

    def _set_manual_trim(self, *, pitch_trim=None, formant_trim=None, command_name):
        if not self.calibrate_lock_lab_enabled:
            result = CommandResult.fail("Calibrate/Lock Lab is not enabled.")
            self.telemetry.record_command_result(command_name, result)
            return result
        try:
            pitch = self._manual_trim.requested_pitch_trim_st if pitch_trim is None else pitch_trim
            formant = self._manual_trim.requested_formant_trim_st if formant_trim is None else formant_trim
            self._trim_generation += 1
            self._manual_trim = manual_trim(pitch, formant, self._trim_generation)
        except ValueError as exc:
            result = CommandResult.fail(str(exc), stable_control=self.stable_control_snapshot())
            self.telemetry.record_command_result(command_name, result)
            return result
        self._refresh_execution_target()
        state = self.stable_control_snapshot()
        result = CommandResult.ok("Manual trim updated.", stable_control=state)
        self.telemetry.record_command_result(command_name, result)
        return result

    def _locked_snapshot(self, newer_suggestion_available=False):
        if self._locked_transformation is None:
            return None
        return LockedTransformationSnapshot(
            **{
                **self._locked_transformation.__dict__,
                "newer_suggestion_available": bool(newer_suggestion_available),
            }
        )

    def _suggestion_differs_from_lock(self):
        return bool(
            self._current_suggestion is not None
            and (
                self._locked_transformation is None
                or self._current_suggestion.plan != self._locked_transformation.plan
            )
        )

    def _newer_suggestion_available(self):
        return bool(
            self._locked_transformation is not None
            and self._current_suggestion is not None
            and self._current_suggestion.plan != self._locked_transformation.plan
        )

    def _target_changed_after_lock(self):
        return bool(
            self._locked_transformation is not None
            and self.current_target_profile.target_id != self._locked_transformation.target_id
        )

    def _strength_changed_after_lock(self):
        return bool(
            self._locked_transformation is not None
            and self.target_planner_strength != self._locked_transformation.character_strength
        )

    def _calibration_changed_after_lock(self):
        return bool(
            self._locked_transformation is not None
            and self._current_calibration is not None
            and self._current_calibration.calibration_id != self._locked_transformation.source_calibration_id
        )

    def set_target_planner_strength(self, strength_percent):
        if self.target_planner is None:
            result = CommandResult.fail("Target Planner Lab is not enabled.")
            self.telemetry.record_command_result("set_target_planner_strength", result)
            return result
        try:
            strength = float(strength_percent) / 100.0
            if strength < 0.0 or strength > 1.0:
                raise ValueError("Target Planner strength must be between 0 and 100.")
        except (TypeError, ValueError) as exc:
            result = CommandResult.fail(str(exc))
            self.telemetry.record_command_result("set_target_planner_strength", result)
            return result
        self.target_planner_strength = strength
        self._refresh_stable_suggestion(force=self.calibrate_lock_lab_enabled)
        state = self.target_planner_state()
        result = CommandResult.ok("Target Planner strength updated.", target_planner=state)
        self.telemetry.record_command_result("set_target_planner_strength", result)
        return result

    def update_target_profile(self, **changes):
        if self.target_planner is None:
            result = CommandResult.fail("Target Planner Lab is not enabled.")
            self.telemetry.record_command_result("update_target_profile", result)
            return result
        try:
            self.current_target_profile = replace_target(self.current_target_profile, **changes)
        except (TypeError, ValueError) as exc:
            result = CommandResult.fail(str(exc))
            self.telemetry.record_command_result("update_target_profile", result)
            return result
        self._refresh_stable_suggestion(force=self.calibrate_lock_lab_enabled)
        state = self.target_planner_state()
        result = CommandResult.ok("Target Planner profile updated.", target_planner=state)
        self.telemetry.record_command_result("update_target_profile", result)
        return result

    def load_target_reference(self, reference):
        if self.target_planner is None:
            result = CommandResult.fail("Target Planner Lab is not enabled.")
            self.telemetry.record_command_result("load_target_reference", result, reference=reference)
            return result
        references = {
            "neutral": DEFAULT_TARGET_PROFILE,
            "higher_brighter": HIGHER_BRIGHTER_REFERENCE,
            "lower_weightier": LOWER_WEIGHTIER_REFERENCE,
        }
        target = references.get(reference)
        if target is None:
            result = CommandResult.fail("Unknown target reference.")
            self.telemetry.record_command_result("load_target_reference", result, reference=reference)
            return result
        self.current_target_profile = target
        self._refresh_stable_suggestion(force=self.calibrate_lock_lab_enabled)
        state = self.target_planner_state()
        result = CommandResult.ok("Target reference loaded.", target_planner=state)
        self.telemetry.record_command_result("load_target_reference", result, reference=reference)
        return result

    def reset_target_planner(self):
        if self.target_planner is None:
            result = CommandResult.fail("Target Planner Lab is not enabled.")
            self.telemetry.record_command_result("reset_target_planner", result)
            return result
        self.current_target_profile = DEFAULT_TARGET_PROFILE
        self.target_planner_strength = 1.0
        self._refresh_stable_suggestion(force=self.calibrate_lock_lab_enabled)
        if self.source_voice_analyzer is not None:
            self.source_voice_analyzer.reset()
        state = self.target_planner_state()
        result = CommandResult.ok("Target Planner reset.", target_planner=state)
        self.telemetry.record_command_result("reset_target_planner", result)
        return result

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
        if self.transformation_execution_runtime is not None:
            self.telemetry.set_metadata(
                "transformation_execution",
                self.transformation_execution_runtime.snapshot().to_telemetry_dict(),
            )

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
            "selected_character_id": self.current_character_id,
            "character_strength": self.current_character_strength,
            "settings_issues": issues,
            "input_processing": self.current_input_processing.asdict(),
        }

    def input_processing_state(self):
        return self.current_input_processing.asdict()

    def formant_lab_state(self):
        if not self.formant_lab_enabled or self.transformation_execution_lab_enabled:
            return None
        status = self.engine.formant_lab_status()
        if status is None:
            return {
                "available": True,
                "active": False,
                "bypassed": self.engine.formant_lab.bypassed,
                "pitch_semitones": self.engine.formant_lab.pitch_semitones,
                "formant_semitones": self.engine.formant_lab.formant_semitones,
                "formant_factor": self.engine.formant_lab.formant_factor,
                "backend": "signalsmith",
                "latency_frames": 0,
                "estimated_added_ms": 0.0,
                "runtime_failure": "",
                "last_stable_pitch": 0.0,
                "last_stable_formant": 0.0,
            }
        state = status.asdict()
        state.update(
            {
                "bypassed": self.engine.formant_lab.bypassed,
                "pitch_semitones": self.engine.formant_lab.pitch_semitones,
                "formant_semitones": self.engine.formant_lab.formant_semitones,
                "formant_factor": self.engine.formant_lab.formant_factor,
            }
        )
        return state

    def update_formant_lab(self, *, enabled=None, pitch_semitones=None, formant_semitones=None, bypassed=None):
        if not self.formant_lab_enabled or self.transformation_execution_lab_enabled:
            result = CommandResult.fail("Formant Lab is not enabled.")
            self.telemetry.record_command_result("update_formant_lab", result)
            return result
        try:
            from voice_lab.effects.formant_lab import formant_lab_parameters

            current = self.engine.formant_lab.parameters
            if pitch_semitones is not None:
                pitch_semitones = self.config.validate_effect_parameters(1.0, 0.0, 4000, pitch_semitones).pitch
            parameters = formant_lab_parameters(
                enabled=current.enabled if enabled is None else enabled,
                bypassed=current.bypassed if bypassed is None else bypassed,
                pitch_semitones=current.pitch_semitones if pitch_semitones is None else pitch_semitones,
                formant_semitones=(
                    current.formant_semitones if formant_semitones is None else formant_semitones
                ),
            )
        except Exception as exc:
            result = CommandResult.fail(str(exc))
            self.telemetry.record_command_result("update_formant_lab", result)
            return result
        self.engine.set_formant_lab(parameters)
        state = self.formant_lab_state()
        self.telemetry.set_metadata("formant_lab", state)
        result = CommandResult.ok("Formant Lab updated.", formant_lab=state)
        self.telemetry.record_command_result("update_formant_lab", result)
        return result

    def reset_formant_lab(self):
        if not self.formant_lab_enabled or self.transformation_execution_lab_enabled:
            result = CommandResult.fail("Formant Lab is not enabled.")
            self.telemetry.record_command_result("reset_formant_lab", result)
            return result
        self.engine.reset_formant_lab()
        state = self.formant_lab_state()
        self.telemetry.set_metadata("formant_lab", state)
        result = CommandResult.ok("Formant Lab reset.", formant_lab=state)
        self.telemetry.record_command_result("reset_formant_lab", result)
        return result

    def input_processing_activity(self):
        activity = self.engine.input_processing_activity()
        self.telemetry.set_metadata("input_processing_activity", activity.asdict())
        return activity.asdict()

    def input_processing_parameter_ranges(self):
        return input_processing_ranges()

    def update_input_processing(self, processor, **changes):
        try:
            updated, issues = update_input_processing(
                self.current_input_processing,
                processor,
                **changes,
            )
        except (TypeError, ValueError) as exc:
            result = CommandResult.fail(str(exc), processor=processor)
            self.telemetry.record_command_result("update_input_processing", result)
            return result
        if issues:
            self._record_validation_failure("update_input_processing", issues, processor=processor)
            result = CommandResult.fail(
                "Invalid input processing settings.",
                issues=issues,
                processor=processor,
            )
            self.telemetry.record_command_result("update_input_processing", result)
            return result
        self.current_input_processing = updated
        self.engine.set_input_processing(updated)
        self._update_operator_settings(input_processing=updated)
        self.telemetry.set_metadata("input_processing", updated.asdict())
        result = CommandResult.ok("Input processing updated.", input_processing=updated.asdict())
        self.telemetry.record_command_result("update_input_processing", result, processor=processor)
        return result

    def reset_input_processing(self):
        if self.current_input_processing == DEFAULT_INPUT_PROCESSING_SETTINGS:
            result = CommandResult.ok(
                "Input processing already at defaults.",
                input_processing=self.current_input_processing.asdict(),
            )
            self.telemetry.record_command_result("reset_input_processing", result)
            return result
        self.current_input_processing = DEFAULT_INPUT_PROCESSING_SETTINGS
        self.engine.set_input_processing(self.current_input_processing)
        self._update_operator_settings(input_processing=self.current_input_processing)
        self.telemetry.set_metadata("input_processing", self.current_input_processing.asdict())
        result = CommandResult.ok(
            "Input processing reset.",
            input_processing=self.current_input_processing.asdict(),
        )
        self.telemetry.record_command_result("reset_input_processing", result)
        return result

    def voice_characters(self):
        return tuple(character.asdict() for character in voice_characters())

    def custom_preset_names(self):
        protected = protected_voice_names()
        return tuple(name for name in self.preset_names() if name not in protected)

    def voice_selector_entries(self):
        entries = [{"kind": "section", "label": "Built-in Voices", "value": None}]
        for character in voice_characters():
            entries.append(
                {
                    "kind": "built_in",
                    "label": character.display_name,
                    "value": character.id,
                    "description": character.description,
                }
            )
        custom_names = self.custom_preset_names()
        if custom_names:
            entries.append({"kind": "section", "label": "Custom Voices", "value": None})
            for name in custom_names:
                entries.append(
                    {
                        "kind": "custom",
                        "label": name,
                        "value": name,
                        "description": "Saved custom voice",
                    }
                )
        return tuple(entries)

    def active_voice_state(self):
        character = character_by_id(self.current_character_id)
        character_name = character.display_name if character else "Unknown"
        if self.effects_bypassed:
            text = f"Voice effects bypassed - {self._active_voice_base_text()} remains selected"
        else:
            text = self._active_voice_base_text()
        return {
            "kind": self.active_voice_kind,
            "character_id": self.current_character_id,
            "character_name": character_name,
            "custom_preset": self.current_custom_preset,
            "strength": self.current_character_strength,
            "effects_bypassed": self.effects_bypassed,
            "parameters": dict(self.current_effect_params),
            "text": text,
        }

    def select_voice_character(self, character_id, strength=None, persist=True):
        character = character_by_id(character_id)
        if character is None:
            result = CommandResult.fail(f"Unknown voice character: {character_id}")
            self.telemetry.record_command_result("select_voice_character", result, character_id=character_id)
            return result
        strength = self.current_character_strength if strength is None else strength
        try:
            strength = validate_strength(strength)
            preset, effect_parameters = resolve_character_parameters(character.id, strength)
        except ValueError as exc:
            result = CommandResult.fail(str(exc), character_id=character_id)
            self.telemetry.record_command_result("select_voice_character", result, character_id=character_id)
            return result
        applied = self._apply_effect_validation(
            preset,
            effect_parameters,
            persist_settings=False,
            mark_custom=False,
        )
        if not applied.success:
            return applied
        self.current_character_id = character.id
        self.current_character_strength = strength
        self.current_custom_preset = None
        self.current_selected_preset = character.compatibility_preset_name or character.display_name
        self.active_voice_kind = "character"
        if persist:
            self._update_operator_settings(
                selected_character_id=character.id,
                character_strength=strength,
                selected_preset=self.current_selected_preset,
            )
        self._publish_voice_metadata()
        result = CommandResult.ok(
            f"Voice character: {character.display_name}",
            character=character.asdict(),
            strength=strength,
            params=preset.copy(),
        )
        self.telemetry.record_event(
            "voice.character_selected",
            "info",
            result.message,
            character_id=character.id,
            strength=strength,
        )
        self.telemetry.record_command_result("select_voice_character", result, character_id=character.id)
        return result

    def select_voice(self, kind, value, strength=None, persist=True):
        if kind == "built_in":
            return self.select_voice_character(value, strength=strength, persist=persist)
        if kind == "custom":
            return self.select_preset(value, persist=persist)
        result = CommandResult.fail("Unsupported voice selection.")
        self.telemetry.record_command_result("select_voice", result, kind=kind, value=value)
        return result

    def set_character_strength(self, value, persist=True):
        try:
            strength = validate_strength(value)
        except ValueError as exc:
            result = CommandResult.fail(str(exc), strength=value)
            self.telemetry.record_command_result("set_character_strength", result)
            return result
        return self.select_voice_character(self.current_character_id, strength=strength, persist=persist)

    def set_effects_bypassed(self, enabled):
        enabled = bool(enabled)
        if enabled == self.effects_bypassed:
            result = CommandResult.ok("Voice effects bypass unchanged.", effects_bypassed=enabled)
            self.telemetry.record_command_result("set_effects_bypassed", result)
            return result
        self.effects_bypassed = enabled
        self.engine.set_effects_bypassed(enabled)
        if self.transformation_execution_runtime is not None:
            self.transformation_execution_runtime.set_bypassed(enabled)
        event_type = "voice.bypass_enabled" if enabled else "voice.bypass_disabled"
        message = "Voice effects bypassed." if enabled else "Voice effects resumed."
        self._publish_voice_metadata()
        self.telemetry.record_event(event_type, "info", message, active_voice=self.active_voice_state())
        result = CommandResult.ok(message, effects_bypassed=enabled)
        self.telemetry.record_command_result("set_effects_bypassed", result)
        return result

    def reset_voice(self):
        self.set_effects_bypassed(False)
        return self.select_voice_character(
            NATURAL_CHARACTER_ID,
            strength=DEFAULT_CHARACTER_STRENGTH,
            persist=True,
        )

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
        mark_custom=True,
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
        new_effect_params = {
            "gain": gain,
            "robot": robot,
            "lowpass": lowpass,
            "pitch": pitch,
        }
        effect_changed = new_effect_params != self.current_effect_params
        self.current_effect_params = new_effect_params
        if mark_custom and effect_changed:
            self.active_voice_kind = "unsaved"
            self.current_custom_preset = None
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
        self._publish_voice_metadata()
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
        character = character_by_compatibility_preset(name)
        if character is not None:
            return self.select_voice_character(character.id, persist=persist)
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
        self.current_selected_preset = name
        self.current_character_id = NATURAL_CHARACTER_ID
        self.current_character_strength = DEFAULT_CHARACTER_STRENGTH
        self.current_custom_preset = name
        self.active_voice_kind = "custom"
        if persist:
            self._update_operator_settings(
                selected_preset=name,
                selected_character_id=None,
                character_strength=DEFAULT_CHARACTER_STRENGTH,
            )
        self._apply_effect_validation(
            selection.preset,
            effect_parameters,
            persist_settings=False,
            mark_custom=False,
        )
        self._publish_voice_metadata()
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
        validation = self.validate_custom_voice_name(name, allow_existing=True)
        if not validation.success:
            self.telemetry.record_command_result("save_preset", validation)
            return validation
        normalized_name = validation.metadata["name"]
        if validation.metadata.get("conflict"):
            result = CommandResult.fail(
                "Custom voice already exists. Confirm overwrite before saving.",
                name=normalized_name,
                conflict=True,
            )
            self.telemetry.record_command_result("save_preset", result, preset=name)
            return result
        return self.save_custom_voice(normalized_name, params, overwrite=True)

    def save_custom_voice(self, name, params, overwrite=False):
        validation = self.validate_custom_voice_name(name, allow_existing=overwrite)
        if not validation.success:
            self.telemetry.record_command_result("save_custom_voice", validation)
            return validation
        normalized_name = validation.metadata["name"]
        if validation.metadata.get("conflict") and not overwrite:
            result = CommandResult.fail(
                "Custom voice already exists. Confirm overwrite before saving.",
                name=normalized_name,
                conflict=True,
            )
            self.telemetry.record_command_result("save_custom_voice", result, preset=normalized_name)
            return result
        saved = self.config.save_preset(normalized_name, params)
        if not saved.success:
            result = CommandResult.fail(
                saved.message,
                preset=normalized_name,
                issues=saved.issues,
            )
            if saved.issues:
                self._record_validation_failure("save_custom_voice", saved.issues, preset=normalized_name)
            self.telemetry.record_command_result("save_custom_voice", result, preset=normalized_name)
            return result
        self.select_preset(normalized_name)
        result = CommandResult.ok(saved.message, name=normalized_name, params=saved.preset.copy())
        self.telemetry.record_command_result("save_custom_voice", result, preset=normalized_name)
        return result

    def delete_preset(self, name):
        return self.delete_custom_voice(name)

    def rename_custom_voice(self, old_name, new_name):
        if old_name not in self.custom_preset_names():
            result = CommandResult.fail("Select a saved custom voice to rename.")
            self.telemetry.record_command_result("rename_custom_voice", result, preset=old_name)
            return result
        validation = self.validate_custom_voice_name(new_name)
        if not validation.success:
            self.telemetry.record_command_result("rename_custom_voice", validation, preset=old_name)
            return validation
        normalized_name = validation.metadata["name"]
        renamed = self.config.rename_preset(old_name, normalized_name)
        if not renamed.success:
            result = CommandResult.fail(renamed.message, issues=renamed.issues)
            self.telemetry.record_command_result("rename_custom_voice", result, preset=old_name)
            return result
        if self.current_custom_preset == old_name:
            self.current_custom_preset = normalized_name
            self.current_selected_preset = normalized_name
            self.active_voice_kind = "custom"
            self._update_operator_settings(
                selected_preset=normalized_name,
                selected_character_id=None,
                character_strength=DEFAULT_CHARACTER_STRENGTH,
            )
        self._publish_voice_metadata()
        result = CommandResult.ok(
            f"Renamed custom voice: {normalized_name}",
            old_name=old_name,
            name=normalized_name,
            params=renamed.preset.copy(),
        )
        self.telemetry.record_command_result("rename_custom_voice", result, preset=normalized_name)
        return result

    def duplicate_custom_voice(self, source_name, new_name):
        if source_name not in self.custom_preset_names():
            result = CommandResult.fail("Select a saved custom voice to duplicate.")
            self.telemetry.record_command_result("duplicate_custom_voice", result, preset=source_name)
            return result
        validation = self.validate_custom_voice_name(new_name)
        if not validation.success:
            self.telemetry.record_command_result("duplicate_custom_voice", validation, preset=source_name)
            return validation
        normalized_name = validation.metadata["name"]
        duplicated = self.config.duplicate_preset(source_name, normalized_name)
        if not duplicated.success:
            result = CommandResult.fail(duplicated.message, issues=duplicated.issues)
            self.telemetry.record_command_result("duplicate_custom_voice", result, preset=source_name)
            return result
        selected = self.select_preset(normalized_name)
        if not selected.success:
            return selected
        result = CommandResult.ok(
            f"Duplicated custom voice: {normalized_name}",
            source_name=source_name,
            name=normalized_name,
            params=duplicated.preset.copy(),
        )
        self.telemetry.record_command_result("duplicate_custom_voice", result, preset=normalized_name)
        return result

    def delete_custom_voice(self, name):
        if name in protected_voice_names() or name not in self.custom_preset_names():
            result = CommandResult.fail("Built-in voice characters cannot be deleted")
            self.telemetry.record_command_result("delete_preset", result, preset=name)
            return result
        deleted = self.config.delete_preset(name)
        if not deleted.success:
            result = CommandResult.fail(deleted.message)
            self.telemetry.record_command_result("delete_preset", result, preset=name)
            return result
        params = None
        if self.current_custom_preset == name:
            reset = self.select_voice_character(NATURAL_CHARACTER_ID)
            params = reset.metadata.get("params") if reset.success else None
        result = CommandResult.ok(deleted.message, name=name, params=params)
        self.telemetry.record_command_result("delete_preset", result, preset=name)
        return result

    def validate_custom_voice_name(self, name, allow_existing=False):
        normalized_name = str(name or "").strip()
        if not normalized_name:
            return CommandResult.fail("Custom voice name is required.", reason="empty")
        protected = self._logical_name_map(protected_voice_names())
        reserved = self._logical_name_map(RESERVED_CUSTOM_VOICE_NAMES)
        logical = self._logical_name(normalized_name)
        if logical in protected:
            return CommandResult.fail(
                "Built-in voice names are reserved.",
                reason="reserved",
                name=normalized_name,
            )
        if logical in reserved:
            return CommandResult.fail(
                "That voice name is reserved.",
                reason="reserved",
                name=normalized_name,
            )
        custom_names = self.custom_preset_names()
        custom_logical = self._logical_name_map(custom_names)
        conflict_name = custom_logical.get(logical)
        if conflict_name is not None:
            if allow_existing and conflict_name == normalized_name:
                return CommandResult.ok(name=normalized_name, conflict=True, existing_name=conflict_name)
            return CommandResult.fail(
                "A custom voice with that name already exists.",
                reason="conflict",
                name=normalized_name,
                existing_name=conflict_name,
            )
        return CommandResult.ok(name=normalized_name, conflict=False)

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
        self.level_monitor.reset("starting")
        if self.source_voice_analyzer is not None:
            self.source_voice_analyzer.start()
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
        self.execution_enabled = False
        if self.transformation_execution_controller is not None:
            self.transformation_execution_controller.start()
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
            self.execution_enabled = False
            if self.transformation_execution_controller is not None:
                self.transformation_execution_controller.stop()
            self.engine.stop()
            if self.source_voice_analyzer is not None:
                self.source_voice_analyzer.stop()
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
        self.level_monitor.reset("stopped")
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
        if self.transformation_execution_controller is not None:
            self.transformation_execution_controller.stop()
        if self.source_voice_analyzer is not None:
            self.source_voice_analyzer.close()
        self.engine.stop()

    def _restore_voice_state(self):
        settings = self._operator_settings()
        if self.active_voice_kind == "custom" and settings.selected_preset:
            self.select_preset(settings.selected_preset, persist=False)
            return
        if character_by_id(self.current_character_id) is not None:
            self.select_voice_character(
                self.current_character_id,
                strength=settings.character_strength,
                persist=False,
            )
            return
        self.select_voice_character(NATURAL_CHARACTER_ID, persist=False)

    def _apply_effect_validation(
        self,
        preset_params,
        effect_parameters,
        *,
        persist_settings,
        mark_custom,
    ):
        return self.apply_effect_parameters(
            gain=effect_parameters.gain,
            robot=effect_parameters.robot,
            lowpass=effect_parameters.lowpass,
            pitch=effect_parameters.pitch,
            monitor_enabled=self.current_monitor_enabled,
            monitor_volume=self.current_monitor_volume,
            soundboard_volume=self.current_soundboard_volume,
            persist_settings=persist_settings,
            mark_custom=mark_custom,
        )

    def _publish_voice_metadata(self):
        state = self.active_voice_state()
        self.telemetry.set_metadata("effects_bypassed", self.effects_bypassed)
        self.telemetry.set_metadata("active_voice", state)
        self.telemetry.set_metadata("selected_character_id", self.current_character_id)
        self.telemetry.set_metadata("selected_character_strength", self.current_character_strength)

    def _active_voice_base_text(self):
        if self.active_voice_kind == "custom" and self.current_custom_preset:
            return f"Active voice: Custom - {self.current_custom_preset}"
        if self.active_voice_kind == "unsaved":
            return "Active voice: Custom - Unsaved"
        character = character_by_id(self.current_character_id)
        if character is None:
            return "Active voice: Unknown"
        if character.id == NATURAL_CHARACTER_ID or not character.strength_enabled:
            return f"Active voice: {character.display_name}"
        value = int(self.current_character_strength)
        return f"Active voice: {character.display_name} - {value}%"

    def _logical_name(self, name):
        return str(name or "").strip().casefold()

    def _logical_name_map(self, names):
        return {self._logical_name(name): name for name in names}

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
        if self.source_voice_analyzer is not None:
            self.source_voice_analyzer.stop()
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
        self.level_monitor.reset("failed")
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
