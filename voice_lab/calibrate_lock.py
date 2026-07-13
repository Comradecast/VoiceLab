from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace
from numbers import Real

from voice_lab.execution import (
    EXECUTION_DEADBAND_ST,
    MAX_EXECUTION_FORMANT_ST,
    MAX_EXECUTION_PITCH_ST,
)


PITCH_TRIM_RANGE_ST = (-4.0, 4.0)
FORMANT_TRIM_RANGE_ST = (-1.0, 1.0)
ADAPTIVE_OFF = "off"
ADAPTIVE_CONTINUOUS = "continuous"
ADAPTIVE_MODES = (ADAPTIVE_OFF, ADAPTIVE_CONTINUOUS)


@dataclass(frozen=True)
class CalibrationSourceProfile:
    calibration_id: int
    captured_at: float
    source_snapshot_age_seconds: float | None
    source_reliability: str
    ready: bool
    voiced_duration_seconds: float
    voiced_frame_count: int
    voiced_frame_ratio: float
    median_f0_hz: float
    lower_f0_hz: float
    upper_f0_hz: float
    pitch_span_semitones: float
    chest_energy_ratio: float
    low_mid_energy_ratio: float
    presence_energy_ratio: float
    brightness_energy_ratio: float
    sibilance_energy_ratio: float
    spectral_tilt_db: float | None
    f1_hz: float | None
    f2_hz: float | None
    f3_hz: float | None
    resonance_confidence: float
    warnings: tuple[str, ...] = ()

    def get(self, name, default=None):
        return getattr(self, name, default)

    def asdict(self):
        data = asdict(self)
        data["warnings"] = tuple(self.warnings)
        return data

    def source_snapshot(self):
        profile = {
            "ready": self.ready,
            "reliability": self.source_reliability,
            "voiced_frame_count": self.voiced_frame_count,
            "voiced_duration_seconds": self.voiced_duration_seconds,
            "voiced_frame_ratio": self.voiced_frame_ratio,
            "median_f0_hz": self.median_f0_hz,
            "lower_f0_hz": self.lower_f0_hz,
            "upper_f0_hz": self.upper_f0_hz,
            "pitch_span_hz": max(0.0, self.upper_f0_hz - self.lower_f0_hz),
            "pitch_span_semitones": self.pitch_span_semitones,
            "median_spectral_tilt_db": self.spectral_tilt_db,
            "chest_energy_ratio": self.chest_energy_ratio,
            "low_mid_energy_ratio": self.low_mid_energy_ratio,
            "presence_energy_ratio": self.presence_energy_ratio,
            "brightness_energy_ratio": self.brightness_energy_ratio,
            "sibilance_energy_ratio": self.sibilance_energy_ratio,
            "f1_hz": self.f1_hz,
            "f2_hz": self.f2_hz,
            "f3_hz": self.f3_hz,
            "resonance_confidence": self.resonance_confidence,
        }
        return {
            "current": {
                "captured_at": self.captured_at,
                "reliability": self.source_reliability,
            },
            "profile": profile,
            "status": {
                "active": True,
                "latest_snapshot_age_seconds": 0.0,
                "last_failure": "",
            },
        }


@dataclass(frozen=True)
class SuggestedTransformationSnapshot:
    valid: bool
    suggestion_id: int
    generated_at: float
    calibration_id: int
    target_id: str
    target_version: str
    character_strength: float
    planner_status: str
    planner_confidence: float
    plan: object | None = None
    differs_from_lock: bool = False
    warnings: tuple[str, ...] = ()

    def get(self, name, default=None):
        return getattr(self, name, default)

    def asdict(self):
        data = asdict(self)
        data["warnings"] = tuple(self.warnings)
        return data


@dataclass(frozen=True)
class LockedTransformationSnapshot:
    valid: bool
    lock_id: int
    locked_at: float
    source_calibration_id: int
    suggestion_id: int
    target_id: str
    target_version: str
    character_strength: float
    plan: object | None = None
    supported_capabilities: tuple[str, ...] = ()
    unsupported_capabilities: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    newer_suggestion_available: bool = False

    def get(self, name, default=None):
        return getattr(self, name, default)

    def asdict(self):
        data = asdict(self)
        data["supported_capabilities"] = tuple(self.supported_capabilities)
        data["unsupported_capabilities"] = tuple(self.unsupported_capabilities)
        data["warnings"] = tuple(self.warnings)
        return data


@dataclass(frozen=True)
class ManualTransformationTrim:
    requested_pitch_trim_st: float = 0.0
    applied_pitch_trim_st: float = 0.0
    requested_formant_trim_st: float = 0.0
    applied_formant_trim_st: float = 0.0
    generation: int = 0
    pitch_changed_from_zero: bool = False
    formant_changed_from_zero: bool = False
    pitch_trim_clamped: bool = False
    formant_trim_clamped: bool = False

    def get(self, name, default=None):
        return getattr(self, name, default)

    def asdict(self):
        return asdict(self)


@dataclass(frozen=True)
class StableTransformationControlSnapshot:
    lab: str
    adaptive_mode: str
    execution_authority: str
    calibration: CalibrationSourceProfile | None
    suggestion: SuggestedTransformationSnapshot | None
    locked: LockedTransformationSnapshot | None
    trim: ManualTransformationTrim
    execution_enabled: bool
    calibration_generation: int
    suggestion_generation: int
    lock_generation: int
    current_target_id: str
    current_target_name: str
    current_strength: float
    suggestion_differs_from_lock: bool
    newer_suggestion_available: bool
    manual_trim_active: bool
    live_source_readiness_matters: bool
    locked_plan_available_for_off: bool
    target_changed_after_lock: bool
    strength_changed_after_lock: bool
    calibration_changed_after_lock: bool
    locked_base_pitch_st: float = 0.0
    requested_pitch_trim_st: float = 0.0
    applied_pitch_trim_st: float = 0.0
    requested_final_pitch_st: float = 0.0
    final_pitch_target_st: float = 0.0
    final_pitch_clamped: bool = False
    locked_base_formant_st: float = 0.0
    requested_formant_trim_st: float = 0.0
    applied_formant_trim_st: float = 0.0
    requested_final_formant_st: float = 0.0
    final_formant_target_st: float = 0.0
    final_formant_clamped: bool = False
    warnings: tuple[str, ...] = ()

    def get(self, name, default=None):
        return getattr(self, name, default)

    def asdict(self):
        data = asdict(self)
        data["warnings"] = tuple(self.warnings)
        return data


def manual_trim(pitch_trim=0.0, formant_trim=0.0, generation=0):
    requested_pitch = _finite(pitch_trim, "pitch trim")
    requested_formant = _finite(formant_trim, "formant trim")
    applied_pitch, pitch_clamped = _clamp(requested_pitch, PITCH_TRIM_RANGE_ST)
    applied_formant, formant_clamped = _clamp(requested_formant, FORMANT_TRIM_RANGE_ST)
    return ManualTransformationTrim(
        requested_pitch_trim_st=requested_pitch,
        applied_pitch_trim_st=applied_pitch,
        requested_formant_trim_st=requested_formant,
        applied_formant_trim_st=applied_formant,
        generation=int(generation),
        pitch_changed_from_zero=abs(applied_pitch) > EXECUTION_DEADBAND_ST,
        formant_changed_from_zero=abs(applied_formant) > EXECUTION_DEADBAND_ST,
        pitch_trim_clamped=pitch_clamped,
        formant_trim_clamped=formant_clamped,
    )


def apply_manual_trim(plan, trim):
    if plan is None:
        return None, _trim_projection(None, trim)
    base_pitch = float(plan.pitch.applied_pitch_shift_st)
    requested_pitch = base_pitch + trim.applied_pitch_trim_st
    final_pitch, final_pitch_clamped = _clamp(requested_pitch, (-MAX_EXECUTION_PITCH_ST, MAX_EXECUTION_PITCH_ST))
    base_formant = float(plan.formant.applied_formant_shift_st)
    requested_formant = base_formant + trim.applied_formant_trim_st
    final_formant, final_formant_clamped = _clamp(
        requested_formant,
        (-MAX_EXECUTION_FORMANT_ST, MAX_EXECUTION_FORMANT_ST),
    )
    pitch_capabilities = set(plan.required_capabilities)
    if abs(final_pitch) > EXECUTION_DEADBAND_ST:
        pitch_capabilities.add("adaptive_pitch_center")
    if abs(final_formant) > EXECUTION_DEADBAND_ST:
        pitch_capabilities.add("formant_shift")
    capabilities = tuple(
        name
        for name in (
            "adaptive_pitch_center",
            "pitch_range_mapping",
            "formant_shift",
            "parametric_eq",
            "spectral_tilt_shaping",
            "breathiness",
            "harmonic_enhancement",
            "de_esser",
            "compressor",
            "limiter",
        )
        if name in pitch_capabilities
    )
    pitch = replace(
        plan.pitch,
        requested_pitch_shift_st=requested_pitch,
        applied_pitch_shift_st=final_pitch,
        pitch_shift_clamped=bool(plan.pitch.pitch_shift_clamped or final_pitch_clamped),
        basis=f"{plan.pitch.basis} Manual trim overlay applied after locked/adaptive base.",
    )
    formant = replace(
        plan.formant,
        requested_formant_shift_st=requested_formant,
        applied_formant_shift_st=final_formant,
        formant_clamped=bool(plan.formant.formant_clamped or final_formant_clamped),
        basis=f"{plan.formant.basis} Manual trim overlay applied after locked/adaptive base.",
    )
    warnings = tuple(dict.fromkeys(tuple(plan.warnings) + _trim_warnings(trim, final_pitch_clamped, final_formant_clamped)))
    adjusted = replace(
        plan,
        pitch=pitch,
        formant=formant,
        required_capabilities=capabilities,
        warnings=warnings,
    )
    return adjusted, _trim_projection(plan, trim)


def _trim_projection(plan, trim):
    base_pitch = float(getattr(getattr(plan, "pitch", None), "applied_pitch_shift_st", 0.0) or 0.0)
    requested_pitch = base_pitch + trim.applied_pitch_trim_st
    final_pitch, final_pitch_clamped = _clamp(requested_pitch, (-MAX_EXECUTION_PITCH_ST, MAX_EXECUTION_PITCH_ST))
    base_formant = float(getattr(getattr(plan, "formant", None), "applied_formant_shift_st", 0.0) or 0.0)
    requested_formant = base_formant + trim.applied_formant_trim_st
    final_formant, final_formant_clamped = _clamp(
        requested_formant,
        (-MAX_EXECUTION_FORMANT_ST, MAX_EXECUTION_FORMANT_ST),
    )
    return {
        "locked_base_pitch_st": base_pitch,
        "requested_pitch_trim_st": trim.requested_pitch_trim_st,
        "applied_pitch_trim_st": trim.applied_pitch_trim_st,
        "requested_final_pitch_st": requested_pitch,
        "final_pitch_target_st": final_pitch,
        "final_pitch_clamped": final_pitch_clamped,
        "locked_base_formant_st": base_formant,
        "requested_formant_trim_st": trim.requested_formant_trim_st,
        "applied_formant_trim_st": trim.applied_formant_trim_st,
        "requested_final_formant_st": requested_formant,
        "final_formant_target_st": final_formant,
        "final_formant_clamped": final_formant_clamped,
    }


def trim_projection(plan, trim):
    return _trim_projection(plan, trim)


def _trim_warnings(trim, pitch_clamped, formant_clamped):
    warnings = []
    if trim.pitch_changed_from_zero:
        warnings.append("manual pitch trim active")
    if trim.formant_changed_from_zero:
        warnings.append("manual formant trim active")
    if trim.pitch_trim_clamped or pitch_clamped:
        warnings.append("manual pitch trim clamped")
    if trim.formant_trim_clamped or formant_clamped:
        warnings.append("manual formant trim clamped")
    return tuple(warnings)


def _finite(value, name):
    if not isinstance(value, Real) or isinstance(value, bool) or not math.isfinite(float(value)):
        raise ValueError(f"{name} must be finite")
    return float(value)


def _clamp(value, limits):
    low, high = limits
    clamped = max(low, min(high, float(value)))
    return clamped, clamped != float(value)
