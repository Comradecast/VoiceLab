from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace
from numbers import Real
from time import monotonic

import numpy as np

from voice_lab.effects.base import Effect


PARAMETRIC_EQ_BAND_ORDER = ("low_shelf", "low_mid", "mid", "presence", "high_shelf")
PARAMETRIC_EQ_BACKEND = "builtin_biquad"
PARAMETRIC_EQ_TRANSITION_MS = 20.0
PARAMETRIC_EQ_ADDED_LATENCY_FRAMES = 0
EPSILON = 1.0e-12


@dataclass(frozen=True)
class ParametricEqBandDefinition:
    band_id: str
    display_name: str
    filter_type: str
    purpose: str
    default_frequency_hz: float
    min_frequency_hz: float
    max_frequency_hz: float
    default_gain_db: float = 0.0
    min_gain_db: float = -6.0
    max_gain_db: float = 6.0
    default_q: float = 1.0
    min_q: float = 0.3
    max_q: float = 6.0
    q_editable: bool = True

    def asdict(self):
        return asdict(self)


@dataclass(frozen=True)
class ParametricEqBandParameters:
    band_id: str
    display_name: str
    filter_type: str
    requested_enabled: bool
    requested_frequency_hz: float
    requested_gain_db: float
    requested_q: float
    applied_enabled: bool
    applied_frequency_hz: float
    applied_gain_db: float
    applied_q: float
    frequency_clamped: bool = False
    gain_clamped: bool = False
    q_clamped: bool = False
    warnings: tuple[str, ...] = ()

    def asdict(self):
        data = asdict(self)
        data["warnings"] = tuple(self.warnings)
        return data


@dataclass(frozen=True)
class ParametricEqCoefficientBank:
    coefficient_generation: int
    sample_rate: int
    bands: tuple[ParametricEqBandParameters, ...]
    sections: tuple[tuple[float, float, float, float, float], ...]
    active_band_count: int
    flat: bool


@dataclass(frozen=True)
class ParametricEqPlan:
    plan_generation: int
    generated_at: float
    requested_enabled: bool
    requested_bypassed: bool
    applied_enabled: bool
    bands: tuple[ParametricEqBandParameters, ...]
    active_band_count: int
    flat: bool
    coefficient_generation: int
    coefficient_valid: bool
    backend_status: str
    warnings: tuple[str, ...]
    added_latency_frames: int
    intent_source: str = "manual EQ"

    def asdict(self):
        data = asdict(self)
        data["bands"] = tuple(band.asdict() for band in self.bands)
        data["warnings"] = tuple(self.warnings)
        return data


@dataclass(frozen=True)
class ParametricEqBackendHealth:
    backend: str = PARAMETRIC_EQ_BACKEND
    backend_status: str = "active"
    available: bool = True
    failed: bool = False
    failure_reason: str = ""
    added_latency_frames: int = PARAMETRIC_EQ_ADDED_LATENCY_FRAMES

    def asdict(self):
        return asdict(self)


@dataclass(frozen=True)
class ParametricEqApplicationSnapshot:
    lab: str
    requested_plan: ParametricEqPlan
    applied_plan: ParametricEqPlan
    transition_active: bool
    transition_progress: float
    local_bypass: bool
    global_bypass: bool
    coefficient_generation: int
    processing_active: bool
    backend_health: ParametricEqBackendHealth
    failure_reason: str
    reset_generation: int
    current_sample_rate: int
    current_block_size: int
    added_latency_frames: int

    def get(self, name, default=None):
        return getattr(self, name, default)

    def asdict(self):
        data = asdict(self)
        data["requested_plan"] = self.requested_plan.asdict()
        data["applied_plan"] = self.applied_plan.asdict()
        data["backend_health"] = self.backend_health.asdict()
        return data


@dataclass(frozen=True)
class ParametricEqRuntimeStatus:
    plan_generation: int = 0
    coefficient_generation: int = 0
    sample_rate: int = 48000
    block_size: int = 0
    active_band_count: int = 0
    flat: bool = True
    local_bypass: bool = True
    global_bypass: bool = False
    processing_active: bool = False
    transition_active: bool = False
    transition_progress: float = 1.0
    backend_status: str = "active"
    failure_reason: str = ""
    reset_generation: int = 0
    added_latency_frames: int = PARAMETRIC_EQ_ADDED_LATENCY_FRAMES

    def asdict(self):
        return asdict(self)


def default_band_definitions():
    return (
        ParametricEqBandDefinition(
            "low_shelf",
            "Low Shelf",
            "low_shelf",
            "body and chest weight",
            120.0,
            60.0,
            250.0,
            default_q=1.0,
            min_q=1.0,
            max_q=1.0,
            q_editable=False,
        ),
        ParametricEqBandDefinition(
            "low_mid",
            "Low-Mid Peak",
            "peaking",
            "mud, boxiness, lower resonance",
            300.0,
            150.0,
            800.0,
        ),
        ParametricEqBandDefinition(
            "mid",
            "Mid Peak",
            "peaking",
            "nasal and central vocal color",
            1000.0,
            500.0,
            2500.0,
        ),
        ParametricEqBandDefinition(
            "presence",
            "Presence Peak",
            "peaking",
            "intelligibility and upper-mid clarity",
            3000.0,
            1500.0,
            6000.0,
        ),
        ParametricEqBandDefinition(
            "high_shelf",
            "High Shelf",
            "high_shelf",
            "brightness and air",
            8000.0,
            4000.0,
            12000.0,
            default_q=1.0,
            min_q=1.0,
            max_q=1.0,
            q_editable=False,
        ),
    )


def flat_band_parameters(sample_rate=48000):
    return tuple(_band_from_definition(definition, sample_rate) for definition in default_band_definitions())


class ParametricEqController:
    def __init__(self, clock=monotonic, sample_rate=48000):
        self._clock = clock
        self._sample_rate = int(sample_rate)
        self._plan_generation = 0
        self._coefficient_generation = 0
        self._reset_generation = 0
        self._backend_health = ParametricEqBackendHealth()
        self._last_runtime_status = ParametricEqRuntimeStatus(sample_rate=self._sample_rate)
        self._requested_plan = self._make_plan(
            bands=flat_band_parameters(self._sample_rate),
            requested_enabled=False,
            requested_bypassed=True,
            coefficient_generation=0,
        )
        self._applied_plan = self._requested_plan
        self._coefficient_bank = design_coefficient_bank(
            self._requested_plan.bands,
            sample_rate=self._sample_rate,
            coefficient_generation=0,
        )

    def snapshot(self, global_bypass=False):
        runtime = self._last_runtime_status
        health = self._backend_health
        if runtime.failure_reason:
            health = ParametricEqBackendHealth(
                backend_status="failed",
                available=False,
                failed=True,
                failure_reason=runtime.failure_reason,
            )
        return ParametricEqApplicationSnapshot(
            lab="Experimental - Parametric EQ",
            requested_plan=self._requested_plan,
            applied_plan=self._applied_plan,
            transition_active=bool(runtime.transition_active),
            transition_progress=float(runtime.transition_progress),
            local_bypass=self._requested_plan.requested_bypassed or not self._requested_plan.applied_enabled,
            global_bypass=bool(global_bypass),
            coefficient_generation=self._coefficient_bank.coefficient_generation,
            processing_active=bool(runtime.processing_active),
            backend_health=health,
            failure_reason=runtime.failure_reason,
            reset_generation=self._reset_generation,
            current_sample_rate=int(runtime.sample_rate or self._sample_rate),
            current_block_size=int(runtime.block_size or 0),
            added_latency_frames=PARAMETRIC_EQ_ADDED_LATENCY_FRAMES,
        )

    def coefficient_bank(self):
        return self._coefficient_bank

    def local_bypass(self):
        return self._requested_plan.requested_bypassed or not self._requested_plan.applied_enabled

    def applied_plan_generation(self):
        return self._applied_plan.plan_generation

    def runtime_status(self):
        return self._last_runtime_status

    def record_runtime_status(self, status):
        if isinstance(status, ParametricEqRuntimeStatus):
            self._last_runtime_status = status

    def set_enabled(self, enabled):
        return self._publish(tuple(self._requested_plan.bands), requested_enabled=bool(enabled), requested_bypassed=not bool(enabled))

    def set_bypassed(self, bypassed):
        return self._publish(
            tuple(self._requested_plan.bands),
            requested_enabled=not bool(bypassed),
            requested_bypassed=bool(bypassed),
        )

    def set_band_frequency(self, band_id, frequency_hz):
        return self._update_band(band_id, requested_frequency_hz=frequency_hz)

    def set_band_gain(self, band_id, gain_db):
        return self._update_band(band_id, requested_gain_db=gain_db)

    def set_band_q(self, band_id, q):
        return self._update_band(band_id, requested_q=q)

    def reset_band(self, band_id):
        definitions = {definition.band_id: definition for definition in default_band_definitions()}
        if band_id not in definitions:
            raise ValueError("unknown EQ band")
        replacement = _band_from_definition(definitions[band_id], self._sample_rate)
        bands = tuple(replacement if band.band_id == band_id else band for band in self._requested_plan.bands)
        return self._publish(bands)

    def reset_flat(self):
        self._reset_generation += 1
        return self._publish(flat_band_parameters(self._sample_rate), requested_enabled=False, requested_bypassed=True)

    def restore_default_positions(self):
        definitions = {definition.band_id: definition for definition in default_band_definitions()}
        bands = []
        for band in self._requested_plan.bands:
            definition = definitions[band.band_id]
            bands.append(
                validate_band_parameters(
                    band.band_id,
                    enabled=band.requested_enabled,
                    frequency_hz=definition.default_frequency_hz,
                    gain_db=band.requested_gain_db,
                    q=definition.default_q,
                    sample_rate=self._sample_rate,
                )
            )
        return self._publish(tuple(bands))

    def set_complete_plan(self, bands, *, enabled=None, bypassed=None):
        validated = tuple(
            validate_band_parameters(
                band.get("band_id") if isinstance(band, dict) else getattr(band, "band_id", None),
                enabled=band.get("enabled", True) if isinstance(band, dict) else getattr(band, "requested_enabled", True),
                frequency_hz=band.get("frequency_hz") if isinstance(band, dict) else getattr(band, "requested_frequency_hz", None),
                gain_db=band.get("gain_db") if isinstance(band, dict) else getattr(band, "requested_gain_db", None),
                q=band.get("q") if isinstance(band, dict) else getattr(band, "requested_q", None),
                sample_rate=self._sample_rate,
            )
            for band in bands
        )
        if tuple(band.band_id for band in validated) != PARAMETRIC_EQ_BAND_ORDER:
            raise ValueError("complete EQ plan must contain the five ordered bands")
        return self._publish(
            validated,
            requested_enabled=self._requested_plan.requested_enabled if enabled is None else bool(enabled),
            requested_bypassed=self._requested_plan.requested_bypassed if bypassed is None else bool(bypassed),
        )

    def _update_band(self, band_id, **changes):
        existing = {band.band_id: band for band in self._requested_plan.bands}
        if band_id not in existing:
            raise ValueError("unknown EQ band")
        band = existing[band_id]
        updated = validate_band_parameters(
            band_id,
            enabled=changes.get("requested_enabled", band.requested_enabled),
            frequency_hz=changes.get("requested_frequency_hz", band.requested_frequency_hz),
            gain_db=changes.get("requested_gain_db", band.requested_gain_db),
            q=changes.get("requested_q", band.requested_q),
            sample_rate=self._sample_rate,
        )
        bands = tuple(updated if item.band_id == band_id else item for item in self._requested_plan.bands)
        return self._publish(bands)

    def _publish(self, bands, *, requested_enabled=None, requested_bypassed=None):
        requested_enabled = self._requested_plan.requested_enabled if requested_enabled is None else bool(requested_enabled)
        requested_bypassed = self._requested_plan.requested_bypassed if requested_bypassed is None else bool(requested_bypassed)
        coefficient_generation = self._coefficient_generation + 1
        bank = design_coefficient_bank(
            tuple(bands),
            sample_rate=self._sample_rate,
            coefficient_generation=coefficient_generation,
        )
        self._plan_generation += 1
        self._coefficient_generation = coefficient_generation
        plan = self._make_plan(
            bands=tuple(bands),
            requested_enabled=requested_enabled,
            requested_bypassed=requested_bypassed,
            coefficient_generation=coefficient_generation,
        )
        self._requested_plan = plan
        self._applied_plan = plan
        self._coefficient_bank = bank
        return plan

    def _make_plan(self, *, bands, requested_enabled, requested_bypassed, coefficient_generation):
        active_count = sum(1 for band in bands if band.applied_enabled and abs(band.applied_gain_db) > 1.0e-6)
        flat = active_count == 0
        return ParametricEqPlan(
            plan_generation=self._plan_generation,
            generated_at=self._clock(),
            requested_enabled=bool(requested_enabled),
            requested_bypassed=bool(requested_bypassed),
            applied_enabled=bool(requested_enabled and not requested_bypassed),
            bands=tuple(bands),
            active_band_count=active_count,
            flat=flat,
            coefficient_generation=int(coefficient_generation),
            coefficient_valid=True,
            backend_status="active",
            warnings=tuple(_ordered_unique(w for band in bands for w in band.warnings)),
            added_latency_frames=PARAMETRIC_EQ_ADDED_LATENCY_FRAMES,
        )

    def retained_counts(self):
        return {"plans": 1, "coefficient_banks": 1, "transitions": 1}


class ParametricEqEffect(Effect):
    name = "Parametric EQ"

    def __init__(self, controller=None, transition_ms=PARAMETRIC_EQ_TRANSITION_MS):
        self.controller = controller or ParametricEqController()
        self.transition_ms = float(transition_ms)
        self._active_processor = None
        self._transition_old = None
        self._transition_new = None
        self._transition_total = 0
        self._transition_done = 0
        self._active_generation = None
        self._reset_generation = 0
        self._runtime_status = ParametricEqRuntimeStatus()

    def process(self, mono, frames, sample_rate):
        source = np.asarray(mono, dtype=np.float32)
        try:
            bank = self.controller.coefficient_bank()
            self._ensure_processor(bank, int(sample_rate))
            local_bypass = self.controller.local_bypass()
            flat = bool(bank.flat)
            if local_bypass or flat:
                output = source.astype(np.float32, copy=False)
                self._publish_status(
                    bank,
                    sample_rate,
                    frames,
                    processing_active=False,
                    local_bypass=local_bypass,
                    flat=flat,
                )
                return output
            output = self._process_with_transition(source)
            if not np.all(np.isfinite(output)):
                raise RuntimeError("Parametric EQ produced nonfinite output")
            self._publish_status(
                bank,
                sample_rate,
                frames,
                processing_active=True,
                local_bypass=False,
                flat=False,
            )
            return output.astype(np.float32, copy=False)
        except Exception as exc:
            self._runtime_status = replace(
                self._runtime_status,
                backend_status="failed",
                failure_reason=str(exc),
                processing_active=False,
                local_bypass=True,
            )
            self.controller.record_runtime_status(self._runtime_status)
            return source.astype(np.float32, copy=False)

    def status(self):
        return self._runtime_status

    def telemetry(self):
        return self._runtime_status

    def reset(self):
        self._active_processor = None
        self._transition_old = None
        self._transition_new = None
        self._transition_total = 0
        self._transition_done = 0
        self._active_generation = None
        self._reset_generation += 1
        self._runtime_status = replace(
            self._runtime_status,
            reset_generation=self._reset_generation,
            processing_active=False,
            transition_active=False,
            transition_progress=1.0,
            failure_reason="",
            backend_status="active",
        )
        self.controller.record_runtime_status(self._runtime_status)

    def _ensure_processor(self, bank, sample_rate):
        if bank.sample_rate != int(sample_rate):
            raise RuntimeError("Parametric EQ coefficient sample rate does not match callback sample rate")
        if self._active_generation is None:
            self._active_processor = _BiquadCascade(bank.sections)
            self._active_generation = bank.coefficient_generation
            return
        if self._active_generation == bank.coefficient_generation:
            return
        self._transition_old = self._active_processor
        self._transition_new = _BiquadCascade(bank.sections)
        self._transition_total = max(1, int(round((self.transition_ms / 1000.0) * float(sample_rate))))
        self._transition_done = 0
        self._active_processor = self._transition_new
        self._active_generation = bank.coefficient_generation

    def _process_with_transition(self, source):
        if self._transition_old is None or self._transition_new is None:
            return self._active_processor.process(source)
        old = self._transition_old.process(source)
        new = self._transition_new.process(source)
        count = source.shape[0]
        start = self._transition_done
        positions = np.arange(start, start + count, dtype=np.float64)
        weights = np.clip(positions / float(self._transition_total), 0.0, 1.0).astype(np.float32)
        output = old * (1.0 - weights) + new * weights
        self._transition_done += count
        if self._transition_done >= self._transition_total:
            self._transition_old = None
            self._transition_new = None
            self._transition_done = self._transition_total
        return output.astype(np.float32)

    def _publish_status(self, bank, sample_rate, frames, *, processing_active, local_bypass, flat):
        transition_active = self._transition_old is not None and self._transition_new is not None
        progress = 1.0
        if self._transition_total > 0 and transition_active:
            progress = min(1.0, self._transition_done / float(self._transition_total))
        self._runtime_status = ParametricEqRuntimeStatus(
            plan_generation=self.controller.applied_plan_generation(),
            coefficient_generation=bank.coefficient_generation,
            sample_rate=int(sample_rate),
            block_size=int(frames or 0),
            active_band_count=bank.active_band_count,
            flat=bool(flat),
            local_bypass=bool(local_bypass),
            global_bypass=False,
            processing_active=bool(processing_active),
            transition_active=bool(transition_active),
            transition_progress=float(progress),
            backend_status="active",
            failure_reason="",
            reset_generation=self._reset_generation,
            added_latency_frames=PARAMETRIC_EQ_ADDED_LATENCY_FRAMES,
        )
        self.controller.record_runtime_status(self._runtime_status)


class _BiquadCascade:
    def __init__(self, sections):
        self.sections = tuple(tuple(float(v) for v in section) for section in sections)
        self.state = [[0.0, 0.0] for _ in self.sections]

    def process(self, source):
        output = np.asarray(source, dtype=np.float32).astype(np.float64, copy=True)
        for section_index, (b0, b1, b2, a1, a2) in enumerate(self.sections):
            z1, z2 = self.state[section_index]
            for index, sample in enumerate(output):
                value = b0 * sample + z1
                z1 = b1 * sample - a1 * value + z2
                z2 = b2 * sample - a2 * value
                output[index] = value
            self.state[section_index] = [z1, z2]
        return output.astype(np.float32)


def validate_band_parameters(band_id, *, enabled=True, frequency_hz=None, gain_db=None, q=None, sample_rate=48000):
    definitions = {definition.band_id: definition for definition in default_band_definitions()}
    if band_id not in definitions:
        raise ValueError("unknown EQ band")
    definition = definitions[band_id]
    requested_frequency = _finite_required(frequency_hz, "EQ frequency")
    requested_gain = _finite_required(gain_db, "EQ gain")
    requested_q = _finite_required(q, "EQ Q")
    safe_max_frequency = min(definition.max_frequency_hz, float(sample_rate) * 0.45)
    applied_frequency, frequency_clamped = _clamp(requested_frequency, definition.min_frequency_hz, safe_max_frequency)
    applied_gain, gain_clamped = _clamp(requested_gain, definition.min_gain_db, definition.max_gain_db)
    q_min = definition.min_q
    q_max = definition.max_q
    applied_q, q_clamped = _clamp(requested_q, q_min, q_max)
    warnings = []
    if frequency_clamped:
        warnings.append("frequency clamped")
    if gain_clamped:
        warnings.append("gain clamped")
    if q_clamped:
        warnings.append("Q clamped")
    return ParametricEqBandParameters(
        band_id=definition.band_id,
        display_name=definition.display_name,
        filter_type=definition.filter_type,
        requested_enabled=bool(enabled),
        requested_frequency_hz=requested_frequency,
        requested_gain_db=requested_gain,
        requested_q=requested_q,
        applied_enabled=bool(enabled),
        applied_frequency_hz=applied_frequency,
        applied_gain_db=applied_gain,
        applied_q=applied_q,
        frequency_clamped=frequency_clamped,
        gain_clamped=gain_clamped,
        q_clamped=q_clamped,
        warnings=tuple(warnings),
    )


def design_coefficient_bank(bands, *, sample_rate, coefficient_generation):
    sample_rate = _validate_sample_rate(sample_rate)
    sections = []
    active_count = 0
    for band in tuple(bands):
        if not band.applied_enabled or abs(band.applied_gain_db) <= 1.0e-6:
            sections.append((1.0, 0.0, 0.0, 0.0, 0.0))
            continue
        active_count += 1
        sections.append(_design_band(band, sample_rate))
    return ParametricEqCoefficientBank(
        coefficient_generation=int(coefficient_generation),
        sample_rate=sample_rate,
        bands=tuple(bands),
        sections=tuple(sections),
        active_band_count=active_count,
        flat=active_count == 0,
    )


def frequency_response(bank, frequencies_hz):
    freqs = np.asarray(frequencies_hz, dtype=np.float64)
    response = np.ones_like(freqs, dtype=np.complex128)
    z = np.exp(-2j * np.pi * freqs / float(bank.sample_rate))
    z2 = z * z
    for b0, b1, b2, a1, a2 in bank.sections:
        numerator = b0 + b1 * z + b2 * z2
        denominator = 1.0 + a1 * z + a2 * z2
        response *= numerator / denominator
    return response


def _band_from_definition(definition, sample_rate):
    return validate_band_parameters(
        definition.band_id,
        enabled=True,
        frequency_hz=definition.default_frequency_hz,
        gain_db=definition.default_gain_db,
        q=definition.default_q,
        sample_rate=sample_rate,
    )


def _design_band(band, sample_rate):
    frequency = min(band.applied_frequency_hz, sample_rate * 0.45)
    if band.filter_type == "peaking":
        return _rbj_peaking(frequency, band.applied_gain_db, band.applied_q, sample_rate)
    if band.filter_type == "low_shelf":
        return _rbj_low_shelf(frequency, band.applied_gain_db, sample_rate)
    if band.filter_type == "high_shelf":
        return _rbj_high_shelf(frequency, band.applied_gain_db, sample_rate)
    raise ValueError("unsupported EQ filter type")


def _rbj_peaking(frequency_hz, gain_db, q, sample_rate):
    a = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * math.pi * frequency_hz / sample_rate
    alpha = math.sin(w0) / (2.0 * q)
    cos_w0 = math.cos(w0)
    b0 = 1.0 + alpha * a
    b1 = -2.0 * cos_w0
    b2 = 1.0 - alpha * a
    a0 = 1.0 + alpha / a
    a1 = -2.0 * cos_w0
    a2 = 1.0 - alpha / a
    return _normalize_section(b0, b1, b2, a0, a1, a2)


def _rbj_low_shelf(frequency_hz, gain_db, sample_rate, slope=1.0):
    a = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * math.pi * frequency_hz / sample_rate
    cos_w0 = math.cos(w0)
    sin_w0 = math.sin(w0)
    alpha = sin_w0 / 2.0 * math.sqrt((a + 1.0 / a) * (1.0 / slope - 1.0) + 2.0)
    beta = 2.0 * math.sqrt(a) * alpha
    b0 = a * ((a + 1.0) - (a - 1.0) * cos_w0 + beta)
    b1 = 2.0 * a * ((a - 1.0) - (a + 1.0) * cos_w0)
    b2 = a * ((a + 1.0) - (a - 1.0) * cos_w0 - beta)
    a0 = (a + 1.0) + (a - 1.0) * cos_w0 + beta
    a1 = -2.0 * ((a - 1.0) + (a + 1.0) * cos_w0)
    a2 = (a + 1.0) + (a - 1.0) * cos_w0 - beta
    return _normalize_section(b0, b1, b2, a0, a1, a2)


def _rbj_high_shelf(frequency_hz, gain_db, sample_rate, slope=1.0):
    a = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * math.pi * frequency_hz / sample_rate
    cos_w0 = math.cos(w0)
    sin_w0 = math.sin(w0)
    alpha = sin_w0 / 2.0 * math.sqrt((a + 1.0 / a) * (1.0 / slope - 1.0) + 2.0)
    beta = 2.0 * math.sqrt(a) * alpha
    b0 = a * ((a + 1.0) + (a - 1.0) * cos_w0 + beta)
    b1 = -2.0 * a * ((a - 1.0) + (a + 1.0) * cos_w0)
    b2 = a * ((a + 1.0) + (a - 1.0) * cos_w0 - beta)
    a0 = (a + 1.0) - (a - 1.0) * cos_w0 + beta
    a1 = 2.0 * ((a - 1.0) - (a + 1.0) * cos_w0)
    a2 = (a + 1.0) - (a - 1.0) * cos_w0 - beta
    return _normalize_section(b0, b1, b2, a0, a1, a2)


def _normalize_section(b0, b1, b2, a0, a1, a2):
    if abs(a0) <= EPSILON:
        raise ValueError("invalid EQ coefficient denominator")
    section = (b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0)
    if not all(math.isfinite(value) for value in section):
        raise ValueError("nonfinite EQ coefficients")
    roots = np.roots([1.0, section[3], section[4]])
    if np.any(np.abs(roots) >= 1.0):
        raise ValueError("unstable EQ coefficients")
    return tuple(float(value) for value in section)


def _validate_sample_rate(sample_rate):
    if isinstance(sample_rate, bool) or not isinstance(sample_rate, Real):
        raise ValueError("sample rate must be finite")
    value = int(sample_rate)
    if value <= 0 or not math.isfinite(float(sample_rate)):
        raise ValueError("sample rate must be finite and positive")
    return value


def _finite_required(value, label):
    if value is None:
        raise ValueError(f"{label} is required")
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{label} must be finite")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite")
    return number


def _clamp(value, low, high):
    clamped = max(float(low), min(float(high), float(value)))
    return clamped, clamped != float(value)


def _ordered_unique(values):
    result = []
    for value in values:
        if value not in result:
            result.append(value)
    return tuple(result)
