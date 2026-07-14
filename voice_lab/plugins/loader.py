from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from voice_lab.effects import (
    CompressorEffect,
    EffectChain,
    GainEffect,
    HighPassFilterEffect,
    LowpassEffect,
    NoiseGateEffect,
    ParametricEqEffect,
    PitchShiftEffect,
    RobotEffect,
    VoiceLimiterEffect,
)
from voice_lab.plugins.discovery import BUILTIN_PLUGIN_SOURCE
from voice_lab.plugins.metadata import (
    Compatibility,
    EffectDescriptor,
    PluginMetadata,
    validate_identifier,
)


MANIFEST_VERSION = "1"
_ROOT_FIELDS = {
    "manifest_version",
    "plugin_id",
    "display_name",
    "version",
    "provider",
    "author",
    "description",
    "compatibility",
    "plugin_type",
    "enabled_by_default",
    "effects",
    "homepage",
    "license",
    "metadata",
}
_EFFECT_FIELDS = {
    "effect_id",
    "display_name",
    "category",
    "implementation",
    "factory_id",
    "parameter_metadata",
    "metadata",
}


@dataclass(frozen=True)
class ManifestLoadResult:
    candidate: Any
    success: bool
    metadata: PluginMetadata | None = None
    reason: str = ""
    diagnostics: MappingProxyType = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self):
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))

    @classmethod
    def ok(cls, candidate, metadata, **diagnostics):
        return cls(candidate=candidate, success=True, metadata=metadata, diagnostics=diagnostics)

    @classmethod
    def fail(cls, candidate, reason, **diagnostics):
        return cls(candidate=candidate, success=False, reason=reason, diagnostics=diagnostics)


def builtin_plugin_metadata(formant_lab=False, parametric_eq_lab=False):
    effects = [
        EffectDescriptor(
            effect_id="voicelab.effect.high_pass",
            display_name="High-Pass",
            category="filter",
            factory_id="voicelab.factory.high_pass",
            factory=lambda effect_state: HighPassFilterEffect(effect_state.input_processing.high_pass),
            parameter_metadata={
                "enabled": {"default": False},
                "cutoff_hz": {"unit": "Hz", "minimum": 40, "maximum": 200, "default": 80},
            },
        ),
        EffectDescriptor(
            effect_id="voicelab.effect.noise_gate",
            display_name="Noise Gate",
            category="dynamics",
            factory_id="voicelab.factory.noise_gate",
            factory=lambda effect_state: NoiseGateEffect(effect_state.input_processing.noise_gate),
            parameter_metadata={
                "enabled": {"default": False},
                "threshold_dbfs": {"unit": "dBFS", "minimum": -70, "maximum": -20, "default": -45},
                "release_ms": {"unit": "ms", "minimum": 40, "maximum": 1000, "default": 180},
                "attack_ms": {"fixed": 8},
                "hold_ms": {"fixed": 50},
                "ratio": {"fixed": 2.5},
                "attenuation_floor_db": {"fixed": -36},
            },
        ),
        EffectDescriptor(
            effect_id="voicelab.effect.compressor",
            display_name="Compressor",
            category="dynamics",
            factory_id="voicelab.factory.compressor",
            factory=lambda effect_state: CompressorEffect(
                effect_state.input_processing.compressor,
                _execution_compressor_provider(effect_state),
            ),
            parameter_metadata={
                "enabled": {"default": False},
                "threshold_dbfs": {"unit": "dBFS", "minimum": -40, "maximum": 0, "default": -18},
                "ratio": {"unit": ":1", "minimum": 1.0, "maximum": 10.0, "default": 3.0},
                "attack_ms": {"unit": "ms", "minimum": 1, "maximum": 100, "default": 10},
                "release_ms": {"unit": "ms", "minimum": 20, "maximum": 1000, "default": 150},
                "makeup_gain_db": {"unit": "dB", "minimum": 0, "maximum": 12, "default": 0},
            },
        ),
        _pitch_descriptor(formant_lab),
    ]
    if parametric_eq_lab:
        effects.append(
            EffectDescriptor(
                effect_id="voicelab.effect.parametric_eq",
                display_name="Parametric EQ",
                category="filter",
                factory_id="voicelab.factory.parametric_eq",
                factory=lambda effect_state: ParametricEqEffect(effect_state.parametric_eq_controller),
                parameter_metadata={
                    "bands": 5,
                    "gain_db": {"unit": "dB", "minimum": -6.0, "maximum": 6.0},
                    "latency_frames": 0,
                    "scope": "manual session-only Parametric EQ Lab",
                },
            )
        )
    effects.extend(
        (
            EffectDescriptor(
                effect_id="voicelab.effect.robot",
                display_name="Robot",
                category="voice",
                factory_id="voicelab.factory.robot",
                factory=lambda effect_state: RobotEffect(lambda: effect_state.robot),
            ),
            EffectDescriptor(
                effect_id="voicelab.effect.lowpass",
                display_name="Lowpass",
                category="filter",
                factory_id="voicelab.factory.lowpass",
                factory=lambda effect_state: LowpassEffect(lambda: effect_state.lowpass),
            ),
            EffectDescriptor(
                effect_id="voicelab.effect.gain",
                display_name="Gain",
                category="utility",
                factory_id="voicelab.factory.gain",
                factory=lambda effect_state: GainEffect(lambda: effect_state.gain),
            ),
            EffectDescriptor(
                effect_id="voicelab.effect.limiter",
                display_name="Limiter",
                category="dynamics",
                factory_id="voicelab.factory.limiter",
                factory=lambda effect_state: VoiceLimiterEffect(
                    effect_state.input_processing.limiter,
                    _execution_limiter_provider(effect_state),
                ),
                parameter_metadata={
                    "enabled": {"default": False},
                    "ceiling_dbfs": {"unit": "dBFS", "minimum": -12, "maximum": -0.5, "default": -1},
                    "release_ms": {"unit": "ms", "minimum": 20, "maximum": 500, "default": 80},
                    "scope": "processed voice path before Mixer",
                },
            ),
        )
    )
    return PluginMetadata(
        plugin_id="voicelab.builtin.effects",
        display_name="VoiceLab Built-In Effects",
        version="1.0.0",
        provider="VoiceLab",
        description="Built-in input processing, Pitch Shift, Robot, Lowpass, Gain, and limiter effects.",
        compatibility=Compatibility(min_api_version="1.0.0", max_api_version="1.0.0"),
        effects=tuple(effects),
    )


def _pitch_descriptor(formant_lab=False):
    if formant_lab:
        return EffectDescriptor(
            effect_id="voicelab.effect.experimental_pitch_formant",
            display_name="Experimental Pitch/Formant",
            category="voice",
            factory_id="voicelab.factory.experimental_pitch_formant",
            factory=_make_experimental_pitch_formant,
            parameter_metadata={
                "pitch_semitones": {"unit": "semitones", "minimum": -12, "maximum": 12, "default": 0},
                "formant_semitones": {"unit": "semitones", "minimum": -12, "maximum": 12, "default": 0},
                "formant_factor": {"conversion": "2 ** (formant_semitones / 12)"},
                "prototype": "isolated formant-lab mode only",
            },
        )
    return EffectDescriptor(
        effect_id="pitch_shift",
        display_name="Pitch Shift",
        category="voice",
        factory_id="voicelab.factory.pitch_shift",
        factory=lambda effect_state: PitchShiftEffect(lambda: effect_state.pitch),
        parameter_metadata={
            "semitones": {
                "unit": "semitones",
                "minimum": -12,
                "maximum": 12,
                "default": 0,
            },
            "backend": {
                "preferred": "signalsmith",
                "fallback": "pedalboard",
                "native_module": "voice_lab.effects._signalsmith_pitch",
                "prototype_status": "source_available_native_build_pending",
            },
            "streaming_adapter": {
                "processing_window_frames": 2048,
                "max_buffer_windows": 2,
                "startup_underflow": "silence while priming",
                "parameter_change_policy": "reset and re-prime on semitone changes",
                "silence_transition_policy": "flush buffers and reset once on exact digital silence",
                "processing_window_ms_at_48khz": 42.666666666666664,
                "first_output_delay_ms_at_48khz": 21.333333333333332,
            },
        },
    )


def _make_experimental_pitch_formant(effect_state):
    from voice_lab.effects.formant_lab import ExperimentalPitchFormantEffect

    runtime = getattr(effect_state, "transformation_execution_runtime", None)
    if runtime is None:
        return ExperimentalPitchFormantEffect(effect_state.formant_lab)
    return ExperimentalPitchFormantEffect(
        effect_state.formant_lab,
        runtime_parameters_provider=runtime.formant_parameters_for_block,
        latency_reporter=runtime.set_latency_frames,
        backend_health_reporter=runtime.publish_backend_health,
    )


def _execution_compressor_provider(effect_state):
    runtime = getattr(effect_state, "transformation_execution_runtime", None)
    if runtime is None:
        return None
    return runtime.compressor_settings_for_block


def _execution_limiter_provider(effect_state):
    runtime = getattr(effect_state, "transformation_execution_runtime", None)
    if runtime is None:
        return None
    return runtime.limiter_settings_for_block


def load_effects_from_metadata(metadata, effect_state):
    return [descriptor.factory(effect_state) for descriptor in metadata.effects]


def load_candidate_metadata(candidate):
    result = load_candidate_manifest(candidate)
    if not result.success:
        raise ValueError(result.reason)
    return result.metadata


def load_candidate_manifest(candidate):
    if candidate.candidate_type == "builtin" and candidate.source == BUILTIN_PLUGIN_SOURCE:
        return ManifestLoadResult.ok(candidate, builtin_plugin_metadata(), source="builtin")
    if candidate.candidate_type != "manifest":
        return ManifestLoadResult.fail(
            candidate,
            f"Unsupported plugin candidate type: {candidate.candidate_type}",
        )
    try:
        manifest = dict(candidate.manifest)
        if not manifest and candidate.manifest_path is not None:
            manifest = _read_manifest(candidate.manifest_path)
        metadata = plugin_metadata_from_manifest(manifest)
        return ManifestLoadResult.ok(candidate, metadata, source=str(candidate.source))
    except FileNotFoundError as exc:
        return ManifestLoadResult.fail(candidate, f"Plugin manifest is missing: {exc}")
    except PermissionError as exc:
        return ManifestLoadResult.fail(candidate, f"Plugin manifest is unreadable: {exc}")
    except ValueError as exc:
        return ManifestLoadResult.fail(candidate, str(exc))
    except Exception as exc:
        return ManifestLoadResult.fail(candidate, f"Plugin manifest load failed: {exc}")


def plugin_metadata_from_manifest(manifest):
    if not isinstance(manifest, dict):
        raise ValueError("manifest root must be an object")
    manifest_version = _required_string(manifest, "manifest_version")
    if manifest_version != MANIFEST_VERSION:
        raise ValueError(f"Unsupported manifest_version: {manifest_version}")

    unknown_root_fields = _unknown_fields(manifest, _ROOT_FIELDS)
    compatibility_data = _required_mapping(manifest, "compatibility")
    effects_data = _required_list(manifest, "effects")
    if not effects_data:
        raise ValueError("effects must contain at least one effect descriptor")

    provider = manifest.get("provider", manifest.get("author"))
    if not isinstance(provider, str) or not provider:
        raise ValueError("provider or author is required")

    effects = tuple(
        _effect_descriptor_from_manifest_effect(effect_data)
        for effect_data in effects_data
    )

    metadata = dict(_optional_mapping(manifest, "metadata"))
    if unknown_root_fields:
        metadata["unknown_fields"] = tuple(unknown_root_fields)
    metadata["manifest_version"] = manifest_version

    return PluginMetadata(
        plugin_id=_required_string(manifest, "plugin_id"),
        display_name=_required_string(manifest, "display_name"),
        version=_required_string(manifest, "version"),
        provider=provider,
        description=_required_string(manifest, "description"),
        compatibility=Compatibility(
            min_api_version=_required_string(compatibility_data, "min_api_version"),
            max_api_version=_optional_string(compatibility_data, "max_api_version"),
        ),
        plugin_type=_optional_string(manifest, "plugin_type", default="effect"),
        enabled_by_default=_optional_bool(manifest, "enabled_by_default", default=True),
        effects=effects,
        homepage=_optional_string(manifest, "homepage", default=""),
        license=_optional_string(manifest, "license", default=""),
        metadata=metadata,
    )


def _effect_descriptor_from_manifest_effect(effect_data):
    if not isinstance(effect_data, dict):
        raise ValueError("effect descriptors must be objects")
    unknown_effect_fields = _unknown_fields(effect_data, _EFFECT_FIELDS)
    factory_id = effect_data.get("implementation", effect_data.get("factory_id"))
    if not isinstance(factory_id, str) or not factory_id:
        raise ValueError("effect implementation or factory_id is required")
    validate_identifier(factory_id, "effect implementation")

    parameter_metadata = dict(_optional_mapping(effect_data, "parameter_metadata"))
    effect_metadata = dict(_optional_mapping(effect_data, "metadata"))
    if unknown_effect_fields:
        effect_metadata["unknown_fields"] = tuple(unknown_effect_fields)
    if effect_metadata:
        parameter_metadata["manifest_metadata"] = effect_metadata

    return EffectDescriptor(
        effect_id=_required_string(effect_data, "effect_id"),
        display_name=_required_string(effect_data, "display_name"),
        category=_required_string(effect_data, "category"),
        factory_id=factory_id,
        factory=_external_manifest_factory(factory_id),
        parameter_metadata=parameter_metadata,
    )


def _external_manifest_factory(factory_id):
    def unresolved_external_factory(effect_state):
        raise RuntimeError(
            f"External plugin implementation is not executable in M4.3: {factory_id}"
        )

    return unresolved_external_factory


def _read_manifest(manifest_path):
    if manifest_path.stat().st_size > 1024 * 1024:
        raise ValueError("manifest file is too large")
    with manifest_path.open("r", encoding="utf-8") as handle:
        import json

        manifest = json.load(handle)
    if not isinstance(manifest, dict):
        raise ValueError("manifest root must be an object")
    return manifest


def _required_string(data, field_name):
    value = data.get(field_name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} is required")
    return value


def _optional_string(data, field_name, default=None):
    value = data.get(field_name, default)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    return value


def _optional_bool(data, field_name, default=False):
    value = data.get(field_name, default)
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a boolean")
    return value


def _required_mapping(data, field_name):
    value = data.get(field_name)
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    return value


def _optional_mapping(data, field_name):
    value = data.get(field_name, {})
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    return value


def _required_list(data, field_name):
    value = data.get(field_name)
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    return value


def _unknown_fields(data, known_fields):
    return sorted(field for field in data if field not in known_fields)


def load_builtin_effect_chain(effect_state, runtime_failure_handler=None, formant_lab=False, parametric_eq_lab=False):
    return EffectChain(
        load_effects_from_metadata(
            builtin_plugin_metadata(formant_lab=formant_lab, parametric_eq_lab=parametric_eq_lab),
            effect_state,
        ),
        runtime_failure_handler=runtime_failure_handler,
    )
