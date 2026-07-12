from dataclasses import dataclass, field, replace
from math import isfinite
from numbers import Real

from voice_lab.config.validation import ValidationIssue


HIGH_PASS_CUTOFF_RANGE = (40.0, 200.0)
GATE_THRESHOLD_RANGE = (-70.0, -20.0)
GATE_RELEASE_RANGE = (40.0, 1000.0)
COMPRESSOR_THRESHOLD_RANGE = (-40.0, 0.0)
COMPRESSOR_RATIO_RANGE = (1.0, 10.0)
COMPRESSOR_ATTACK_RANGE = (1.0, 100.0)
COMPRESSOR_RELEASE_RANGE = (20.0, 1000.0)
COMPRESSOR_MAKEUP_RANGE = (0.0, 12.0)
LIMITER_CEILING_RANGE = (-12.0, -0.5)
LIMITER_RELEASE_RANGE = (20.0, 500.0)


@dataclass(frozen=True)
class HighPassSettings:
    enabled: bool = False
    cutoff_hz: float = 80.0

    def asdict(self):
        return {"enabled": self.enabled, "cutoff_hz": self.cutoff_hz}


@dataclass(frozen=True)
class NoiseGateSettings:
    enabled: bool = False
    threshold_dbfs: float = -45.0
    release_ms: float = 180.0

    def asdict(self):
        return {
            "enabled": self.enabled,
            "threshold_dbfs": self.threshold_dbfs,
            "release_ms": self.release_ms,
        }


@dataclass(frozen=True)
class CompressorSettings:
    enabled: bool = False
    threshold_dbfs: float = -18.0
    ratio: float = 3.0
    attack_ms: float = 10.0
    release_ms: float = 150.0
    makeup_gain_db: float = 0.0

    def asdict(self):
        return {
            "enabled": self.enabled,
            "threshold_dbfs": self.threshold_dbfs,
            "ratio": self.ratio,
            "attack_ms": self.attack_ms,
            "release_ms": self.release_ms,
            "makeup_gain_db": self.makeup_gain_db,
        }


@dataclass(frozen=True)
class LimiterSettings:
    enabled: bool = False
    ceiling_dbfs: float = -1.0
    release_ms: float = 80.0

    def asdict(self):
        return {
            "enabled": self.enabled,
            "ceiling_dbfs": self.ceiling_dbfs,
            "release_ms": self.release_ms,
        }


@dataclass(frozen=True)
class InputProcessingSettings:
    high_pass: HighPassSettings = field(default_factory=HighPassSettings)
    noise_gate: NoiseGateSettings = field(default_factory=NoiseGateSettings)
    compressor: CompressorSettings = field(default_factory=CompressorSettings)
    limiter: LimiterSettings = field(default_factory=LimiterSettings)

    def asdict(self):
        return {
            "high_pass": self.high_pass.asdict(),
            "noise_gate": self.noise_gate.asdict(),
            "compressor": self.compressor.asdict(),
            "limiter": self.limiter.asdict(),
        }


DEFAULT_INPUT_PROCESSING_SETTINGS = InputProcessingSettings()


def input_processing_ranges():
    return {
        "high_pass": {
            "cutoff_hz": _range_dict(HIGH_PASS_CUTOFF_RANGE, "Hz"),
        },
        "noise_gate": {
            "threshold_dbfs": _range_dict(GATE_THRESHOLD_RANGE, "dBFS"),
            "release_ms": _range_dict(GATE_RELEASE_RANGE, "ms"),
        },
        "compressor": {
            "threshold_dbfs": _range_dict(COMPRESSOR_THRESHOLD_RANGE, "dBFS"),
            "ratio": _range_dict(COMPRESSOR_RATIO_RANGE, ":1"),
            "attack_ms": _range_dict(COMPRESSOR_ATTACK_RANGE, "ms"),
            "release_ms": _range_dict(COMPRESSOR_RELEASE_RANGE, "ms"),
            "makeup_gain_db": _range_dict(COMPRESSOR_MAKEUP_RANGE, "dB"),
        },
        "limiter": {
            "ceiling_dbfs": _range_dict(LIMITER_CEILING_RANGE, "dBFS"),
            "release_ms": _range_dict(LIMITER_RELEASE_RANGE, "ms"),
        },
    }


def validate_input_processing_document(data, field="input_processing"):
    issues = []
    if data is None:
        return DEFAULT_INPUT_PROCESSING_SETTINGS, tuple(issues)
    if isinstance(data, InputProcessingSettings):
        data = data.asdict()
    if not isinstance(data, dict):
        return DEFAULT_INPUT_PROCESSING_SETTINGS, (
            ValidationIssue(field, "input_processing must be a mapping"),
        )

    high_pass = _validate_high_pass(data.get("high_pass", {}), f"{field}.high_pass", issues)
    noise_gate = _validate_noise_gate(data.get("noise_gate", {}), f"{field}.noise_gate", issues)
    compressor = _validate_compressor(data.get("compressor", {}), f"{field}.compressor", issues)
    limiter = _validate_limiter(data.get("limiter", {}), f"{field}.limiter", issues)
    return (
        InputProcessingSettings(
            high_pass=high_pass,
            noise_gate=noise_gate,
            compressor=compressor,
            limiter=limiter,
        ),
        tuple(issues),
    )


def update_input_processing(settings, processor, **changes):
    if processor not in {"high_pass", "noise_gate", "compressor", "limiter"}:
        raise ValueError(f"Unsupported input processor: {processor}")
    current = getattr(settings, processor)
    candidate = replace(current, **changes)
    data = settings.asdict()
    data[processor] = candidate.asdict()
    validated, issues = validate_input_processing_document(data)
    return validated, issues


def _validate_high_pass(data, field, issues):
    data = _mapping(data, field, issues)
    default = DEFAULT_INPUT_PROCESSING_SETTINGS.high_pass
    return HighPassSettings(
        enabled=_bool(data.get("enabled", default.enabled), f"{field}.enabled", default.enabled, issues),
        cutoff_hz=_number(
            data.get("cutoff_hz", default.cutoff_hz),
            f"{field}.cutoff_hz",
            default.cutoff_hz,
            HIGH_PASS_CUTOFF_RANGE,
            issues,
        ),
    )


def _validate_noise_gate(data, field, issues):
    data = _mapping(data, field, issues)
    default = DEFAULT_INPUT_PROCESSING_SETTINGS.noise_gate
    return NoiseGateSettings(
        enabled=_bool(data.get("enabled", default.enabled), f"{field}.enabled", default.enabled, issues),
        threshold_dbfs=_number(
            data.get("threshold_dbfs", default.threshold_dbfs),
            f"{field}.threshold_dbfs",
            default.threshold_dbfs,
            GATE_THRESHOLD_RANGE,
            issues,
        ),
        release_ms=_number(
            data.get("release_ms", default.release_ms),
            f"{field}.release_ms",
            default.release_ms,
            GATE_RELEASE_RANGE,
            issues,
        ),
    )


def _validate_compressor(data, field, issues):
    data = _mapping(data, field, issues)
    default = DEFAULT_INPUT_PROCESSING_SETTINGS.compressor
    return CompressorSettings(
        enabled=_bool(data.get("enabled", default.enabled), f"{field}.enabled", default.enabled, issues),
        threshold_dbfs=_number(
            data.get("threshold_dbfs", default.threshold_dbfs),
            f"{field}.threshold_dbfs",
            default.threshold_dbfs,
            COMPRESSOR_THRESHOLD_RANGE,
            issues,
        ),
        ratio=_number(
            data.get("ratio", default.ratio),
            f"{field}.ratio",
            default.ratio,
            COMPRESSOR_RATIO_RANGE,
            issues,
        ),
        attack_ms=_number(
            data.get("attack_ms", default.attack_ms),
            f"{field}.attack_ms",
            default.attack_ms,
            COMPRESSOR_ATTACK_RANGE,
            issues,
        ),
        release_ms=_number(
            data.get("release_ms", default.release_ms),
            f"{field}.release_ms",
            default.release_ms,
            COMPRESSOR_RELEASE_RANGE,
            issues,
        ),
        makeup_gain_db=_number(
            data.get("makeup_gain_db", default.makeup_gain_db),
            f"{field}.makeup_gain_db",
            default.makeup_gain_db,
            COMPRESSOR_MAKEUP_RANGE,
            issues,
        ),
    )


def _validate_limiter(data, field, issues):
    data = _mapping(data, field, issues)
    default = DEFAULT_INPUT_PROCESSING_SETTINGS.limiter
    return LimiterSettings(
        enabled=_bool(data.get("enabled", default.enabled), f"{field}.enabled", default.enabled, issues),
        ceiling_dbfs=_number(
            data.get("ceiling_dbfs", default.ceiling_dbfs),
            f"{field}.ceiling_dbfs",
            default.ceiling_dbfs,
            LIMITER_CEILING_RANGE,
            issues,
        ),
        release_ms=_number(
            data.get("release_ms", default.release_ms),
            f"{field}.release_ms",
            default.release_ms,
            LIMITER_RELEASE_RANGE,
            issues,
        ),
    )


def _mapping(value, field, issues):
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    issues.append(ValidationIssue(field, f"{field} must be a mapping"))
    return {}


def _bool(value, field, default, issues):
    if isinstance(value, bool):
        return value
    issues.append(ValidationIssue(field, f"{field} must be a boolean"))
    return default


def _number(value, field, default, limits, issues):
    if not isinstance(value, Real) or isinstance(value, bool) or not isfinite(value):
        issues.append(ValidationIssue(field, f"{field} must be a finite number"))
        return default
    value = float(value)
    low, high = limits
    if value < low or value > high:
        issues.append(ValidationIssue(field, f"{field} must be between {low:g} and {high:g}"))
        return default
    return value


def _range_dict(limits, unit):
    return {"minimum": limits[0], "maximum": limits[1], "unit": unit}
