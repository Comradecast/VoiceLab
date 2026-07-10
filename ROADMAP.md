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
