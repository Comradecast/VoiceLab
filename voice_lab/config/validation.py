from dataclasses import dataclass, field
from math import isfinite
from numbers import Real
from typing import Any


GAIN_MIN = 0.0
GAIN_MAX = 5.0
ROBOT_MIN = 0.0
ROBOT_MAX = 1.0
LOWPASS_MIN = 300
LOWPASS_MAX = 8000

PRESET_GAIN_MIN = 0
PRESET_GAIN_MAX = 50
PRESET_ROBOT_MIN = 0
PRESET_ROBOT_MAX = 100


@dataclass(frozen=True)
class ValidationIssue:
    field: str
    message: str


@dataclass(frozen=True)
class EffectParameterValidationResult:
    success: bool
    gain: float | None = None
    robot: float | None = None
    lowpass: int | None = None
    issues: tuple[ValidationIssue, ...] = field(default_factory=tuple)

    @property
    def message(self):
        return "; ".join(issue.message for issue in self.issues)


@dataclass(frozen=True)
class PresetValidationResult:
    success: bool
    preset: dict[str, Any] | None = None
    effect_parameters: EffectParameterValidationResult | None = None
    issues: tuple[ValidationIssue, ...] = field(default_factory=tuple)

    @property
    def message(self):
        return "; ".join(issue.message for issue in self.issues)


def validate_effect_parameters(gain, robot, lowpass):
    issues = []
    normalized_gain = _validate_number("gain", gain, GAIN_MIN, GAIN_MAX, issues, as_int=False)
    normalized_robot = _validate_number("robot", robot, ROBOT_MIN, ROBOT_MAX, issues, as_int=False)
    normalized_lowpass = _validate_number(
        "lowpass",
        lowpass,
        LOWPASS_MIN,
        LOWPASS_MAX,
        issues,
        as_int=True,
    )
    if issues:
        return EffectParameterValidationResult(False, issues=tuple(issues))
    return EffectParameterValidationResult(
        True,
        gain=normalized_gain,
        robot=normalized_robot,
        lowpass=normalized_lowpass,
    )


def validate_preset_parameters(preset):
    if not isinstance(preset, dict):
        issue = ValidationIssue("preset", "Preset must be a mapping")
        return PresetValidationResult(False, issues=(issue,))

    issues = []
    preset_gain = _validate_number(
        "gain",
        preset.get("gain", 10),
        PRESET_GAIN_MIN,
        PRESET_GAIN_MAX,
        issues,
        as_int=False,
    )
    preset_robot = _validate_number(
        "robot",
        preset.get("robot", 0),
        PRESET_ROBOT_MIN,
        PRESET_ROBOT_MAX,
        issues,
        as_int=False,
    )
    preset_lowpass = _validate_number(
        "lowpass",
        preset.get("lowpass", 4000),
        LOWPASS_MIN,
        LOWPASS_MAX,
        issues,
        as_int=True,
    )
    if issues:
        return PresetValidationResult(False, issues=tuple(issues))

    normalized_preset = dict(preset)
    normalized_preset["gain"] = int(preset_gain) if float(preset_gain).is_integer() else preset_gain
    normalized_preset["robot"] = int(preset_robot) if float(preset_robot).is_integer() else preset_robot
    normalized_preset["lowpass"] = preset_lowpass
    effect_parameters = validate_effect_parameters(
        gain=preset_gain / 10.0,
        robot=preset_robot / 100.0,
        lowpass=preset_lowpass,
    )
    if not effect_parameters.success:
        return PresetValidationResult(False, issues=effect_parameters.issues)
    return PresetValidationResult(
        True,
        preset=normalized_preset,
        effect_parameters=effect_parameters,
    )


def _validate_number(field, value, minimum, maximum, issues, as_int):
    if not isinstance(value, Real) or isinstance(value, bool) or not isfinite(value):
        issues.append(ValidationIssue(field, f"{field} must be a finite number"))
        return None
    if value < minimum or value > maximum:
        issues.append(ValidationIssue(field, f"{field} must be between {minimum:g} and {maximum:g}"))
        return None
    if as_int and not float(value).is_integer():
        issues.append(ValidationIssue(field, f"{field} must be an integer"))
        return None
    return int(value) if as_int else float(value)
