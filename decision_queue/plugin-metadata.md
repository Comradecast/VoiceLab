# Plugin Metadata

Architecture Stable

## Priority

Medium

## Status

Resolved

## Blocks

Nothing

## Decision Owner

Chief Engineer

## Needed By

Plugin implementation

## Question

What are the exact plugin search locations and metadata format?

## Decision

M4.1 through M4.6 define and freeze the RC1 plugin metadata, discovery, manifest loading, registration, compatibility, lifecycle, and telemetry contracts.

Selected structure:

- `PluginMetadata`
- `Compatibility`
- `EffectDescriptor`
- `PluginRegistrationResult`

Required plugin metadata:

- stable plugin id
- display name
- plugin version
- provider
- description
- plugin type
- enabled-by-default state
- VoiceLab plugin API compatibility
- provided effect descriptors

Required effect metadata:

- stable effect id
- display name
- category
- factory id
- effect factory reference
- optional parameter metadata

Identifier format:

- lowercase slug or dotted identifier
- starts with a lowercase letter
- may contain lowercase letters, digits, dots, underscores, and hyphens as separators
- no display-name-derived aliases in M4.1

Version and compatibility approach:

- versions use `major.minor.patch`
- the current VoiceLab plugin API version is `1.0.0`
- compatibility declares minimum API version and optional maximum API version
- incompatible plugins are rejected before effect construction

Invalid metadata behavior:

- invalid metadata produces a structured registration failure
- incompatible metadata produces a structured registration failure
- duplicate plugin ids are rejected
- duplicate effect ids are rejected
- registration is atomic and must not partially register invalid plugins

Discovery and manifest treatment:

- discovery locations are deterministic: built-in source, application-local `plugins/`, then `~/VoiceLab/plugins`
- external candidates are `plugin.json` files or directories containing `plugin.json`
- discovery is startup-only and non-recursive
- manifests use schema version `1`
- manifest implementation references are declarative identifiers only
- unknown manifest fields are tolerated and preserved in metadata diagnostics

Built-in treatment:

- Robot, Lowpass, and Gain are represented by one built-in plugin manifest: `voicelab.builtin.effects`
- built-in effect order remains Robot -> Lowpass -> Gain

RC1 freeze:

- plugin metadata/discovery/loading/registration contracts are frozen for RC1
- built-in plugins are the only executable plugin path
- external manifest plugins are metadata-only in RC1
- external execution, factory resolution, trust policy, sandboxing, dependency management, and enable/disable policy remain deferred
