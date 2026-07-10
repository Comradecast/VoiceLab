from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable
import re


PLUGIN_API_VERSION = "1.0.0"
_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def validate_identifier(value, label):
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(
            f"{label} must be lowercase and use stable slug/dotted identifier format"
        )


def validate_version(value, label):
    if not isinstance(value, str) or not _VERSION_RE.fullmatch(value):
        raise ValueError(f"{label} must use major.minor.patch version format")


def parse_version(value):
    validate_version(value, "version")
    return tuple(int(part) for part in value.split("."))


@dataclass(frozen=True)
class Compatibility:
    min_api_version: str
    max_api_version: str | None = None

    def __post_init__(self):
        validate_version(self.min_api_version, "min_api_version")
        if self.max_api_version is not None:
            validate_version(self.max_api_version, "max_api_version")
            if parse_version(self.max_api_version) < parse_version(self.min_api_version):
                raise ValueError("max_api_version must be greater than or equal to min_api_version")

    def is_compatible(self, api_version=PLUGIN_API_VERSION):
        current = parse_version(api_version)
        if current < parse_version(self.min_api_version):
            return False
        if self.max_api_version is not None and current > parse_version(self.max_api_version):
            return False
        return True

    def reason(self, api_version=PLUGIN_API_VERSION):
        if self.is_compatible(api_version):
            return ""
        return (
            f"Plugin requires VoiceLab plugin API {self.min_api_version}"
            + (f" through {self.max_api_version}" if self.max_api_version else " or newer")
            + f"; current API is {api_version}"
        )


@dataclass(frozen=True)
class EffectDescriptor:
    effect_id: str
    display_name: str
    category: str
    factory_id: str
    factory: Callable[[Any], Any]
    parameter_metadata: MappingProxyType = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self):
        validate_identifier(self.effect_id, "effect_id")
        validate_identifier(self.factory_id, "factory_id")
        if not self.display_name:
            raise ValueError("effect display_name is required")
        if not self.category:
            raise ValueError("effect category is required")
        if not callable(self.factory):
            raise ValueError("effect factory must be callable")
        object.__setattr__(self, "parameter_metadata", MappingProxyType(dict(self.parameter_metadata)))


@dataclass(frozen=True)
class PluginMetadata:
    plugin_id: str
    display_name: str
    version: str
    provider: str
    description: str
    compatibility: Compatibility
    plugin_type: str = "effect"
    enabled_by_default: bool = True
    effects: tuple[EffectDescriptor, ...] = field(default_factory=tuple)
    homepage: str = ""
    license: str = ""
    metadata: MappingProxyType = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self):
        validate_identifier(self.plugin_id, "plugin_id")
        validate_version(self.version, "plugin version")
        validate_identifier(self.plugin_type, "plugin_type")
        if not self.display_name:
            raise ValueError("plugin display_name is required")
        if not self.provider:
            raise ValueError("plugin provider is required")
        if not self.description:
            raise ValueError("plugin description is required")
        if not isinstance(self.compatibility, Compatibility):
            raise ValueError("plugin compatibility must be Compatibility")
        effects = tuple(self.effects)
        if not effects:
            raise ValueError("plugin must provide at least one effect")
        effect_ids = [effect.effect_id for effect in effects]
        if len(effect_ids) != len(set(effect_ids)):
            raise ValueError("plugin metadata contains duplicate effect ids")
        object.__setattr__(self, "effects", effects)
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))


@dataclass(frozen=True)
class PluginRegistrationResult:
    success: bool
    plugin_id: str = ""
    reason: str = ""
    metadata: PluginMetadata | None = None

    @classmethod
    def ok(cls, metadata):
        return cls(True, plugin_id=metadata.plugin_id, metadata=metadata)

    @classmethod
    def fail(cls, reason, plugin_id=""):
        return cls(False, plugin_id=plugin_id, reason=reason)
