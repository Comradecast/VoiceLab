from voice_lab.effects import EffectChain
from voice_lab.plugins.loader import (
    builtin_plugin_metadata,
    load_candidate_manifest,
    load_effects_from_metadata,
)
from voice_lab.plugins.metadata import PLUGIN_API_VERSION, PluginRegistrationResult


class PluginManager:
    def __init__(self, api_version=PLUGIN_API_VERSION, discovery_result=None):
        self.api_version = api_version
        self._plugins = {}
        self._effect_ids = set()
        self._registration_failures = []
        self._manifest_load_results = []
        self._registration_results = []
        self.discovery_result = discovery_result
        if discovery_result is None:
            self.register_builtin_plugins()
        else:
            self.register_discovered_plugins(discovery_result)

    def register_builtin_plugins(self):
        result = self.register_plugin(builtin_plugin_metadata())
        self._registration_results.append(result)
        return result

    def register_discovered_plugins(self, discovery_result):
        results = []
        for candidate in discovery_result.candidates:
            load_result = load_candidate_manifest(candidate)
            self._manifest_load_results.append(load_result)
            if not load_result.success:
                result = self._fail(
                    f"Plugin candidate load failed: {load_result.reason}",
                    plugin_id=getattr(candidate, "source", ""),
                )
                self._registration_results.append(result)
                results.append(result)
                continue
            result = self.register_plugin(load_result.metadata)
            self._registration_results.append(result)
            results.append(result)
        return tuple(results)

    def register_plugin(self, metadata):
        try:
            plugin_id = metadata.plugin_id
            if not metadata.compatibility.is_compatible(self.api_version):
                return self._fail(
                    metadata.compatibility.reason(self.api_version),
                    plugin_id=plugin_id,
                )
            if plugin_id in self._plugins:
                return self._fail(f"Duplicate plugin id: {plugin_id}", plugin_id=plugin_id)

            effect_ids = tuple(effect.effect_id for effect in metadata.effects)
            duplicate_effects = [effect_id for effect_id in effect_ids if effect_id in self._effect_ids]
            if duplicate_effects:
                return self._fail(
                    f"Duplicate effect id: {duplicate_effects[0]}",
                    plugin_id=plugin_id,
                )
        except Exception as exc:
            return self._fail(f"Invalid plugin metadata: {exc}")

        self._plugins[plugin_id] = metadata
        self._effect_ids.update(effect_ids)
        return PluginRegistrationResult.ok(metadata)

    def registered_plugins(self):
        return tuple(self._plugins.values())

    def registration_failures(self):
        return tuple(self._registration_failures)

    def manifest_load_results(self):
        return tuple(self._manifest_load_results)

    def registration_results(self):
        return tuple(self._registration_results)

    def load_default_effect_chain(self, effect_state, runtime_failure_handler=None, formant_lab=False):
        if formant_lab:
            from voice_lab.plugins.loader import builtin_plugin_metadata

            metadata = builtin_plugin_metadata(formant_lab=True)
        else:
            metadata = self._plugins["voicelab.builtin.effects"]
        return EffectChain(
            load_effects_from_metadata(metadata, effect_state),
            runtime_failure_handler=runtime_failure_handler,
        )

    def _fail(self, reason, plugin_id=""):
        result = PluginRegistrationResult.fail(reason, plugin_id=plugin_id)
        self._registration_failures.append(result)
        return result
