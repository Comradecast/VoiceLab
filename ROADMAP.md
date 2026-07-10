# VoiceLab Roadmap

This is the canonical roadmap document.

Roadmap entries must reference the contracts in `ARCHITECTURE.md`, respect `NON_NEGOTIABLES.md`, and link to `DECISION_QUEUE.md` entries when roadmap work depends on unresolved architecture decisions.

## M0 - Project Constitution

Status: Approved

M0 establishes the project governance foundation.

### Completed

- Project Constitution
- Architecture
- Governance
- Decision Queue
- Roadmap
- Engineering Process

### Pending

- Implementation

## M1 - Repository Skeleton

Purpose: make the repository structure match the architecture.

This milestone is not functionality work. It must not introduce DSP, new behavior, new product features, or architectural redesign.

The goal is structural alignment only: move existing code and assets toward the ownership boundaries defined in `ARCHITECTURE.md`.

### Target Structure

- `main.py`
- `voice_lab/app/`
- `voice_lab/engine/`
- `voice_lab/io/`
- `voice_lab/mixer/`
- `voice_lab/effects/`
- `voice_lab/plugins/`
- `voice_lab/telemetry/`
- `voice_lab/config/`
- `voice_lab/controllers/`
- `voice_lab/ui/`
- `voice_lab/tests/`
- `docs/`

### Constraints

- Existing behavior must not change.
- Existing runnable entry points must remain runnable or have compatibility shims.
- Moves must preserve importability.
- Responsibility ownership must match `ARCHITECTURE.md`.
- No subsystem may gain side-door access during the move.
- Tests may be added or relocated only to verify unchanged behavior.
- Any ambiguous ownership discovered during the move must create or update a Decision Queue page instead of being guessed.

### Done When

- The repository has the target package structure.
- Existing source files have a clear architectural home.
- Compatibility shims or updated imports keep current behavior intact.
- Documentation and repository layout agree.
- No new DSP or feature behavior has been introduced.

## M2 - Boundary Stabilization

Status: Complete

Purpose: stabilize subsystem ownership boundaries so the implementation matches the contracts in `ARCHITECTURE.md`.

M2 focused on moving responsibilities to their documented owners without changing runtime behavior or adding product features.

### Completed

- M2.1 Application Command Boundary
- M2.2 Audio I/O Isolation
- M2.3 Mixer Boundary
- M2.4 Router Boundary
- M2.5 Capture Boundary
- M2.6 Minimal Telemetry Plumbing
- M2.7 Effect Plugin Boundary
- M2.8 Effect Chain Boundary
- M2.9 Effect Chain Telemetry
- M2.10 Configuration Validation Boundary
- M2.11 Configuration Service Boundary
- M2.12 Controller Command Boundary
- M2.13 Application Lifecycle Boundary

### Completion Notes

- UI and controllers route runtime changes through `ApplicationService`.
- Audio I/O, capture, router, mixer, engine, effect chain, plugin loading, telemetry, configuration, and lifecycle responsibilities have explicit owners.
- Compatibility shims remain for legacy entry points.
- Remaining architecture questions stay tracked in `DECISION_QUEUE.md`.

## Next Phase Options

M3 AudioFrame / AudioContext has been selected as the next path.

Unselected future options:

- M3 Plugin metadata/discovery
- M3 Configuration hardening

## M3 - AudioFrame / AudioContext

Status: In Progress

Purpose: formalize the audio data contract before expanding runtime context, plugin metadata, or configuration behavior.

### Completed

- M3.1 AudioFrame Foundation
- M3.2 AudioContext Foundation
- M3.3 Output Bus Frame Contract
- M3.4 Auxiliary Source Contract
- M3.5 Audio Contract Hardening

### M3.1 Completion Notes

- `AudioFrame` exists as the minimal core audio data contract.
- Capture produces `AudioFrame` instances for microphone input blocks.
- AudioEngine accepts `AudioFrame` at its processing boundary and returns processed `AudioFrame` output.
- Mixer accepts processed `AudioFrame` input while preserving existing output buses.
- Existing DSP, UI behavior, routing, telemetry, hotkeys, and soundboard behavior remain unchanged.

### M3.2 Completion Notes

- `AudioContext` exists as the minimal runtime processing metadata contract.
- `AudioFrame` owns samples and carries an optional `AudioContext` reference.
- Capture creates context metadata for microphone input blocks.
- AudioEngine passes context to EffectChain while preserving existing effect behavior.
- Effects are not required to consume context yet.
- Existing DSP, UI behavior, routing, telemetry, hotkeys, and soundboard behavior remain unchanged.

### M3.3 Completion Notes

- `OutputBuses` now groups `AudioFrame` instances for `main_bus` and `monitor_bus`.
- Mixer creates AudioFrame-backed output buses while preserving existing mixing behavior.
- Router consumes AudioFrame-backed buses and keeps destination mapping unchanged.
- AudioIO owns final sample extraction into PortAudio output buffers.
- Existing DSP, UI behavior, routing decisions, telemetry, hotkeys, presets, and soundboard behavior remain unchanged.

### M3.4 Completion Notes

- `AuxiliaryAudio` exists as the minimal contract for non-microphone audio entering the mixer.
- Soundboard asset loading returns `AuxiliaryAudio` instead of a bare sample array.
- Mixer exposes `queue_auxiliary` as the primary auxiliary-source queueing API.
- Raw arrays remain supported only through the legacy `queue_sound` compatibility shim.
- Existing DSP, UI behavior, routing decisions, telemetry, hotkeys, presets, and soundboard behavior remain unchanged.

### M3.5 Completion Notes

- `AudioFrame` now validates sample shape, frame count, channel count, dtype, sample format, timestamp, block index, and attached context agreement.
- `AudioContext` now validates sample format, timestamp, block index, and processing-stage vocabulary.
- `AuxiliaryAudio` now enforces the same sample shape, frame count, channel count, dtype, and sample-format invariants as `AudioFrame`.
- `OutputBuses` now requires `AudioFrame` instances for both buses.
- Raw-array compatibility paths remain available but are explicitly deprecated and are not used by canonical runtime flow.
- CommandResult remains outside the audio-contract freeze candidate.

## M4 - Plugin Metadata / Discovery

Status: Complete

Purpose: formalize plugin identity, compatibility, discovery, manifest loading, registration, lifecycle telemetry, and freeze the RC1 plugin boundary before any external execution work.

### Completed

- M4.1 Plugin Metadata Contract
- M4.2 Plugin Discovery Boundary
- M4.3 Plugin Manifest Loading
- M4.4 Plugin Load Telemetry
- M4.5 Plugin Boundary Audit
- M4.6 Plugin Architecture Freeze

### M4.1 Completion Notes

- `PluginMetadata`, `Compatibility`, `EffectDescriptor`, and `PluginRegistrationResult` define the in-process plugin metadata contract.
- Plugin identifiers and effect identifiers are validated with stable lowercase slug/dotted format.
- Plugin versions and VoiceLab plugin API compatibility use `major.minor.patch` format.
- `PluginManager` owns registration, compatibility evaluation, plugin-id uniqueness, effect-id uniqueness, atomic failure behavior, and read-only metadata exposure.
- Built-in Robot, Lowpass, and Gain effects register through one built-in plugin manifest while preserving Robot -> Lowpass -> Gain order.
- External filesystem discovery remains out of scope for M4.1.

### M4.2 Completion Notes

- `PluginDiscovery` owns startup-only plugin candidate discovery.
- Discovery locations are deterministic: built-in source, project-root `plugins/`, then `~/VoiceLab/plugins`.
- External candidates are non-recursive `plugin.json` files or directories containing `plugin.json`.
- Discovery returns structured candidates and failures without constructing effects, registering plugins, or executing arbitrary plugin code.
- ApplicationLifecycle invokes discovery during startup before plugin validation/registration.
- PluginManager remains the owner of metadata registration and uniqueness checks.

### M4.3 Completion Notes

- `PluginLoader` converts declarative `plugin.json` manifests into validated `PluginMetadata`.
- Manifest schema version `1` is supported; unsupported manifest versions fail with structured load results.
- Unknown manifest fields are tolerated and preserved in metadata diagnostics.
- Implementation references are validated as declarative identifiers and are not imported or executed.
- PluginManager remains the owner of compatibility checks, identity collisions, and registration.
- Built-in plugin behavior and Robot -> Lowpass -> Gain order remain unchanged.

### M4.4 Completion Notes

- Plugin startup telemetry records discovery, manifest load, compatibility, registration, and startup summary outcomes.
- `TelemetrySnapshot` exposes passive plugin startup status without becoming authoritative plugin state.
- Plugin telemetry distinguishes discovered, metadata loaded, registered metadata, executable, and active states.
- External manifest plugins remain metadata-only and non-executable.
- Telemetry is recorded at lifecycle orchestration and does not control plugin behavior.

### M4.5 Completion Notes

- Plugin metadata, discovery, manifest loading, registration, compatibility checking, lifecycle integration, and telemetry were audited as stable for RC1.
- Discovery remains candidate-only and does not execute code.
- Manifest loading remains declarative and does not import implementation references.
- Built-in plugins remain the only executable plugin path.
- External plugin execution was explicitly deferred until after RC1 unless a separate architecture decision changes that scope.

### M4.6 Completion Notes

- M4 plugin metadata/discovery/loading/registration contracts are frozen for RC1.
- External manifest plugins may be discovered, loaded as metadata, registered as metadata, and reported through telemetry, but they are not executable in RC1.
- The following work is deferred and must not be implemented casually:
  - external plugin execution
  - factory resolution
  - trust policy
  - sandboxing or process isolation
  - dependency management
  - plugin enable/disable policy

## Next Phase Options After M4

M5.0 Pitch Transformation Demonstrator has been selected as the next product-capability path.

## M5 - Product Capability Demonstrator

Status: In Progress

Purpose: validate VoiceLab's real-time voice-transformation direction before RC1 hardening by adding one meaningful voice-changing capability through the existing plugin, configuration, command, telemetry, and UI boundaries.

### Completed

- M5.0 Pitch Transformation Demonstrator

### M5.0 Completion Notes

- Added a built-in `pitch_shift` effect before Robot, Lowpass, and Gain in the deterministic default chain.
- Pitch is centrally validated in semitones from `-12` to `+12`, with `0` as neutral.
- Presets can store and restore pitch, and the default demonstration set includes Natural, Deep Voice, and High Voice without silently replacing user-created presets.
- The UI exposes a minimal Pitch slider and current value using the existing command path.
- Telemetry exposes current pitch semitones and existing EffectChain status reports enabled, disabled, runtime-bypassed, and failed effects.
- `AudioEngine` still does not import or construct concrete effects directly.
- The pitch effect owns a bounded streaming adapter with a 2048-frame processing window, deterministic priming silence, exact-size callback output, and reset/re-prime behavior on pitch changes.
- Diagnostics confirmed `RobotEffect` receives zero and is not responsible for pitch coloration; exact digital silence now flushes pitch adapter buffers and settles to zero in offline sine, speech-like, and impulse tests.
- Latency diagnostics selected 2048 frames over 8192 after live testing found 8192-frame monitor delay distracting. At 48 kHz with 1024-frame callbacks, the selected window has about 42.67 ms processing-window duration and about 21.33 ms first-output buffering delay.
- Pitch buffering latency is exposed through telemetry metadata as `pitch_buffer_status`.
- The installed Pedalboard backend did not produce usable continuous `reset=False` streaming output in offline checks, so M5.0 remains provisional pending manual audio quality validation.

### Pending

- Manual hardware test with microphone, virtual mic, and monitor output.
- Manual confirmation that 2048-frame pitch quality is acceptable and that monitor delay is no longer distracting.
- RC1 decision on whether Pedalboard quality/latency is acceptable or a streaming-capable pitch backend is required.

## M5.2 - Streaming Pitch Backend Evaluation

Status: Complete

Purpose: evaluate replacement backends after live testing showed Pedalboard cannot satisfy both continuity and latency for VoiceLab's primary real-time pitch effect.

### Completed

- Compared Signalsmith Stretch, Rubber Band, SoundTouch, and PSOLA against VoiceLab's real-time effect/plugin boundary.
- Confirmed Pedalboard should remain provisional or fallback-only for pitch.
- Recommended Signalsmith Stretch as the first replacement prototype target.
- Recorded the backend decision in `decision_queue/streaming-pitch-backend.md`.

### M5.2 Completion Notes

- Signalsmith Stretch is the preferred open-source target because it is MIT licensed, C++11/header-oriented, supports block processing with explicit input/output sizes, exposes input/output latency, and is documented as tested with MSVC on Windows.
- Rubber Band is technically credible and mature, including a live block-by-block pitch API, but GPL/commercial licensing and heavier packaging make it a second choice.
- SoundTouch is portable and LGPL, but its documented stream latency is around 100 ms and quality expectations are weaker for this use case.
- PSOLA is promising for later speech-specific voice transformation, but requires robust pitch tracking and a custom streaming implementation, making it too risky for the immediate backend swap.

### Pending

- M5.3 minimal Signalsmith Stretch prototype behind `PitchShiftEffect`.

## M5.3 - Signalsmith Stretch Prototype

Status: PASS

Purpose: build a minimal native-backed Signalsmith Stretch prototype behind the existing `PitchShiftEffect` boundary without changing higher-level VoiceLab contracts.

### Completed

- Vendored minimal Signalsmith Stretch and Signalsmith Linear MIT-licensed source under `third_party/`.
- Added a small VoiceLab-specific Python backend wrapper for an optional native `voice_lab.effects._signalsmith_pitch` module.
- Added pybind11 C++ wrapper source for `SignalsmithPitchBackend`.
- Added a build script and backend notes.
- Integrated `PitchShiftEffect` to prefer Signalsmith when the native module is available and fall back explicitly to Pedalboard when unavailable.
- Preserved existing AudioEngine, Mixer, Router, AudioIO, UI, frozen audio contracts, and plugin metadata/discovery contracts.

### M5.3 Completion Notes

- The native Signalsmith backend was built and loaded successfully on Windows with Python 3.13.
- Live hardware testing passed: metallic/electrical tail is gone, flutter/choppiness is gone, and `+/-4` semitones sounds close to the intended product direction.
- `+/-8` semitones is usable but audibly pitch-modulated; `+/-12` semitones is intentionally extreme.
- Signalsmith Stretch is the canonical real-time pitch backend. Pedalboard remains fallback/diagnostic only.
- Pitch telemetry reports `signalsmith` when the native backend is active.

### Pending

- M5.4 RC1 hardening and product stabilization.

## M5.4 - Native Pitch Runtime Hardening

Status: PASS

Purpose: harden the existing Signalsmith runtime path for RC1 without changing
the proven audio behavior.

### Scope

- Make the native backend build repeatable from the repository root.
- Keep runtime startup free of automatic native compilation.
- Expose explicit pitch backend status and fallback state through pitch telemetry.
- Preserve Signalsmith as the canonical real-time backend and Pedalboard as
  fallback/diagnostic only.
- Add focused regression coverage for backend state, fallback, lifecycle,
  semitone changes, bypass, and telemetry readability.

### Out of Scope

- Changing Signalsmith DSP configuration to address singing contour artifacts.
- Installer, auto-update, dependency management, or cross-platform packaging.
- External plugin execution or frozen plugin/audio contract changes.

### Completed

- Hardened the Signalsmith build script around repository-root execution,
  active-interpreter use, deterministic pybind11 include resolution, canonical
  package output, duplicate native binary checks, and locked-binary diagnostics.
- Confirmed runtime startup does not compile the native extension.
- Added explicit pitch backend telemetry for active Signalsmith, Pedalboard
  fallback, missing/incompatible/import-failed native module states, no-backend
  failure behavior, and zero-semitone bypass.
- Preserved Signalsmith DSP behavior and kept backend selection inside
  `PitchShiftEffect`.
- Added focused regression coverage for backend state, fallback, no-backend
  behavior, zero and `+/-4` semitone configuration, bypass, lifecycle restart,
  live semitone/preset changes, shutdown with buffered pitch state, and telemetry
  readability.

### Completion Notes

- Native Signalsmith availability was verified as active in the current
  workspace.
- Native Signalsmith rebuild verification completed after running VoiceLab
  processes released the Windows `.pyd` file lock: the first rebuild succeeded,
  and a second consecutive rebuild also succeeded without manual cleanup.
- The compiled native module was copied to the canonical
  `voice_lab/effects/` package location.
- Manual hardware audio quality remains out of scope for automated M5.4
  verification; the prior M5.3 live hardware pass remains the RC1 audio-quality
  basis.

Candidate directions:

- M5 RC1 hardening
- M5 Configuration hardening
- M5 Product stabilization and known-issue triage
