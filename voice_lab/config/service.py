from dataclasses import dataclass, field
from typing import Any

from voice_lab.config.presets import load_presets, save_presets
from voice_lab.config.settings import (
    load_settings,
    save_settings,
    update_settings,
    with_device_identity,
)
from voice_lab.config.validation import (
    EffectParameterValidationResult,
    PresetValidationResult,
    ValidationIssue,
    validate_effect_parameters,
    validate_preset_parameters,
)


@dataclass(frozen=True)
class PresetSelectionResult:
    success: bool
    preset: dict[str, Any] | None = None
    effect_parameters: EffectParameterValidationResult | None = None
    issues: tuple[ValidationIssue, ...] = field(default_factory=tuple)
    message: str = ""


@dataclass(frozen=True)
class PresetSaveResult:
    success: bool
    preset: dict[str, Any] | None = None
    issues: tuple[ValidationIssue, ...] = field(default_factory=tuple)
    message: str = ""
    error: Exception | None = None


@dataclass(frozen=True)
class PresetDeleteResult:
    success: bool
    message: str = ""
    error: Exception | None = None


class ConfigurationService:
    def __init__(
        self,
        load_func=load_presets,
        save_func=save_presets,
        settings_load_func=load_settings,
        settings_save_func=save_settings,
    ):
        self._save_func = save_func
        self._settings_save_func = settings_save_func
        self._presets = load_func()
        self._settings_load_result = settings_load_func()
        self._settings = self._settings_load_result.settings
        self._presets_dirty = False
        self._settings_dirty = False

    def preset_names(self):
        return sorted(self._presets.keys())

    def operator_settings(self):
        return self._settings

    def settings_load_result(self):
        return self._settings_load_result

    def validate_effect_parameters(self, gain, robot, lowpass, pitch=0.0):
        return validate_effect_parameters(gain, robot, lowpass, pitch)

    def select_preset(self, name):
        if not name or name not in self._presets:
            return PresetSelectionResult(False, message=f"Preset not found: {name}")

        validation = validate_preset_parameters(self._presets[name])
        if not validation.success:
            return PresetSelectionResult(
                False,
                issues=validation.issues,
                message=f"Invalid preset: {validation.message}",
            )
        return PresetSelectionResult(
            True,
            preset=validation.preset,
            effect_parameters=validation.effect_parameters,
        )

    def save_preset(self, name, params):
        validation = validate_preset_parameters(params)
        if not validation.success:
            return PresetSaveResult(
                False,
                issues=validation.issues,
                message=f"Invalid preset: {validation.message}",
            )

        updated_presets = dict(self._presets)
        updated_presets[name] = validation.preset
        try:
            self._save_func(updated_presets)
        except Exception as exc:
            return PresetSaveResult(False, message=f"Preset save failed: {exc}", error=exc)

        self._presets = updated_presets
        self._presets_dirty = False
        return PresetSaveResult(True, preset=validation.preset, message=f"Saved preset: {name}")

    def rename_preset(self, old_name, new_name):
        if old_name not in self._presets:
            return PresetSaveResult(False, message=f"Preset not found: {old_name}")
        if new_name in self._presets:
            return PresetSaveResult(False, message=f"Preset already exists: {new_name}")
        validation = validate_preset_parameters(self._presets[old_name])
        if not validation.success:
            return PresetSaveResult(
                False,
                issues=validation.issues,
                message=f"Invalid preset: {validation.message}",
            )

        updated_presets = dict(self._presets)
        updated_presets[new_name] = validation.preset
        del updated_presets[old_name]
        try:
            self._save_func(updated_presets)
        except Exception as exc:
            return PresetSaveResult(False, message=f"Preset rename failed: {exc}", error=exc)

        self._presets = updated_presets
        self._presets_dirty = False
        return PresetSaveResult(True, preset=validation.preset, message=f"Renamed preset: {new_name}")

    def duplicate_preset(self, source_name, new_name):
        if source_name not in self._presets:
            return PresetSaveResult(False, message=f"Preset not found: {source_name}")
        if new_name in self._presets:
            return PresetSaveResult(False, message=f"Preset already exists: {new_name}")
        validation = validate_preset_parameters(self._presets[source_name])
        if not validation.success:
            return PresetSaveResult(
                False,
                issues=validation.issues,
                message=f"Invalid preset: {validation.message}",
            )

        updated_presets = dict(self._presets)
        updated_presets[new_name] = validation.preset
        try:
            self._save_func(updated_presets)
        except Exception as exc:
            return PresetSaveResult(False, message=f"Preset duplicate failed: {exc}", error=exc)

        self._presets = updated_presets
        self._presets_dirty = False
        return PresetSaveResult(True, preset=validation.preset, message=f"Duplicated preset: {new_name}")

    def delete_preset(self, name):
        if name not in self._presets:
            return PresetDeleteResult(False, message=f"Preset not found: {name}")

        updated_presets = dict(self._presets)
        del updated_presets[name]
        try:
            self._save_func(updated_presets)
        except Exception as exc:
            return PresetDeleteResult(False, message=f"Preset delete failed: {exc}", error=exc)

        self._presets = updated_presets
        self._presets_dirty = False
        return PresetDeleteResult(True, message=f"Deleted preset: {name}")

    def validation_from_preset(self, preset):
        return validate_preset_parameters(preset)

    def update_operator_settings(self, **changes):
        settings, issues = update_settings(self._settings, **changes)
        self._settings = settings
        self._settings_dirty = True
        return issues

    def set_preferred_device(self, role, identity):
        self._settings = with_device_identity(self._settings, role, identity)
        self._settings_dirty = True

    def mark_settings_dirty(self):
        self._settings_dirty = True

    def flush(self):
        if self._presets_dirty:
            self._save_func(dict(self._presets))
            self._presets_dirty = False
        if self._settings_dirty:
            self._settings_save_func(self._settings)
            self._settings_dirty = False
