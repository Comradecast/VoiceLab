__all__ = (
    "BUILTIN_PLUGIN_SOURCE",
    "PLUGIN_MANIFEST_NAME",
    "Compatibility",
    "DiscoveryFailure",
    "DiscoveryLocation",
    "EffectDescriptor",
    "MANIFEST_VERSION",
    "ManifestLoadResult",
    "PLUGIN_API_VERSION",
    "PluginCandidate",
    "PluginDiscovery",
    "PluginDiscoveryResult",
    "PluginManager",
    "PluginMetadata",
    "PluginRegistrationResult",
    "default_discovery_locations",
    "load_candidate_manifest",
    "plugin_metadata_from_manifest",
)


def __getattr__(name):
    if name in {
        "BUILTIN_PLUGIN_SOURCE",
        "PLUGIN_MANIFEST_NAME",
        "DiscoveryFailure",
        "DiscoveryLocation",
        "PluginCandidate",
        "PluginDiscovery",
        "PluginDiscoveryResult",
        "default_discovery_locations",
    }:
        from voice_lab.plugins import discovery

        return getattr(discovery, name)
    if name == "PluginManager":
        from voice_lab.plugins.manager import PluginManager

        return PluginManager
    if name in {
        "MANIFEST_VERSION",
        "ManifestLoadResult",
        "load_candidate_manifest",
        "plugin_metadata_from_manifest",
    }:
        from voice_lab.plugins import loader

        return getattr(loader, name)
    if name in {
        "PLUGIN_API_VERSION",
        "Compatibility",
        "EffectDescriptor",
        "PluginMetadata",
        "PluginRegistrationResult",
    }:
        from voice_lab.plugins import metadata

        return getattr(metadata, name)
    raise AttributeError(f"module 'voice_lab.plugins' has no attribute {name!r}")
