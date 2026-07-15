from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass
from numbers import Real

from voice_lab.analysis import F0_MAX_HZ, F0_MIN_HZ, STALE_SNAPSHOT_SECONDS
from voice_lab.config.input_processing import (
    COMPRESSOR_ATTACK_RANGE,
    COMPRESSOR_MAKEUP_RANGE,
    COMPRESSOR_RATIO_RANGE,
    COMPRESSOR_RELEASE_RANGE,
    COMPRESSOR_THRESHOLD_RANGE,
    LIMITER_CEILING_RANGE,
    LIMITER_RELEASE_RANGE,
)


PLAN_VERSION = "m9.1"
TARGET_SCHEMA_VERSION = "target_voice_profile.v1"
MAX_NATURAL_FORMANT_SHIFT_ST = 2.0
PITCH_STRATEGY_ABSOLUTE_F0 = "absolute_f0"
PITCH_STRATEGY_RELATIVE_SHIFT = "relative_shift"
FORMANT_STRATEGY_NEUTRAL = "neutral"
FORMANT_STRATEGY_FIXED_SHIFT = "restrained_fixed_shift"
FORMANT_STRATEGY_NATURAL_COMPENSATION = "natural_compensation"
FORMANT_STRATEGY_SIZE_COUPLED = "size_coupled_stylization"
NATURAL_FORMANT_COMPENSATION_RATIO = 0.43
SPECTRAL_EPSILON = 1e-6
NEAR_ZERO_PITCH_SPAN_ST = 0.25
CAPABILITY_ORDER = (
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


@dataclass(frozen=True)
class DynamicsTarget:
    compressor_enabled: bool = False
    compressor_threshold_dbfs: float = -18.0
    compressor_ratio: float = 1.0
    compressor_attack_ms: float = 10.0
    compressor_release_ms: float = 150.0
    compressor_makeup_gain_db: float = 0.0
    limiter_enabled: bool = False
    limiter_ceiling_dbfs: float = -1.0
    limiter_release_ms: float = 80.0

    def asdict(self):
        return asdict(self)


@dataclass(frozen=True)
class PitchStrategy:
    strategy_id: str = PITCH_STRATEGY_ABSOLUTE_F0
    relative_shift_st: float = 0.0

    def asdict(self):
        return asdict(self)


@dataclass(frozen=True)
class FormantStrategy:
    strategy_id: str = FORMANT_STRATEGY_FIXED_SHIFT
    fixed_shift_st: float = 0.0
    compensation_ratio: float = NATURAL_FORMANT_COMPENSATION_RATIO
    natural: bool = False
    stylized: bool = False

    def asdict(self):
        return asdict(self)


@dataclass(frozen=True)
class TargetVoiceProfile:
    target_id: str
    display_name: str
    description: str
    schema_version: str = TARGET_SCHEMA_VERSION
    target_median_f0_hz: float = 140.0
    target_pitch_span_st: float = 6.0
    pitch_strategy: PitchStrategy = PitchStrategy()
    max_pitch_shift_st: float = 8.0
    min_pitch_range_scale: float = 0.5
    max_pitch_range_scale: float = 2.0
    nominal_formant_shift_st: float = 0.0
    formant_strategy: FormantStrategy = FormantStrategy()
    max_abs_formant_shift_st: float = MAX_NATURAL_FORMANT_SHIFT_ST
    chest_energy_ratio: float = 0.20
    low_mid_energy_ratio: float = 0.35
    presence_energy_ratio: float = 0.20
    brightness_energy_ratio: float = 0.10
    sibilance_energy_ratio: float = 0.08
    spectral_tilt_db: float = -8.0
    max_band_adjustment_db: float = 6.0
    max_spectral_tilt_adjustment_db: float = 6.0
    breathiness: float = 0.0
    harmonic_weight: float = 0.0
    dynamics: DynamicsTarget = DynamicsTarget()
    expect_de_essing: bool = False
    requires_pitch_range: bool = True
    requires_eq: bool = True
    requires_breathiness: bool = False
    requires_harmonic_enhancement: bool = False
    warnings: tuple[str, ...] = ()

    def asdict(self):
        data = asdict(self)
        data["warnings"] = tuple(self.warnings)
        return data


@dataclass(frozen=True)
class PitchPlan:
    source_median_f0_hz: float | None
    target_median_f0_hz: float
    requested_pitch_shift_st: float
    applied_pitch_shift_st: float
    pitch_shift_clamped: bool
    source_pitch_span_st: float | None
    target_pitch_span_st: float
    requested_pitch_range_scale: float
    applied_pitch_range_scale: float
    pitch_range_clamped: bool
    confidence: float
    basis: str
    strategy: str = PITCH_STRATEGY_ABSOLUTE_F0
    unavailable_reason: str = ""

    def asdict(self):
        return asdict(self)


@dataclass(frozen=True)
class FormantPlan:
    requested_formant_shift_st: float
    applied_formant_shift_st: float
    formant_clamped: bool
    confidence: float
    basis: str
    strategy: str = FORMANT_STRATEGY_FIXED_SHIFT
    naturalness_guard_active: bool = False
    stylized_formant_combination_active: bool = False
    capability_source: str = "target_profile"
    warning: str = ""

    def asdict(self):
        return asdict(self)


@dataclass(frozen=True)
class BandAdjustment:
    requested_db: float | None
    applied_db: float | None
    clamped: bool
    confidence: float
    unavailable_reason: str = ""

    def asdict(self):
        return asdict(self)


@dataclass(frozen=True)
class SpectralPlan:
    chest_db: BandAdjustment
    low_mid_db: BandAdjustment
    presence_db: BandAdjustment
    brightness_db: BandAdjustment
    sibilance_db: BandAdjustment
    spectral_tilt_db: BandAdjustment
    de_essing_amount: float
    de_essing_basis: str

    def asdict(self):
        return {
            "chest_db": self.chest_db.asdict(),
            "low_mid_db": self.low_mid_db.asdict(),
            "presence_db": self.presence_db.asdict(),
            "brightness_db": self.brightness_db.asdict(),
            "sibilance_db": self.sibilance_db.asdict(),
            "spectral_tilt_db": self.spectral_tilt_db.asdict(),
            "de_essing_amount": self.de_essing_amount,
            "de_essing_basis": self.de_essing_basis,
        }


@dataclass(frozen=True)
class TexturePlan:
    breathiness: float
    harmonic_weight: float
    breathiness_required: bool
    harmonic_enhancement_required: bool
    confidence: float
    basis: str

    def asdict(self):
        return asdict(self)


@dataclass(frozen=True)
class DynamicsPlan:
    compressor: DynamicsTarget
    limiter: DynamicsTarget
    compressor_differs_from_neutral: bool
    limiter_differs_from_neutral: bool
    confidence: float
    basis: str

    def asdict(self):
        return {
            "compressor": self.compressor.asdict(),
            "limiter": self.limiter.asdict(),
            "compressor_differs_from_neutral": self.compressor_differs_from_neutral,
            "limiter_differs_from_neutral": self.limiter_differs_from_neutral,
            "confidence": self.confidence,
            "basis": self.basis,
        }


@dataclass(frozen=True)
class TransformationPlan:
    plan_version: str
    source_captured_at: float | None
    target_id: str
    target_version: str
    character_strength: float
    created_at: float
    ready: bool
    status: str
    source_reliability: str
    aggregate_confidence: float
    source_profile_age_seconds: float | None
    stale: bool
    degraded: bool
    unavailable_reason: str
    pitch: PitchPlan
    formant: FormantPlan
    spectral: SpectralPlan
    texture: TexturePlan
    dynamics: DynamicsPlan
    required_capabilities: tuple[str, ...]
    warnings: tuple[str, ...]

    def asdict(self):
        return {
            "plan_version": self.plan_version,
            "source_captured_at": self.source_captured_at,
            "target_id": self.target_id,
            "target_version": self.target_version,
            "character_strength": self.character_strength,
            "created_at": self.created_at,
            "ready": self.ready,
            "status": self.status,
            "source_reliability": self.source_reliability,
            "aggregate_confidence": self.aggregate_confidence,
            "source_profile_age_seconds": self.source_profile_age_seconds,
            "stale": self.stale,
            "degraded": self.degraded,
            "unavailable_reason": self.unavailable_reason,
            "pitch": self.pitch.asdict(),
            "formant": self.formant.asdict(),
            "spectral": self.spectral.asdict(),
            "texture": self.texture.asdict(),
            "dynamics": self.dynamics.asdict(),
            "required_capabilities": tuple(self.required_capabilities),
            "warnings": tuple(self.warnings),
        }


def target_voice_profile(**kwargs):
    dynamics = kwargs.get("dynamics")
    if isinstance(dynamics, dict):
        kwargs["dynamics"] = DynamicsTarget(**dynamics)
    pitch_strategy = kwargs.get("pitch_strategy")
    if isinstance(pitch_strategy, dict):
        kwargs["pitch_strategy"] = PitchStrategy(**pitch_strategy)
    formant_strategy = kwargs.get("formant_strategy")
    if isinstance(formant_strategy, dict):
        kwargs["formant_strategy"] = FormantStrategy(**formant_strategy)
    profile = TargetVoiceProfile(**kwargs)
    _validate_profile(profile)
    return profile


class TransformationPlanner:
    def __init__(self, clock=time.monotonic):
        self.clock = clock

    def plan(self, source_snapshot, target_profile, strength):
        try:
            _validate_profile(target_profile)
            strength = _validate_strength_01(strength)
            created_at = float(self.clock())
            profile = dict((source_snapshot or {}).get("profile") or {})
            status = dict((source_snapshot or {}).get("status") or {})
            current = dict((source_snapshot or {}).get("current") or {})
            source_age = status.get("latest_snapshot_age_seconds")
            stale = bool(current.get("reliability") == "stale") or (
                source_age is not None and source_age > STALE_SNAPSHOT_SECONDS
            )
            source_reliability = _source_reliability(profile, current, status)
            source_confidence = _source_confidence(profile, stale, source_reliability)
            pitch = _pitch_plan(profile, target_profile, strength, source_confidence)
            formant = _formant_plan(target_profile, strength, pitch)
            spectral = _spectral_plan(profile, target_profile, strength, source_confidence)
            texture = _texture_plan(target_profile, strength)
            dynamics = _dynamics_plan(target_profile, strength)
            warnings = _warnings(profile, stale, source_reliability, pitch, formant, spectral, target_profile)
            capabilities = _capabilities(pitch, formant, spectral, texture, dynamics, target_profile, strength)
            status_name, ready, degraded, unavailable = _plan_state(
                profile, status, stale, source_reliability, pitch, formant, spectral
            )
            aggregate = 0.0 if not ready and status_name not in {"degraded", "stale_source"} else min(
                source_confidence,
                pitch.confidence,
                _spectral_confidence(spectral),
            )
            if status_name == "degraded":
                aggregate = min(aggregate, 0.65)
            if status_name == "stale_source":
                aggregate = min(aggregate, 0.35)
            return TransformationPlan(
                plan_version=PLAN_VERSION,
                source_captured_at=current.get("captured_at"),
                target_id=target_profile.target_id,
                target_version=target_profile.schema_version,
                character_strength=strength,
                created_at=created_at,
                ready=ready,
                status=status_name,
                source_reliability=source_reliability,
                aggregate_confidence=_clamp01(aggregate),
                source_profile_age_seconds=source_age,
                stale=stale,
                degraded=degraded,
                unavailable_reason=unavailable,
                pitch=pitch,
                formant=formant,
                spectral=spectral,
                texture=texture,
                dynamics=dynamics,
                required_capabilities=capabilities,
                warnings=warnings,
            )
        except Exception as exc:
            return _failure_plan(target_profile, strength if isinstance(strength, Real) else 0.0, str(exc), self.clock())


def _pitch_plan(profile, target, strength, source_confidence):
    source_f0 = _optional_positive(profile.get("median_f0_hz"))
    source_span = _optional_positive(profile.get("pitch_span_semitones"))
    if source_f0 is None:
        return PitchPlan(None, target.target_median_f0_hz, 0.0, 0.0, False, source_span,
                         target.target_pitch_span_st, 1.0, 1.0, False, 0.0,
                         "Missing reliable source median F0.", target.pitch_strategy.strategy_id, "missing_source_median_f0")
    if _is_neutral_target(target):
        return PitchPlan(
            source_f0,
            target.target_median_f0_hz,
            0.0,
            0.0,
            False,
            source_span,
            target.target_pitch_span_st,
            1.0,
            1.0,
            False,
            source_confidence,
            "Neutral target; no pitch movement or pitch-range mapping.",
            target.pitch_strategy.strategy_id,
        )
    if target.pitch_strategy.strategy_id == PITCH_STRATEGY_RELATIVE_SHIFT:
        requested = target.pitch_strategy.relative_shift_st
        pitch_basis = "Pitch center uses explicit relative semitone target scaled by strength."
    else:
        requested = 12.0 * math.log2(target.target_median_f0_hz / source_f0)
        pitch_basis = "Pitch center uses 12*log2(target/source)."
    strength_adjusted = requested * strength
    applied, clamped = _clamp_signed(strength_adjusted, target.max_pitch_shift_st)
    if source_span is None or source_span <= NEAR_ZERO_PITCH_SPAN_ST:
        requested_scale = 1.0
        applied_scale = 1.0
        range_clamped = False
        basis = f"{pitch_basis} Range neutral because source span is unavailable."
        confidence = min(source_confidence, 0.65)
    else:
        requested_scale = target.target_pitch_span_st / source_span
        interpolated = 1.0 + ((requested_scale - 1.0) * strength)
        applied_scale, range_clamped = _clamp_range(
            interpolated, target.min_pitch_range_scale, target.max_pitch_range_scale
        )
        basis = f"{pitch_basis} Range maps target/source span with strength interpolation."
        confidence = source_confidence
    return PitchPlan(source_f0, target.target_median_f0_hz, requested, applied, clamped,
                     source_span, target.target_pitch_span_st, requested_scale, applied_scale,
                     range_clamped, _clamp01(confidence), basis, target.pitch_strategy.strategy_id)


def _formant_plan(target, strength, pitch):
    strategy = target.formant_strategy
    warning = ""
    guard_active = False
    stylized = False
    if strategy.strategy_id == FORMANT_STRATEGY_NEUTRAL:
        requested = 0.0
        basis = "Formant strategy is neutral; no planner formant movement requested."
    elif strategy.strategy_id == FORMANT_STRATEGY_NATURAL_COMPENSATION:
        if strategy.fixed_shift_st < 0.0:
            requested = strategy.fixed_shift_st * strength
            basis = "Natural compensation target contains inconsistent negative formant intent."
        else:
            requested = max(0.0, -pitch.applied_pitch_shift_st) * strategy.compensation_ratio
            basis = "Natural compensation derives moderate positive formant movement from applied downward pitch."
    else:
        requested = strategy.fixed_shift_st * strength
        if strategy.strategy_id == FORMANT_STRATEGY_SIZE_COUPLED:
            stylized = requested < 0.0 and pitch.applied_pitch_shift_st < 0.0
            basis = "Size-coupled stylization intentionally lowers pitch and formants for a large-vocal-tract effect."
        else:
            basis = "Restrained fixed formant shift from explicit target strategy."
    applied_request = requested
    if strategy.strategy_id == FORMANT_STRATEGY_NATURAL_COMPENSATION and requested < 0.0:
        applied_request = 0.0
        guard_active = True
        warning = "naturalness guard blocked negative natural-compensation formant"
    applied, clamped = _clamp_signed(applied_request, target.max_abs_formant_shift_st)
    if clamped:
        warning = "formant movement clamped" if not warning else f"{warning}; formant movement clamped"
    if strategy.strategy_id == FORMANT_STRATEGY_SIZE_COUPLED and stylized:
        warning = (
            "stylized negative pitch plus negative formant may exaggerate vowels, W/R transitions, or nasal resonance"
            if not warning
            else warning
        )
    if abs(strategy.fixed_shift_st) > MAX_NATURAL_FORMANT_SHIFT_ST:
        warning = "target asks for extreme formant movement"
    return FormantPlan(
        requested,
        applied,
        clamped,
        0.55 if abs(applied) > 0.0 else 1.0,
        basis + " Approximate F1/F2/F3 are weak context and do not drive this value.",
        strategy.strategy_id,
        guard_active,
        stylized,
        "target_profile_strategy",
        warning,
    )


def _spectral_plan(profile, target, strength, source_confidence):
    if _is_neutral_target(target):
        neutral = BandAdjustment(0.0, 0.0, False, 1.0)
        return SpectralPlan(
            chest_db=neutral,
            low_mid_db=neutral,
            presence_db=neutral,
            brightness_db=neutral,
            sibilance_db=neutral,
            spectral_tilt_db=neutral,
            de_essing_amount=0.0,
            de_essing_basis="neutral target",
        )
    bands = (
        ("chest_energy_ratio", target.chest_energy_ratio, target.max_band_adjustment_db),
        ("low_mid_energy_ratio", target.low_mid_energy_ratio, target.max_band_adjustment_db),
        ("presence_energy_ratio", target.presence_energy_ratio, target.max_band_adjustment_db),
        ("brightness_energy_ratio", target.brightness_energy_ratio, target.max_band_adjustment_db),
        ("sibilance_energy_ratio", target.sibilance_energy_ratio, target.max_band_adjustment_db),
    )
    adjustments = {
        name: _ratio_adjustment(profile.get(name), target_value, strength, limit, source_confidence)
        for name, target_value, limit in bands
    }
    tilt = _tilt_adjustment(
        profile.get("median_spectral_tilt_db"),
        target.spectral_tilt_db,
        strength,
        target.max_spectral_tilt_adjustment_db,
        source_confidence,
    )
    de_ess = _de_essing_amount(profile, target, adjustments["brightness_energy_ratio"], strength)
    return SpectralPlan(
        chest_db=adjustments["chest_energy_ratio"],
        low_mid_db=adjustments["low_mid_energy_ratio"],
        presence_db=adjustments["presence_energy_ratio"],
        brightness_db=adjustments["brightness_energy_ratio"],
        sibilance_db=adjustments["sibilance_energy_ratio"],
        spectral_tilt_db=tilt,
        de_essing_amount=de_ess,
        de_essing_basis="max(source_sibilance_excess, brightness_increase, target_de_essing_expectation)",
    )


def _texture_plan(target, strength):
    if _is_neutral_target(target):
        return TexturePlan(
            breathiness=0.0,
            harmonic_weight=0.0,
            breathiness_required=False,
            harmonic_enhancement_required=False,
            confidence=1.0,
            basis="Neutral target; no texture movement.",
        )
    strength_active = strength > SPECTRAL_EPSILON
    breathiness = _clamp01(target.breathiness * strength)
    harmonic = _clamp01(target.harmonic_weight * strength)
    return TexturePlan(
        breathiness=breathiness,
        harmonic_weight=harmonic,
        breathiness_required=breathiness > SPECTRAL_EPSILON or (strength_active and target.requires_breathiness),
        harmonic_enhancement_required=(
            harmonic > SPECTRAL_EPSILON or (strength_active and target.requires_harmonic_enhancement)
        ),
        confidence=0.5 if breathiness or harmonic else 1.0,
        basis="Target intent scaled by strength; no source identity inference.",
    )


def _dynamics_plan(target, strength):
    if _is_neutral_target(target):
        return DynamicsPlan(
            compressor=DynamicsTarget(),
            limiter=DynamicsTarget(),
            compressor_differs_from_neutral=False,
            limiter_differs_from_neutral=False,
            confidence=1.0,
            basis="Neutral target; no dynamics movement.",
        )
    c = target.dynamics
    compressor = DynamicsTarget(
        compressor_enabled=c.compressor_enabled and strength > 0.0,
        compressor_threshold_dbfs=c.compressor_threshold_dbfs,
        compressor_ratio=1.0 + ((c.compressor_ratio - 1.0) * strength),
        compressor_attack_ms=c.compressor_attack_ms,
        compressor_release_ms=c.compressor_release_ms,
        compressor_makeup_gain_db=c.compressor_makeup_gain_db * strength,
        limiter_enabled=False,
        limiter_ceiling_dbfs=c.limiter_ceiling_dbfs,
        limiter_release_ms=c.limiter_release_ms,
    )
    limiter = DynamicsTarget(
        compressor_enabled=False,
        limiter_enabled=c.limiter_enabled and strength > 0.0,
        limiter_ceiling_dbfs=c.limiter_ceiling_dbfs,
        limiter_release_ms=c.limiter_release_ms,
    )
    return DynamicsPlan(
        compressor=compressor,
        limiter=limiter,
        compressor_differs_from_neutral=compressor.compressor_enabled and (
            compressor.compressor_ratio != 1.0 or compressor.compressor_makeup_gain_db != 0.0
        ),
        limiter_differs_from_neutral=limiter.limiter_enabled,
        confidence=0.7 if compressor.compressor_enabled or limiter.limiter_enabled else 1.0,
        basis="Target dynamics recommendation only; live M8.0 settings are not mutated.",
    )


def _ratio_adjustment(source_value, target_value, strength, limit, source_confidence):
    source = _optional_positive(source_value)
    if source is None or source <= SPECTRAL_EPSILON:
        return BandAdjustment(None, None, False, 0.0, "missing_or_zero_source_ratio")
    if target_value <= SPECTRAL_EPSILON:
        requested = -limit
    else:
        requested = 10.0 * math.log10(target_value / source)
    applied, clamped = _clamp_signed(requested * strength, limit)
    return BandAdjustment(requested, applied, clamped, _clamp01(source_confidence))


def _tilt_adjustment(source_value, target_value, strength, limit, source_confidence):
    if not _finite(source_value):
        return BandAdjustment(None, None, False, 0.0, "missing_source_tilt_index")
    requested = float(target_value) - float(source_value)
    applied, clamped = _clamp_signed(requested * strength, limit)
    return BandAdjustment(requested, applied, clamped, _clamp01(source_confidence))


def _de_essing_amount(profile, target, brightness_adjustment, strength):
    source_sibilance = _optional_positive(profile.get("sibilance_energy_ratio")) or 0.0
    source_component = max(0.0, (source_sibilance - target.sibilance_energy_ratio) / 0.20) * strength
    brightness_component = 0.0
    if brightness_adjustment.applied_db is not None:
        brightness_component = max(0.0, brightness_adjustment.applied_db / max(target.max_band_adjustment_db, 1.0))
    target_component = 0.35 * strength if target.expect_de_essing else 0.0
    return _clamp01(max(source_component, brightness_component, target_component))


def _materially_nonzero(value):
    return value is not None and abs(float(value)) > SPECTRAL_EPSILON


def _is_neutral_target(target):
    return (
        target.pitch_strategy.strategy_id == PITCH_STRATEGY_RELATIVE_SHIFT
        and abs(target.pitch_strategy.relative_shift_st) <= SPECTRAL_EPSILON
        and target.formant_strategy.strategy_id == FORMANT_STRATEGY_NEUTRAL
        and not target.requires_pitch_range
        and not target.requires_eq
        and not target.requires_breathiness
        and not target.requires_harmonic_enhancement
        and not target.expect_de_essing
    )


def _capabilities(pitch, formant, spectral, texture, dynamics, target, strength):
    strength_active = strength > SPECTRAL_EPSILON
    needed = []
    if _materially_nonzero(pitch.applied_pitch_shift_st):
        needed.append("adaptive_pitch_center")
    if _materially_nonzero(pitch.applied_pitch_range_scale - 1.0) or (
        strength_active and target.requires_pitch_range
    ):
        needed.append("pitch_range_mapping")
    if _materially_nonzero(formant.applied_formant_shift_st):
        needed.append("formant_shift")
    if any(_materially_nonzero(getattr(spectral, name).applied_db) for name in (
        "chest_db", "low_mid_db", "presence_db", "brightness_db", "sibilance_db"
    )) or (strength_active and target.requires_eq):
        needed.append("parametric_eq")
    if _materially_nonzero(spectral.spectral_tilt_db.applied_db):
        needed.append("spectral_tilt_shaping")
    if texture.breathiness_required:
        needed.append("breathiness")
    if texture.harmonic_enhancement_required:
        needed.append("harmonic_enhancement")
    if spectral.de_essing_amount > SPECTRAL_EPSILON:
        needed.append("de_esser")
    if dynamics.compressor_differs_from_neutral:
        needed.append("compressor")
    if dynamics.limiter_differs_from_neutral:
        needed.append("limiter")
    return tuple(name for name in CAPABILITY_ORDER if name in set(needed))


def _warnings(profile, stale, source_reliability, pitch, formant, spectral, target):
    warnings = ["plan is diagnostic only; audio is not modified"]
    if stale:
        warnings.append("source profile stale")
    if source_reliability not in {"ready", "collecting"}:
        warnings.append(f"source reliability: {source_reliability}")
    if pitch.pitch_shift_clamped:
        warnings.append("requested pitch shift clamped")
    if pitch.pitch_range_clamped:
        warnings.append("requested pitch-range scale clamped")
    if formant.formant_clamped:
        warnings.append("formant movement clamped")
    if formant.naturalness_guard_active:
        warnings.append("naturalness guard blocked inconsistent negative formant")
    if formant.stylized_formant_combination_active:
        warnings.append("stylized negative pitch plus negative formant may exaggerate vowels, W/R transitions, or nasal resonance")
    for label, adjustment in (
        ("chest", spectral.chest_db),
        ("low-mid", spectral.low_mid_db),
        ("presence", spectral.presence_db),
        ("brightness", spectral.brightness_db),
        ("sibilance", spectral.sibilance_db),
        ("tilt", spectral.spectral_tilt_db),
    ):
        if adjustment.unavailable_reason:
            warnings.append(f"{label} source descriptor unavailable")
        if adjustment.clamped:
            warnings.append(f"{label} adjustment clamped")
    if profile.get("f1_hz") is not None or profile.get("f2_hz") is not None or profile.get("f3_hz") is not None:
        warnings.append("resonance estimates are weak descriptors")
    warnings.extend(target.warnings)
    return tuple(dict.fromkeys(warnings))


def _plan_state(profile, status, stale, source_reliability, pitch, formant, spectral):
    if status.get("last_failure"):
        return "planner_failure", False, False, str(status.get("last_failure"))
    if stale:
        return "stale_source", False, True, "source profile is stale"
    if not profile or not status.get("active", False):
        return "waiting_for_source", False, False, "source analysis is unavailable"
    if not profile.get("ready"):
        return "collecting_source", False, False, "source profile is still collecting"
    if pitch.unavailable_reason:
        return "degraded", False, True, pitch.unavailable_reason
    if formant.naturalness_guard_active:
        return "degraded", False, True, "naturalness guard blocked inconsistent formant target"
    if _spectral_confidence(spectral) <= 0.0:
        return "degraded", False, True, "source spectral descriptors unavailable"
    if any(getattr(spectral, name).unavailable_reason for name in (
        "chest_db", "low_mid_db", "presence_db", "brightness_db", "sibilance_db", "spectral_tilt_db"
    )):
        return "degraded", False, True, "one or more source spectral descriptors unavailable"
    return "ready", True, False, ""


def _source_reliability(profile, current, status):
    if status.get("last_failure"):
        return "analyzer failure"
    if current.get("reliability") == "stale":
        return "stale"
    if not status.get("active", False):
        return "analyzer unavailable"
    return str(profile.get("reliability") or current.get("reliability") or "collecting")


def _source_confidence(profile, stale, reliability):
    if stale or reliability == "stale":
        return 0.35
    if reliability == "ready" and profile.get("ready"):
        voiced_ratio = float(profile.get("voiced_frame_ratio") or 0.0)
        voiced_duration = float(profile.get("voiced_duration_seconds") or 0.0)
        return _clamp01(min(1.0, 0.55 + voiced_ratio * 0.25 + min(voiced_duration / 8.0, 1.0) * 0.20))
    if reliability == "collecting":
        return 0.35
    return 0.0


def _spectral_confidence(spectral):
    values = [
        spectral.chest_db.confidence,
        spectral.low_mid_db.confidence,
        spectral.presence_db.confidence,
        spectral.brightness_db.confidence,
        spectral.sibilance_db.confidence,
        spectral.spectral_tilt_db.confidence,
    ]
    return min(values)


def _failure_plan(target, strength, reason, created_at):
    target_id = getattr(target, "target_id", "invalid")
    target_version = getattr(target, "schema_version", TARGET_SCHEMA_VERSION)
    neutral_pitch = PitchPlan(None, 0.0, 0.0, 0.0, False, None, 0.0, 1.0, 1.0, False, 0.0, "", PITCH_STRATEGY_RELATIVE_SHIFT, reason)
    neutral_formant = FormantPlan(0.0, 0.0, False, 0.0, "planner failure", FORMANT_STRATEGY_NEUTRAL)
    unavailable = BandAdjustment(None, None, False, 0.0, "planner_failure")
    spectral = SpectralPlan(unavailable, unavailable, unavailable, unavailable, unavailable, unavailable, 0.0, "")
    texture = TexturePlan(0.0, 0.0, False, False, 0.0, "")
    dynamics = DynamicsPlan(DynamicsTarget(), DynamicsTarget(), False, False, 0.0, "")
    return TransformationPlan(PLAN_VERSION, None, target_id, target_version, _safe_strength(strength), created_at,
                              False, "invalid_target", "", 0.0, None, False, False, reason,
                              neutral_pitch, neutral_formant, spectral, texture, dynamics, (), (reason,))


def _validate_profile(profile):
    if not isinstance(profile.target_id, str) or not profile.target_id.strip():
        raise ValueError("target_id must be a nonempty string")
    if not isinstance(profile.display_name, str) or not profile.display_name.strip():
        raise ValueError("display_name must be a nonempty string")
    if not isinstance(profile.pitch_strategy, PitchStrategy):
        raise ValueError("pitch_strategy must be a PitchStrategy")
    if not isinstance(profile.formant_strategy, FormantStrategy):
        raise ValueError("formant_strategy must be a FormantStrategy")
    _validate_pitch_strategy(profile.pitch_strategy)
    _validate_formant_strategy(profile.formant_strategy)
    for field in (
        "target_median_f0_hz", "target_pitch_span_st", "max_pitch_shift_st",
        "min_pitch_range_scale", "max_pitch_range_scale", "nominal_formant_shift_st",
        "max_abs_formant_shift_st", "chest_energy_ratio", "low_mid_energy_ratio",
        "presence_energy_ratio", "brightness_energy_ratio", "sibilance_energy_ratio",
        "spectral_tilt_db", "max_band_adjustment_db", "max_spectral_tilt_adjustment_db",
        "breathiness", "harmonic_weight",
    ):
        if not _finite(getattr(profile, field)):
            raise ValueError(f"{field} must be finite")
    if not (F0_MIN_HZ <= profile.target_median_f0_hz <= F0_MAX_HZ):
        raise ValueError("target_median_f0_hz outside supported source-analysis range")
    if profile.target_pitch_span_st < 0.0:
        raise ValueError("target_pitch_span_st must be nonnegative")
    if profile.max_pitch_shift_st < 0.0 or profile.max_pitch_shift_st > 24.0:
        raise ValueError("max_pitch_shift_st must be between 0 and 24")
    if profile.min_pitch_range_scale <= 0.0 or profile.max_pitch_range_scale < profile.min_pitch_range_scale:
        raise ValueError("invalid pitch-range scale limits")
    if (
        abs(profile.nominal_formant_shift_st) > MAX_NATURAL_FORMANT_SHIFT_ST
        or profile.max_abs_formant_shift_st < 0.0
        or profile.max_abs_formant_shift_st > MAX_NATURAL_FORMANT_SHIFT_ST
    ):
        raise ValueError("formant planning is restrained to +/-2 semitones")
    for field in ("chest_energy_ratio", "low_mid_energy_ratio", "presence_energy_ratio", "brightness_energy_ratio", "sibilance_energy_ratio"):
        if getattr(profile, field) < 0.0:
            raise ValueError(f"{field} must be nonnegative")
    if not (0.0 <= profile.breathiness <= 1.0 and 0.0 <= profile.harmonic_weight <= 1.0):
        raise ValueError("texture targets must be normalized 0..1")
    _validate_dynamics(profile.dynamics)


def _validate_pitch_strategy(strategy):
    if strategy.strategy_id not in {PITCH_STRATEGY_ABSOLUTE_F0, PITCH_STRATEGY_RELATIVE_SHIFT}:
        raise ValueError("unsupported pitch strategy")
    if not _finite(strategy.relative_shift_st):
        raise ValueError("pitch strategy relative_shift_st must be finite")
    if abs(strategy.relative_shift_st) > 24.0:
        raise ValueError("pitch strategy relative_shift_st must be between -24 and 24")


def _validate_formant_strategy(strategy):
    if strategy.strategy_id not in {
        FORMANT_STRATEGY_NEUTRAL,
        FORMANT_STRATEGY_FIXED_SHIFT,
        FORMANT_STRATEGY_NATURAL_COMPENSATION,
        FORMANT_STRATEGY_SIZE_COUPLED,
    }:
        raise ValueError("unsupported formant strategy")
    if not _finite(strategy.fixed_shift_st):
        raise ValueError("formant strategy fixed_shift_st must be finite")
    if not _finite(strategy.compensation_ratio) or strategy.compensation_ratio < 0.0:
        raise ValueError("formant strategy compensation_ratio must be finite and nonnegative")
    if abs(strategy.fixed_shift_st) > MAX_NATURAL_FORMANT_SHIFT_ST:
        raise ValueError("formant strategy fixed shift is restrained to +/-2 semitones")
    if not isinstance(strategy.natural, bool) or not isinstance(strategy.stylized, bool):
        raise ValueError("formant strategy flags must be boolean")


def _validate_dynamics(d):
    if not isinstance(d.compressor_enabled, bool) or not isinstance(d.limiter_enabled, bool):
        raise ValueError("dynamics enabled flags must be boolean")
    _range("compressor_threshold_dbfs", d.compressor_threshold_dbfs, COMPRESSOR_THRESHOLD_RANGE)
    _range("compressor_ratio", d.compressor_ratio, COMPRESSOR_RATIO_RANGE)
    _range("compressor_attack_ms", d.compressor_attack_ms, COMPRESSOR_ATTACK_RANGE)
    _range("compressor_release_ms", d.compressor_release_ms, COMPRESSOR_RELEASE_RANGE)
    _range("compressor_makeup_gain_db", d.compressor_makeup_gain_db, COMPRESSOR_MAKEUP_RANGE)
    _range("limiter_ceiling_dbfs", d.limiter_ceiling_dbfs, LIMITER_CEILING_RANGE)
    _range("limiter_release_ms", d.limiter_release_ms, LIMITER_RELEASE_RANGE)


def _range(name, value, limits):
    if not _finite(value) or value < limits[0] or value > limits[1]:
        raise ValueError(f"{name} must be between {limits[0]:g} and {limits[1]:g}")


def _validate_strength_01(value):
    if not _finite(value):
        raise ValueError("strength must be a finite number")
    value = float(value)
    if value < 0.0 or value > 1.0:
        raise ValueError("strength must be between 0 and 1")
    return value


def _safe_strength(value):
    return float(value) if _finite(value) else 0.0


def _finite(value):
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)


def _optional_positive(value):
    if not _finite(value) or value <= 0.0:
        return None
    return float(value)


def _clamp_signed(value, limit):
    limit = abs(float(limit))
    clamped = max(-limit, min(limit, float(value)))
    return clamped, not math.isclose(clamped, float(value), rel_tol=0.0, abs_tol=1e-9)


def _clamp_range(value, low, high):
    clamped = max(float(low), min(float(high), float(value)))
    return clamped, not math.isclose(clamped, float(value), rel_tol=0.0, abs_tol=1e-9)


def _clamp01(value):
    return max(0.0, min(1.0, float(value)))


def replace_target(profile, **changes):
    data = profile.asdict()
    data["dynamics"] = profile.dynamics
    data["pitch_strategy"] = profile.pitch_strategy
    data["formant_strategy"] = profile.formant_strategy
    if "nominal_formant_shift_st" in changes and "formant_strategy" not in changes:
        strategy = profile.formant_strategy
        if strategy.strategy_id in {FORMANT_STRATEGY_FIXED_SHIFT, FORMANT_STRATEGY_SIZE_COUPLED}:
            data["formant_strategy"] = FormantStrategy(
                strategy.strategy_id,
                fixed_shift_st=changes["nominal_formant_shift_st"],
                compensation_ratio=strategy.compensation_ratio,
                natural=strategy.natural,
                stylized=strategy.stylized,
            )
    data.update(changes)
    return target_voice_profile(**data)


DEFAULT_TARGET_PROFILE = target_voice_profile(
    target_id="diagnostic-neutral",
    display_name="Diagnostic Neutral",
    description="Session-only neutral target for planner inspection.",
    target_median_f0_hz=140.0,
    target_pitch_span_st=6.0,
    pitch_strategy=PitchStrategy(PITCH_STRATEGY_RELATIVE_SHIFT, 0.0),
    nominal_formant_shift_st=0.0,
    formant_strategy=FormantStrategy(FORMANT_STRATEGY_NEUTRAL, natural=True),
    requires_pitch_range=False,
    requires_eq=False,
)

HIGHER_BRIGHTER_REFERENCE = target_voice_profile(
    target_id="diagnostic-higher-brighter",
    display_name="Higher / Brighter Reference",
    description="Diagnostic higher/brighter planning reference, not a production character.",
    target_median_f0_hz=220.0,
    target_pitch_span_st=7.5,
    pitch_strategy=PitchStrategy(PITCH_STRATEGY_ABSOLUTE_F0),
    max_pitch_shift_st=8.0,
    nominal_formant_shift_st=1.2,
    formant_strategy=FormantStrategy(FORMANT_STRATEGY_FIXED_SHIFT, fixed_shift_st=1.2),
    chest_energy_ratio=0.12,
    low_mid_energy_ratio=0.28,
    presence_energy_ratio=0.28,
    brightness_energy_ratio=0.18,
    sibilance_energy_ratio=0.12,
    spectral_tilt_db=-4.0,
    breathiness=0.25,
    harmonic_weight=0.15,
    expect_de_essing=True,
    requires_breathiness=True,
    requires_harmonic_enhancement=True,
    warnings=("Diagnostic values are provisional.",),
)

NATURAL_DEEP_REFERENCE = target_voice_profile(
    target_id="diagnostic-lower-weightier",
    display_name="Natural Deep Reference",
    description="Diagnostic natural deep planning reference: lowers pitch while preserving vowel shape with positive formant compensation.",
    target_median_f0_hz=110.0,
    target_pitch_span_st=4.0,
    pitch_strategy=PitchStrategy(PITCH_STRATEGY_RELATIVE_SHIFT, -3.5),
    max_pitch_shift_st=8.0,
    nominal_formant_shift_st=1.5,
    formant_strategy=FormantStrategy(
        FORMANT_STRATEGY_NATURAL_COMPENSATION,
        fixed_shift_st=1.5,
        compensation_ratio=NATURAL_FORMANT_COMPENSATION_RATIO,
        natural=True,
    ),
    chest_energy_ratio=0.34,
    low_mid_energy_ratio=0.42,
    presence_energy_ratio=0.15,
    brightness_energy_ratio=0.06,
    sibilance_energy_ratio=0.05,
    spectral_tilt_db=-12.0,
    harmonic_weight=0.25,
    dynamics=DynamicsTarget(
        compressor_enabled=True,
        compressor_threshold_dbfs=-18.0,
        compressor_ratio=3.0,
        compressor_attack_ms=10.0,
        compressor_release_ms=150.0,
        compressor_makeup_gain_db=1.0,
        limiter_enabled=True,
        limiter_ceiling_dbfs=-1.0,
        limiter_release_ms=80.0,
    ),
    requires_harmonic_enhancement=True,
    warnings=(
        "Diagnostic values are provisional.",
        "Natural Deep lowers pitch while using positive formant compensation; it is not a large-vocal-tract effect.",
    ),
)

LARGE_CAVERNOUS_REFERENCE = target_voice_profile(
    target_id="diagnostic-large-cavernous",
    display_name="Large / Cavernous Reference",
    description="Diagnostic stylized large-vocal-tract effect; not a natural deep voice.",
    target_median_f0_hz=100.0,
    target_pitch_span_st=3.5,
    pitch_strategy=PitchStrategy(PITCH_STRATEGY_RELATIVE_SHIFT, -4.5),
    max_pitch_shift_st=8.0,
    nominal_formant_shift_st=-1.5,
    formant_strategy=FormantStrategy(
        FORMANT_STRATEGY_SIZE_COUPLED,
        fixed_shift_st=-1.5,
        stylized=True,
    ),
    chest_energy_ratio=0.38,
    low_mid_energy_ratio=0.45,
    presence_energy_ratio=0.12,
    brightness_energy_ratio=0.05,
    sibilance_energy_ratio=0.04,
    spectral_tilt_db=-14.0,
    harmonic_weight=0.25,
    dynamics=DynamicsTarget(
        compressor_enabled=True,
        compressor_threshold_dbfs=-18.0,
        compressor_ratio=3.0,
        compressor_attack_ms=10.0,
        compressor_release_ms=150.0,
        compressor_makeup_gain_db=1.0,
        limiter_enabled=True,
        limiter_ceiling_dbfs=-1.0,
        limiter_release_ms=80.0,
    ),
    requires_harmonic_enhancement=True,
    warnings=(
        "Diagnostic values are provisional.",
        "Large / Cavernous is stylized and may exaggerate vowels, W/R transitions, or nasal resonance.",
    ),
)

LOWER_WEIGHTIER_REFERENCE = NATURAL_DEEP_REFERENCE

TARGET_REFERENCE_ORDER = (
    DEFAULT_TARGET_PROFILE,
    HIGHER_BRIGHTER_REFERENCE,
    NATURAL_DEEP_REFERENCE,
    LARGE_CAVERNOUS_REFERENCE,
)
