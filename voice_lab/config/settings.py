import json
import os
import tempfile
from dataclasses import dataclass, field, replace
from math import isfinite
from numbers import Real
from typing import Any

from voice_lab.config.config import SETTINGS_PATH
from voice_lab.config.validation import ValidationIssue
from voice_lab.config.voice_characters import DEFAULT_CHARACTER_STRENGTH, validate_strength


SETTINGS_SCHEMA_VERSION = 1
DEVICE_ROLES = ("input", "virtual_output", "monitor_output")


@dataclass(frozen=True)
class StoredDeviceIdentity:
    name: str
    hostapi: int | str
    max_input_channels: int
    max_output_channels: int
    default_samplerate: float | None = None

    @property
    def identity(self):
        return (
            self.name,
            self.hostapi,
            self.max_input_channels,
            self.max_output_channels,
            self.default_samplerate,
        )

    def asdict(self):
        return {
            "name": self.name,
            "hostapi": self.hostapi,
            "max_input_channels": self.max_input_channels,
            "max_output_channels": self.max_output_channels,
            "default_samplerate": self.default_samplerate,
        }


@dataclass(frozen=True)
class OperatorSettings:
    schema_version: int = SETTINGS_SCHEMA_VERSION
    devices: dict[str, StoredDeviceIdentity] = field(default_factory=dict)
    monitor_enabled: bool = False
    monitor_volume: float = 0.35
    soundboard_volume: float = 0.70
    selected_preset: str | None = None
    selected_character_id: str | None = None
    character_strength: float = DEFAULT_CHARACTER_STRENGTH

    def asdict(self):
        return {
            "schema_version": self.schema_version,
            "devices": {
                role: identity.asdict()
                for role, identity in self.devices.items()
                if role in DEVICE_ROLES
            },
            "monitor_enabled": self.monitor_enabled,
            "monitor_volume": self.monitor_volume,
            "soundboard_volume": self.soundboard_volume,
            "selected_preset": self.selected_preset,
            "selected_character_id": self.selected_character_id,
            "character_strength": self.character_strength,
        }


@dataclass(frozen=True)
class SettingsLoadResult:
    settings: OperatorSettings
    issues: tuple[ValidationIssue, ...] = field(default_factory=tuple)
    missing: bool = False
    unsupported_schema: bool = False
    read_failed: bool = False
    write_allowed: bool = True


def load_settings(path=SETTINGS_PATH):
    if not os.path.exists(path):
        return SettingsLoadResult(OperatorSettings(), missing=True)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception as exc:
        return SettingsLoadResult(
            OperatorSettings(),
            issues=(ValidationIssue("settings", f"Settings could not be read: {exc}"),),
            read_failed=True,
        )
    return validate_settings_document(data)


def save_settings(settings, path=SETTINGS_PATH):
    validated = validate_settings_document(settings.asdict())
    if validated.unsupported_schema or validated.read_failed:
        raise ValueError("Cannot save invalid operator settings")
    payload = validated.settings.asdict()
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=directory,
            prefix=".settings.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = handle.name
            json.dump(payload, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path is not None:
            try:
                os.unlink(temp_path)
            except OSError:
                pass


def validate_settings_document(data):
    issues = []
    if not isinstance(data, dict):
        return SettingsLoadResult(
            OperatorSettings(),
            issues=(ValidationIssue("settings", "Settings root must be a mapping"),),
            read_failed=True,
        )

    schema_version = data.get("schema_version")
    if schema_version != SETTINGS_SCHEMA_VERSION:
        return SettingsLoadResult(
            OperatorSettings(),
            issues=(ValidationIssue("schema_version", "Unsupported settings schema version"),),
            unsupported_schema=True,
            write_allowed=False,
        )

    devices = _validate_devices(data.get("devices", {}), issues)
    monitor_enabled = _validate_bool(
        "monitor_enabled",
        data.get("monitor_enabled", False),
        False,
        issues,
    )
    monitor_volume = _validate_volume(
        "monitor_volume",
        data.get("monitor_volume", 0.35),
        0.35,
        issues,
    )
    soundboard_volume = _validate_volume(
        "soundboard_volume",
        data.get("soundboard_volume", 0.70),
        0.70,
        issues,
    )
    selected_preset = _validate_optional_string(
        "selected_preset",
        data.get("selected_preset"),
        issues,
    )
    selected_character_id = _validate_optional_string(
        "selected_character_id",
        data.get("selected_character_id"),
        issues,
    )
    character_strength = _validate_strength(
        "character_strength",
        data.get("character_strength", DEFAULT_CHARACTER_STRENGTH),
        DEFAULT_CHARACTER_STRENGTH,
        issues,
    )
    return SettingsLoadResult(
        OperatorSettings(
            devices=devices,
            monitor_enabled=monitor_enabled,
            monitor_volume=monitor_volume,
            soundboard_volume=soundboard_volume,
            selected_preset=selected_preset,
            selected_character_id=selected_character_id,
            character_strength=character_strength,
        ),
        issues=tuple(issues),
    )


def update_settings(settings, **changes):
    data = settings.asdict()
    data.update(changes)
    result = validate_settings_document(data)
    return result.settings, result.issues


def with_device_identity(settings, role, identity):
    if role not in DEVICE_ROLES:
        raise ValueError(f"Unsupported device role: {role}")
    devices = dict(settings.devices)
    if identity is None:
        devices.pop(role, None)
    elif isinstance(identity, StoredDeviceIdentity):
        devices[role] = identity
    else:
        devices[role] = _validate_device_identity(role, identity, [])
    return replace(settings, devices=devices)


def _validate_devices(value, issues):
    if value is None:
        return {}
    if not isinstance(value, dict):
        issues.append(ValidationIssue("devices", "devices must be a mapping"))
        return {}
    devices = {}
    for role, identity_data in value.items():
        if role not in DEVICE_ROLES:
            issues.append(ValidationIssue(f"devices.{role}", "Unknown device role ignored"))
            continue
        identity = _validate_device_identity(f"devices.{role}", identity_data, issues)
        if identity is not None:
            devices[role] = identity
    return devices


def _validate_device_identity(field, value, issues):
    if not isinstance(value, dict):
        issues.append(ValidationIssue(field, "Device identity must be a mapping"))
        return None
    name = value.get("name")
    hostapi = value.get("hostapi")
    max_input_channels = value.get("max_input_channels")
    max_output_channels = value.get("max_output_channels")
    default_samplerate = value.get("default_samplerate")
    if not isinstance(name, str) or not name:
        issues.append(ValidationIssue(f"{field}.name", "Device identity name is required"))
        return None
    if not isinstance(hostapi, (int, str)) or isinstance(hostapi, bool):
        issues.append(ValidationIssue(f"{field}.hostapi", "Device host API must be a string or integer"))
        return None
    if not _valid_channel_count(max_input_channels):
        issues.append(ValidationIssue(f"{field}.max_input_channels", "Input channels must be a non-negative integer"))
        return None
    if not _valid_channel_count(max_output_channels):
        issues.append(ValidationIssue(f"{field}.max_output_channels", "Output channels must be a non-negative integer"))
        return None
    samplerate = None
    if default_samplerate is not None:
        if not isinstance(default_samplerate, Real) or isinstance(default_samplerate, bool) or not isfinite(default_samplerate):
            issues.append(ValidationIssue(f"{field}.default_samplerate", "Default sample rate must be finite"))
            return None
        samplerate = float(default_samplerate)
    return StoredDeviceIdentity(
        name=name,
        hostapi=hostapi,
        max_input_channels=int(max_input_channels),
        max_output_channels=int(max_output_channels),
        default_samplerate=samplerate,
    )


def _valid_channel_count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _validate_bool(field, value, default, issues):
    if isinstance(value, bool):
        return value
    issues.append(ValidationIssue(field, f"{field} must be a boolean"))
    return default


def _validate_volume(field, value, default, issues):
    if not isinstance(value, Real) or isinstance(value, bool) or not isfinite(value):
        issues.append(ValidationIssue(field, f"{field} must be a finite number"))
        return default
    if value < 0.0 or value > 1.0:
        issues.append(ValidationIssue(field, f"{field} must be between 0 and 1"))
        return default
    return float(value)


def _validate_optional_string(field, value, issues):
    if value is None:
        return None
    if isinstance(value, str) and value:
        return value
    issues.append(ValidationIssue(field, f"{field} must be a non-empty string"))
    return None


def _validate_strength(field, value, default, issues):
    try:
        return validate_strength(value)
    except ValueError as exc:
        issues.append(ValidationIssue(field, str(exc)))
        return default
