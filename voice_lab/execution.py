from __future__ import annotations

import math
import threading
import time
from dataclasses import asdict, dataclass, field
from numbers import Real

from voice_lab.config.input_processing import (
    COMPRESSOR_ATTACK_RANGE,
    COMPRESSOR_MAKEUP_RANGE,
    COMPRESSOR_RATIO_RANGE,
    COMPRESSOR_RELEASE_RANGE,
    COMPRESSOR_THRESHOLD_RANGE,
    LIMITER_CEILING_RANGE,
    LIMITER_RELEASE_RANGE,
    CompressorSettings,
    InputProcessingSettings,
    LimiterSettings,
)
from voice_lab.effects.formant_lab import formant_lab_parameters
SUPPORTED_CAPABILITIES = (
    "adaptive_pitch_center",
    "formant_shift",
    "compressor",
    "limiter",
)
KNOWN_UNSUPPORTED_CAPABILITIES = (
    "pitch_range_mapping",
    "parametric_eq",
    "spectral_tilt_shaping",
    "breathiness",
    "harmonic_enhancement",
    "de_esser",
)
CAPABILITY_DISPLAY_ORDER = SUPPORTED_CAPABILITIES + KNOWN_UNSUPPORTED_CAPABILITIES
EXECUTION_CONTROLLER_CADENCE_HZ = 10.0
EXECUTION_PLAN_STALE_SECONDS = 2.0
EXECUTION_DEADBAND_ST = 0.01
MAX_EXECUTION_PITCH_ST = 12.0
MAX_EXECUTION_FORMANT_ST = 2.0


@dataclass(frozen=True)
class TransformationExecutionTarget:
    execution_generation: int = 0
    source_plan_generation: float | None = None
    target_id: str = ""
    target_version: str = ""
    character_strength: float = 0.0
    user_enabled: bool = False
    plan_status: str = "disabled"
    plan_confidence: float = 0.0
    source_age_seconds: float | None = None
    requested_supported_capabilities: tuple[str, ...] = ()
    requested_unsupported_capabilities: tuple[str, ...] = ()
    target_pitch_semitones: float = 0.0
    target_formant_semitones: float = 0.0
    compressor_override_active: bool = False
    compressor_target: CompressorSettings = field(default_factory=CompressorSettings)
    limiter_override_active: bool = False
    limiter_target: LimiterSettings = field(default_factory=LimiterSettings)
    partial_execution: bool = False
    blocked_reason: str = ""
    warnings: tuple[str, ...] = ()

    def asdict(self):
        data = asdict(self)
        data["requested_supported_capabilities"] = tuple(self.requested_supported_capabilities)
        data["requested_unsupported_capabilities"] = tuple(self.requested_unsupported_capabilities)
        data["warnings"] = tuple(self.warnings)
        return data


@dataclass(frozen=True)
class TransformationExecutionStatus:
    status: str = "disabled"
    message: str = ""
    supported_capabilities: tuple[str, ...] = SUPPORTED_CAPABILITIES
    unsupported_capabilities: tuple[str, ...] = KNOWN_UNSUPPORTED_CAPABILITIES

    def asdict(self):
        return asdict(self)


@dataclass(frozen=True)
class TransformationExecutionSnapshot:
    enabled: bool
    status: str
    active: bool
    neutral: bool
    bypassed: bool
    transitioning: bool
    current_pitch_semitones: float
    target_pitch_semitones: float
    current_formant_semitones: float
    target_formant_semitones: float
    current_compressor: dict
    baseline_compressor: dict
    plan_compressor: dict
    compressor_override_active: bool
    current_limiter: dict
    baseline_limiter: dict
    plan_limiter: dict
    limiter_override_active: bool
    smoothing_settled: bool
    smoothing_progress: float
    plan_age_seconds: float | None
    last_accepted_generation: int
    last_rejected_generation: int
    controller_worker_status: str
    last_failure: str
    execution_generation: int
    target_id: str
    target_version: str
    character_strength: float
    plan_status: str
    plan_confidence: float
    source_age_seconds: float | None
    requested_supported_capabilities: tuple[str, ...]
    requested_unsupported_capabilities: tuple[str, ...]
    partial_execution: bool
    blocked_reason: str
    warnings: tuple[str, ...]
    latency_frames: int = 0
    latency_ms_at_48k: float = 0.0

    def asdict(self):
        return asdict(self)


class TransformationExecutionRuntime:
    def __init__(self, baseline_settings=None, clock=time.monotonic):
        settings = baseline_settings or InputProcessingSettings()
        self._clock = clock
        self._baseline_compressor = settings.compressor
        self._baseline_limiter = settings.limiter
        self._target = TransformationExecutionTarget(
            compressor_target=self._baseline_compressor,
            limiter_target=self._baseline_limiter,
        )
        self._status = "disabled"
        self._enabled = False
        self._bypassed = False
        self._current_pitch = 0.0
        self._current_formant = 0.0
        self._formant_parameters = formant_lab_parameters()
        self._current_compressor = self._baseline_compressor
        self._current_limiter = self._baseline_limiter
        self._last_accepted_generation = 0
        self._last_rejected_generation = 0
        self._worker_status = "stopped"
        self._last_failure = ""
        self._latency_frames = 0

    def set_baseline(self, settings):
        self._baseline_compressor = settings.compressor
        self._baseline_limiter = settings.limiter
        if not self._target.compressor_override_active:
            self._current_compressor = settings.compressor
        if not self._target.limiter_override_active:
            self._current_limiter = settings.limiter

    def publish_target(self, target, status):
        self._target = target
        self._enabled = bool(target.user_enabled)
        self._status = status
        if status in {"blocked", "stale_plan", "controller_failure"}:
            self._last_rejected_generation = max(self._last_rejected_generation, target.execution_generation)
        elif target.execution_generation:
            self._last_accepted_generation = target.execution_generation

    def set_worker_status(self, status, failure=""):
        self._worker_status = status
        self._last_failure = failure
        if failure:
            neutral = self._target_neutral("controller failure")
            self.publish_target(neutral, "controller_failure")

    def set_bypassed(self, bypassed):
        self._bypassed = bool(bypassed)

    def set_latency_frames(self, frames):
        self._latency_frames = int(frames or 0)

    def reset(self):
        self._target = self._target_neutral("")
        self._status = "disabled"
        self._enabled = False
        self._current_pitch = 0.0
        self._current_formant = 0.0
        self._formant_parameters = formant_lab_parameters()
        self._current_compressor = self._baseline_compressor
        self._current_limiter = self._baseline_limiter

    def formant_parameters_for_block(self, frames, sample_rate):
        previous_pitch = self._current_pitch
        previous_formant = self._current_formant
        self._smooth(frames, sample_rate)
        if previous_pitch != self._current_pitch or previous_formant != self._current_formant:
            self._formant_parameters = formant_lab_parameters(
                enabled=True,
                bypassed=False,
                pitch_semitones=self._current_pitch,
                formant_semitones=self._current_formant,
            )
        return self._formant_parameters

    def compressor_settings_for_block(self):
        return self._current_compressor

    def limiter_settings_for_block(self):
        return self._current_limiter

    def snapshot(self):
        target = self._target
        pitch_delta = abs(self._current_pitch - target.target_pitch_semitones)
        formant_delta = abs(self._current_formant - target.target_formant_semitones)
        dynamics_settled = (
            self._current_compressor == self._effective_compressor_target()
            and self._current_limiter == self._effective_limiter_target()
        )
        settled = pitch_delta <= EXECUTION_DEADBAND_ST and formant_delta <= EXECUTION_DEADBAND_ST and dynamics_settled
        status = "bypassed" if self._bypassed else self._status
        return TransformationExecutionSnapshot(
            enabled=self._enabled,
            status=status,
            active=status in {"active", "active_partial", "transitioning"},
            neutral=abs(target.target_pitch_semitones) <= EXECUTION_DEADBAND_ST
            and abs(target.target_formant_semitones) <= EXECUTION_DEADBAND_ST
            and not target.compressor_override_active
            and not target.limiter_override_active,
            bypassed=self._bypassed,
            transitioning=not settled,
            current_pitch_semitones=self._current_pitch,
            target_pitch_semitones=target.target_pitch_semitones,
            current_formant_semitones=self._current_formant,
            target_formant_semitones=target.target_formant_semitones,
            current_compressor=self._current_compressor.asdict(),
            baseline_compressor=self._baseline_compressor.asdict(),
            plan_compressor=target.compressor_target.asdict(),
            compressor_override_active=target.compressor_override_active,
            current_limiter=self._current_limiter.asdict(),
            baseline_limiter=self._baseline_limiter.asdict(),
            plan_limiter=target.limiter_target.asdict(),
            limiter_override_active=target.limiter_override_active,
            smoothing_settled=settled,
            smoothing_progress=1.0 if settled else 0.0,
            plan_age_seconds=(self._clock() - target.source_plan_generation)
            if target.source_plan_generation is not None
            else None,
            last_accepted_generation=self._last_accepted_generation,
            last_rejected_generation=self._last_rejected_generation,
            controller_worker_status=self._worker_status,
            last_failure=self._last_failure,
            execution_generation=target.execution_generation,
            target_id=target.target_id,
            target_version=target.target_version,
            character_strength=target.character_strength,
            plan_status=target.plan_status,
            plan_confidence=target.plan_confidence,
            source_age_seconds=target.source_age_seconds,
            requested_supported_capabilities=target.requested_supported_capabilities,
            requested_unsupported_capabilities=target.requested_unsupported_capabilities,
            partial_execution=target.partial_execution,
            blocked_reason=target.blocked_reason,
            warnings=target.warnings,
            latency_frames=self._latency_frames,
            latency_ms_at_48k=(self._latency_frames / 48000.0) * 1000.0,
        )

    def _smooth(self, frames, sample_rate):
        step = max(0.02, min(1.0, float(frames or 0) / max(float(sample_rate or 48000), 1.0) / 0.08))
        target = self._target
        self._current_pitch = _move_toward(self._current_pitch, target.target_pitch_semitones, step)
        self._current_formant = _move_toward(self._current_formant, target.target_formant_semitones, step)
        self._current_compressor = self._effective_compressor_target()
        self._current_limiter = self._effective_limiter_target()

    def _effective_compressor_target(self):
        return self._target.compressor_target if self._target.compressor_override_active else self._baseline_compressor

    def _effective_limiter_target(self):
        return self._target.limiter_target if self._target.limiter_override_active else self._baseline_limiter

    def _target_neutral(self, reason):
        return TransformationExecutionTarget(
            execution_generation=self._target.execution_generation + 1,
            target_id=self._target.target_id,
            target_version=self._target.target_version,
            compressor_target=self._baseline_compressor,
            limiter_target=self._baseline_limiter,
            blocked_reason=reason,
        )


class TransformationExecutor:
    def __init__(self):
        self._generation = 0

    def map_plan(self, plan, *, enabled, baseline_settings, effects_bypassed=False):
        self._generation += 1
        baseline_compressor = baseline_settings.compressor
        baseline_limiter = baseline_settings.limiter
        supported, unsupported = _partition_capabilities(getattr(plan, "required_capabilities", ()))
        warnings = tuple(getattr(plan, "warnings", ()))
        base = {
            "execution_generation": self._generation,
            "source_plan_generation": getattr(plan, "created_at", None),
            "target_id": getattr(plan, "target_id", ""),
            "target_version": getattr(plan, "target_version", ""),
            "character_strength": float(getattr(plan, "character_strength", 0.0) or 0.0),
            "user_enabled": bool(enabled),
            "plan_status": getattr(plan, "status", "unavailable"),
            "plan_confidence": float(getattr(plan, "aggregate_confidence", 0.0) or 0.0),
            "source_age_seconds": getattr(plan, "source_profile_age_seconds", None),
            "requested_supported_capabilities": supported,
            "requested_unsupported_capabilities": unsupported,
            "compressor_target": baseline_compressor,
            "limiter_target": baseline_limiter,
            "warnings": warnings,
        }
        if effects_bypassed:
            return TransformationExecutionTarget(**base), "bypassed"
        if not enabled:
            return TransformationExecutionTarget(**base), "disabled"
        if plan is None:
            return TransformationExecutionTarget(**base, blocked_reason="waiting for plan"), "waiting_for_source"
        if getattr(plan, "stale", False):
            return TransformationExecutionTarget(**base, blocked_reason="source profile is stale"), "stale_plan"
        if not getattr(plan, "ready", False):
            status = getattr(plan, "status", "waiting_for_source")
            if status not in {"waiting_for_source", "collecting_source", "invalid_target", "planner_failure"}:
                status = "blocked"
            return TransformationExecutionTarget(**base, blocked_reason=getattr(plan, "unavailable_reason", "")), status
        if base["character_strength"] <= 0.0:
            return TransformationExecutionTarget(**base), "ready_neutral"

        try:
            pitch = _validated_pitch(plan.pitch.applied_pitch_shift_st, supported)
            formant = _validated_formant(plan.formant.applied_formant_shift_st, supported)
            compressor_active, compressor = _compressor_target(plan, supported, baseline_compressor)
            limiter_active, limiter = _limiter_target(plan, supported, baseline_limiter)
        except ValueError as exc:
            return TransformationExecutionTarget(**base, blocked_reason=str(exc)), "blocked"

        target = TransformationExecutionTarget(
            **{key: value for key, value in base.items() if key not in {"compressor_target", "limiter_target"}},
            target_pitch_semitones=pitch,
            target_formant_semitones=formant,
            compressor_override_active=compressor_active,
            compressor_target=compressor,
            limiter_override_active=limiter_active,
            limiter_target=limiter,
            partial_execution=bool(unsupported),
        )
        return target, "active_partial" if unsupported else "active"


class TransformationExecutionController:
    def __init__(
        self,
        *,
        runtime,
        executor,
        planner,
        source_snapshot_getter,
        target_profile_getter,
        strength_getter,
        baseline_getter,
        enabled_getter,
        bypass_getter,
        cadence_hz=EXECUTION_CONTROLLER_CADENCE_HZ,
    ):
        self.runtime = runtime
        self.executor = executor
        self.planner = planner
        self.source_snapshot_getter = source_snapshot_getter
        self.target_profile_getter = target_profile_getter
        self.strength_getter = strength_getter
        self.baseline_getter = baseline_getter
        self.enabled_getter = enabled_getter
        self.bypass_getter = bypass_getter
        self.cadence_hz = float(cadence_hz)
        self._stop = threading.Event()
        self._thread = None
        self._latest_plan = None
        self._latest_target = None
        self.recalculation_count = 0

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self.runtime.set_worker_status("running")
        self._thread = threading.Thread(target=self._run, name="TransformationExecutionController", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
        self._thread = None
        self.runtime.reset()
        self.runtime.set_worker_status("stopped")

    def recalculate_once(self):
        baseline = self.baseline_getter()
        self.runtime.set_baseline(baseline)
        plan = self.planner.plan(self.source_snapshot_getter(), self.target_profile_getter(), self.strength_getter())
        target, status = self.executor.map_plan(
            plan,
            enabled=self.enabled_getter(),
            baseline_settings=baseline,
            effects_bypassed=self.bypass_getter(),
        )
        previous = self._latest_target
        if previous is None or _target_changed(previous, target):
            self.runtime.publish_target(target, status)
            self._latest_target = target
        self._latest_plan = plan
        self.recalculation_count += 1
        return target, status

    def latest_plan(self):
        return self._latest_plan

    def latest_target(self):
        return self._latest_target

    def retained_counts(self):
        return {"plans": 1 if self._latest_plan is not None else 0, "targets": 1 if self._latest_target is not None else 0}

    def _run(self):
        interval = 1.0 / max(self.cadence_hz, 1.0)
        while not self._stop.wait(interval):
            try:
                self.recalculate_once()
                self.runtime.set_worker_status("running")
            except Exception as exc:
                self.runtime.set_worker_status("failed", str(exc))


def _move_toward(current, target, fraction):
    current = float(current)
    target = float(target)
    if not math.isfinite(current):
        current = 0.0
    if not math.isfinite(target):
        target = 0.0
    delta = target - current
    if abs(delta) <= EXECUTION_DEADBAND_ST:
        return target
    return current + delta * max(0.0, min(1.0, float(fraction)))


def _partition_capabilities(capabilities):
    seen = set()
    supported = []
    unsupported = []
    for capability in tuple(capabilities or ()):
        if capability in seen:
            continue
        seen.add(capability)
        if capability in SUPPORTED_CAPABILITIES:
            supported.append(capability)
        else:
            unsupported.append(capability)
    supported = tuple(name for name in SUPPORTED_CAPABILITIES if name in supported)
    unsupported = tuple(
        name for name in CAPABILITY_DISPLAY_ORDER if name in unsupported
    ) + tuple(sorted(name for name in unsupported if name not in CAPABILITY_DISPLAY_ORDER))
    return supported, unsupported


def _validated_pitch(value, supported):
    value = _finite_number(value, "pitch shift")
    if abs(value) > MAX_EXECUTION_PITCH_ST:
        raise ValueError("pitch shift outside execution range")
    if abs(value) > EXECUTION_DEADBAND_ST and "adaptive_pitch_center" not in supported:
        raise ValueError("plan omitted adaptive_pitch_center capability")
    return value


def _validated_formant(value, supported):
    value = _finite_number(value, "formant shift")
    if abs(value) > MAX_EXECUTION_FORMANT_ST:
        raise ValueError("formant shift outside restrained execution range")
    if abs(value) > EXECUTION_DEADBAND_ST and "formant_shift" not in supported:
        raise ValueError("plan omitted formant_shift capability")
    return value


def _compressor_target(plan, supported, baseline):
    if "compressor" not in supported or getattr(plan, "character_strength", 0.0) <= 0.0:
        return False, baseline
    c = plan.dynamics.compressor
    if not c.compressor_enabled:
        return False, baseline
    return True, CompressorSettings(
        enabled=True,
        threshold_dbfs=_range("compressor threshold", c.compressor_threshold_dbfs, COMPRESSOR_THRESHOLD_RANGE),
        ratio=_range("compressor ratio", c.compressor_ratio, COMPRESSOR_RATIO_RANGE),
        attack_ms=_range("compressor attack", c.compressor_attack_ms, COMPRESSOR_ATTACK_RANGE),
        release_ms=_range("compressor release", c.compressor_release_ms, COMPRESSOR_RELEASE_RANGE),
        makeup_gain_db=_range("compressor makeup", c.compressor_makeup_gain_db, COMPRESSOR_MAKEUP_RANGE),
    )


def _limiter_target(plan, supported, baseline):
    if "limiter" not in supported or getattr(plan, "character_strength", 0.0) <= 0.0:
        return False, baseline
    l = plan.dynamics.limiter
    if not l.limiter_enabled:
        return False, baseline
    return True, LimiterSettings(
        enabled=True,
        ceiling_dbfs=_range("limiter ceiling", l.limiter_ceiling_dbfs, LIMITER_CEILING_RANGE),
        release_ms=_range("limiter release", l.limiter_release_ms, LIMITER_RELEASE_RANGE),
    )


def _finite_number(value, name):
    if not isinstance(value, Real) or isinstance(value, bool) or not math.isfinite(float(value)):
        raise ValueError(f"{name} must be finite")
    return float(value)


def _range(name, value, limits):
    value = _finite_number(value, name)
    low, high = limits
    if value < low or value > high:
        raise ValueError(f"{name} must be between {low:g} and {high:g}")
    return value


def _target_changed(previous, current):
    if previous.user_enabled != current.user_enabled:
        return True
    if previous.plan_status != current.plan_status:
        return True
    if previous.requested_supported_capabilities != current.requested_supported_capabilities:
        return True
    if previous.requested_unsupported_capabilities != current.requested_unsupported_capabilities:
        return True
    if abs(previous.target_pitch_semitones - current.target_pitch_semitones) > EXECUTION_DEADBAND_ST:
        return True
    if abs(previous.target_formant_semitones - current.target_formant_semitones) > EXECUTION_DEADBAND_ST:
        return True
    return (
        previous.compressor_override_active != current.compressor_override_active
        or previous.limiter_override_active != current.limiter_override_active
        or previous.compressor_target != current.compressor_target
        or previous.limiter_target != current.limiter_target
        or previous.blocked_reason != current.blocked_reason
    )
