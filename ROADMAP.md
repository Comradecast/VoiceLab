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

## M5.5 - RC1 Lifecycle and Release Readiness

Status: PASS

Purpose: harden application lifecycle and document a repeatable RC1 operator and
release-preparation process without changing audio behavior, pitch DSP
configuration, frozen contracts, or architectural ownership.

### Scope

- Clean shutdown of audio streams, router/device handles, controller resources,
  effect backend buffers, telemetry flushing, and configuration flushing.
- Restart reliability after normal shutdown and recoverable startup failures.
- Focused lifecycle regression coverage without real microphone or VB-CABLE
  hardware.
- Concise RC1 runbook and final manual hardware smoke checklist.

### Out of Scope

- Signalsmith DSP changes.
- Installer creation, auto-update, dependency management, or startup auto-build.
- External plugin execution.
- Deferred singing-contour and soundboard playback-quality issues.

### Completed

- Lifecycle shutdown now releases audio routes/devices, effect backend buffers,
  telemetry/configuration flush hooks, controller state, and service references.
- Startup failure cleanup now closes partially constructed runtime resources and
  allows a later startup retry.
- UI close routes through the application lifecycle close callback.
- Added focused lifecycle regression coverage for service stop/restart,
  idempotent stop, partial startup cleanup, telemetry/config flushing, UI close,
  no duplicate engine/plugin initialization, and thread/resource cleanup with
  fake seams.
- Added `docs/rc1_runbook.md` with setup, native build, launch,
  troubleshooting, release-preparation, and manual RC1 hardware checklist.

### Completion Notes

- Automated M5.5 verification passed.
- Native rebuild succeeded after normal offscreen application close.
- Final M5.6 manual hardware acceptance completed the remaining M5.5
  release-readiness gate.
- Shutdown and relaunch testing passed after normal stop, after close, and after
  closing while processing remained active.
- Native rebuild-after-close verification passed; the rebuilt module copied to
  `voice_lab/effects/_signalsmith_pitch.cp313-win_amd64.pyd`, confirming
  VoiceLab released the native module after shutdown.
- No RC1 lifecycle blockers remain.

## M5.6 - Final Hardware Smoke and RC1 Freeze

Status: PASS

Purpose: complete final RC1 manual hardware acceptance and freeze the verified
repository state without changing implementation behavior, pitch DSP
configuration, frozen contracts, or architectural ownership.

### Scope

- Record final automated verification for M5.4/M5.5 and RC1 contract guards.
- Record final manual hardware startup, device, core audio, stability,
  shutdown, relaunch, and rebuild-after-close results.
- Reconcile known issues so remaining work is explicitly non-blocking.
- Recommend the RC1 release tag without creating or pushing it.

### Out of Scope

- Signalsmith DSP changes.
- UI telemetry visibility implementation.
- External plugin execution.
- Installer, packaging, dependency management, or auto-update behavior.

### Completed

- Final automated verification confirmed Signalsmith `available=True`, backend
  `signalsmith`, backend status `active`, telemetry readability, and no fallback
  active.
- Final manual startup/device acceptance passed for application launch,
  microphone input, virtual microphone availability, monitor availability, and
  starting processing. Backend telemetry/fallback visibility through the UI was
  not tested because telemetry is not currently visible in the application; the
  CLI/automated telemetry path confirmed the backend state.
- Final manual core audio acceptance passed for dry voice, Gain, Lowpass, Robot,
  pitch `+4`, pitch `-4`, preset switching while processing, live pitch changes
  while processing, soundboard playback, virtual microphone processed output,
  and monitor processed output.
- Virtual microphone and monitor processed-output paths were confirmed through
  Steam voice test.
- Subjective pitch/audio acceptance passed: metallic tail absent,
  flutter/choppiness absent, and latency acceptable.
- The former soundboard two-stage behavior was not reproduced during final RC1
  hardware acceptance.
- Runtime stability passed for a 30-minute session with no crash, stream loss,
  runaway/increasing latency, progressive distortion, repeated dropout, frozen
  UI, or lost command response.
- Shutdown and relaunch acceptance passed: stop processing, close after
  stopping, terminal prompt return, relaunch, start processing after relaunch,
  close while processing remained active, terminal prompt return after active
  close, no native-module lock after close, and native Signalsmith rebuild after
  close.

### Completion Notes

- Tested environment: Windows 11, Python 3.13.3, AMD64 / 64-bit,
  pybind11 3.0.4, Signalsmith native module active.
- Established pitch guidance: `+/-4` semitones is the recommended normal range,
  `+/-8` semitones is usable but obviously processed, and `+/-12` semitones is
  intentionally extreme.
- Missing UI telemetry visibility is deferred usability work and is not an RC1
  failure because backend telemetry remains readable through the automated path.
- Remaining DSP debt is limited to non-blocking sung pitch-contour flattening.
- No RC1 blockers were found.

## M6 - Product Refinement

Status: In Progress

Purpose: improve the operator experience after the RC1 freeze while preserving
the proven audio behavior, Signalsmith DSP configuration, frozen contracts,
lifecycle ownership, and plugin boundaries. M6 is not public packaging work.

## M6.1 - Operator Status and Telemetry Visibility

Status: PASS

Purpose: make VoiceLab's current runtime state understandable from the
application itself without giving the UI or telemetry new runtime authority.

### Scope

- Resolve the M6.1 telemetry visibility decision into primary operator UI,
  diagnostic detail, and event/log-only visibility levels.
- Add a narrow application-layer operator-status projection derived from
  existing runtime state and telemetry.
- Render compact PySide6 status fields for processing, routing, pitch backend,
  estimated pitch DSP latency, command/status message, warning/error state, and
  secondary diagnostics.
- Refresh status on the Qt UI thread at low frequency.
- Keep Start Processing and Stop Processing enabled state aligned with the
  authoritative application status projection.

### Out of Scope

- Signalsmith DSP changes.
- Pitch buffering changes.
- Device-routing ownership changes.
- Persistent logging.
- Installer, executable packaging, auto-update, public release, or runtime
  native compilation.
- External plugin execution.
- Broad UI redesign.

### Completed

- `ApplicationService.operator_status()` now returns a read-only operator view
  derived from telemetry snapshot, current application processing state, and
  active route state.
- The UI window now uses `VoiceLab` as the product name and exposes compact
  status labels for processing, routing, pitch, estimated pitch DSP latency,
  status, warnings, and diagnostic backend details.
- Pitch status distinguishes off/bypassed zero semitones, Signalsmith ready,
  active Signalsmith, Pedalboard fallback, no usable backend, and pitch effect
  runtime failure.
- Route status distinguishes routes stopped, virtual mic active, virtual mic and
  monitor active, and route error without inspecting device handles.
- Status refresh uses a 500 ms Qt timer and catches refresh failures without
  affecting processing.
- Added focused M6.1 tests for operator projection semantics and offscreen UI
  refresh/control behavior.

### Completion Notes

- Primary operator information: processing state, route state, pitch/backend
  state, fallback/error warning, current pitch amount, estimated pitch DSP
  latency, command/status message, and latest actionable warning/error.
- Diagnostic-only information: backend identifiers/status, fallback flag,
  current semitones, block/interval sizes, latency frames, and latest backend
  error.
- Event/log-only information: plugin discovery event history, verbose event
  metadata, processor identity, buffer counters, reset counters, and future
  persistent logs.
- Telemetry remains passive; the UI obtains state only through
  `ApplicationService`.
- M6.1 live operator-facing acceptance passed after hardware/UI testing. The
  tester confirmed startup, running, stopped, pitch, route, command, close,
  relaunch, and audio-regression behavior. No false fallback, route, monitor, or
  backend warnings appeared in normal operation.
- Observed accepted limitations: unavailable-device failure behavior was not
  tested, and no new 30-minute soak was run because no instability appeared.

## M6.2 - Operator UX Micro-Polish

Status: PASS

Purpose: correct concrete usability issues observed during M6.1 live acceptance
without redesigning the UI or changing runtime behavior.

### Scope

- Clarify wording for the monitor enable/disable control.
- Preserve the existing application-service command path and routing behavior.

### Out of Scope

- Broad visual redesign.
- DSP, routing, lifecycle, plugin, telemetry-authority, packaging, or logging
  changes.

### Completed

- Renamed the monitor checkbox from "Monitor myself through speakers/headphones"
  to "Enable monitor output" so disabling monitor is discoverable by unchecking
  the control.
- Renamed the adjacent device label to "Monitor output device".
- Added focused offscreen UI coverage for the monitor toggle wording.

### Completion Notes

- This was the only concrete M6.2 correction justified by Phase A observations.
- No runtime behavior changed.

## M6.3 - Safe Device Failure Recovery

Status: PASS

Purpose: make device-related startup and routing failures understandable and
recoverable without changing Router/AudioIO ownership or silently changing the
selected devices.

### Scope

- Normalize device and route startup failures into stable categories and route
  roles.
- Translate normalized failures into concise operator messages and suggested
  actions at the application layer.
- Keep backend/OS exception details in telemetry metadata instead of primary UI
  text.
- Ensure failed starts leave processing not running, routes inactive, Start
  enabled, Stop disabled, and retry possible.
- Ensure Router closes partially opened resources if startup fails.

### Out of Scope

- DSP, Signalsmith, pitch-buffering, backend-selection, audio-contract, plugin,
  lifecycle-ownership, configuration-format, packaging, installer, auto-update,
  external plugin, persistent logging, or hot-plug monitoring changes.
- Silent device fallback, automatic replacement device selection, or automatic
  retry loops.

### Failure-Path Inventory

- Missing input selection, missing virtual output selection, and monitor enabled
  with no monitor selection are detected before Router startup by
  `ApplicationService`.
- Stale selected input, output, or monitor IDs are detected by `Router`
  validation as `device_not_found`.
- Unsupported channel/role configuration is detected by `Router` validation as
  `unsupported_configuration`.
- Monitor output open failures are wrapped by `AudioIO` as
  `device_open_failed` for `monitor_output`.
- Duplex stream open failures are wrapped as `device_open_failed` for the
  general route because PortAudio does not always identify whether input or
  output caused the failure.
- Typed lower-layer/fake failures for input, virtual output, or monitor open are
  preserved and translated by `ApplicationService`.
- Unknown startup failures use safe generic wording.
- Partial startup failures now trigger immediate Router cleanup.
- Stop after failed start is safe and reports "Already stopped".
- Retry after correcting a condition is safe; successful start clears the
  primary warning while telemetry retains failure history.

### Failure Categories

- `missing_selection`
- `device_not_found`
- `device_open_failed`
- `unsupported_configuration`
- `route_startup_failed`
- `partial_start_cleanup_failed`
- `unknown_device_error`

Roles:

- `input`
- `virtual_output`
- `monitor_output`
- `route`

### Completion Notes

- User-visible messages are concise and actionable. They do not expose raw
  tracebacks or backend object representations.
- Technical details are retained in `CommandResult.metadata["failure"]`,
  `active_start_failure` telemetry metadata, and the bounded telemetry event
  history.
- Routine informational commands do not erase an unresolved startup warning.
- A new start attempt may replace a prior startup warning; successful start
  clears the primary warning.
- Monitoring remains optional but explicit: monitor failure does not silently
  disable monitoring or select another device.
- Device refresh was deferred. The current device list is loaded at UI startup;
  users may correct selections already present or relaunch after external
  hot-plug changes. No automatic refresh or hot-plug monitoring was added.
- Automated M6.3 recovery coverage passed for selection failures,
  device-not-found cases, open failures, unsupported configuration, unknown
  startup failure, telemetry detail retention, cleanup, retry, no automatic
  device replacement, monitor semantics, polling after failure, and offscreen UI
  close after failure.
- Manual M6.3 hardware acceptance passed for unavailable monitor recovery,
  unavailable microphone recovery, stale-device-after-relaunch recovery, and
  unavailable virtual microphone recovery.
- Corrected retries succeeded without restarting VoiceLab after monitor,
  microphone, stale selection, and virtual microphone recovery paths.
- Manual M6.3 acceptance confirmed no silent device substitution occurred.
- Exclusive/open failure was not manually reproduced; automated generic-open
  failure coverage passed.
- Normal regression passed for startup, virtual mic, monitor, pitch `+4`, pitch
  `-4`, soundboard, stop, close, relaunch, metallic tail absent, flutter absent,
  and acceptable latency.

## M6.4 - Manual Device Refresh and Selection Integrity

Status: PASS

Purpose: allow the operator to explicitly refresh available audio devices after
connecting, disconnecting, enabling, or disabling hardware without restarting
VoiceLab and without automatic hot-plug behavior.

### Scope

- Add an explicit `Refresh Devices` UI action near the device selectors.
- Route refresh through `ApplicationService`; keep operating-system device
  enumeration owned by `AudioIO`.
- Introduce a narrow immutable application-facing device descriptor for UI
  choices and selection identity.
- Preserve selections only when the same device identity can be matched safely.
- Clear disappeared or ambiguous selections and require explicit operator
  replacement before processing starts.
- Preserve monitor-enabled state, effect parameters, presets, and soundboard
  state during refresh.
- Keep refresh disabled while processing is starting, running, or stopping, and
  reject invalid refresh commands at the service boundary.

### Out of Scope

- Automatic hot-plug polling, Windows device event listeners, background device
  watcher threads, automatic fallback, default substitution, automatic retry,
  stopping active audio to refresh, persistent hardware profiles, friendly
  aliases, packaging, installer, auto-update, DSP changes, external plugin
  execution, and broad UI redesign.

### Device Identity Policy

- Selection preservation first accepts the same numeric index only when the
  device identity still matches.
- If the index changed, a unique exact identity match may preserve the
  selection at the new index.
- Identity is the exact device name, host API identifier, input/output channel
  capabilities, and default sample rate.
- Duplicate exact identities are ambiguous unless the same index still matches.
- Numeric index alone and display name alone are never sufficient.

### Refresh Availability Policy

- `stopped`: enabled.
- `failed`: enabled.
- `starting`: disabled and rejected by `ApplicationService`.
- `running`: disabled and rejected by `ApplicationService`.
- `stopping`: disabled and rejected by `ApplicationService`.

### Completion Notes

- Successful refresh updates all three selector lists atomically and reports
  missing roles in concise command text.
- Enumeration failure preserves the old selector model and selections, records
  technical detail in telemetry, and allows another refresh attempt.
- Refresh does not clear an unresolved M6.3 startup failure; successful Start
  remains the authoritative event that clears startup failure state.
- No silent replacement device is selected during refresh.
- Automated M6.4 coverage passed for refresh availability, service rejection,
  role filtering, selection preservation, ambiguity handling, missing-selection
  reporting, enumeration failure, retry after enumeration failure, start-failure
  interaction, UI signal blocking, status polling, prohibited imports, and
  offscreen UI refresh/close.
- Manual M6.4 live hardware acceptance passed. Baseline refresh preserved the
  same actual devices, newly connected input/output devices appeared without
  relaunching, unselected removed devices disappeared without disturbing current
  selections, and removed selected microphone, monitor, and virtual microphone
  selections were cleared.
- Manual M6.4 acceptance confirmed no replacement device was silently selected,
  monitor enabled state remained explicit, VB-CABLE reappeared after
  restoration and manual refresh, Refresh Devices was disabled while processing,
  and Refresh Devices became available again after stopping and after failed
  starts.
- Manual M6.4 recovery and corrected retry succeeded, and identity preservation
  behaved correctly during observed device-list changes.
- Duplicate ambiguity and forced enumeration failure remained NOT TESTED because
  they were not safely reproducible.
- Normal M6.4 regression passed for normal microphone, virtual mic, monitor,
  monitor-disabled operation, dry voice, Gain, Lowpass, Robot, pitch `0`,
  pitch `+4`, pitch `-4`, presets, soundboard, Start, Stop, close, and relaunch.
- Subjective M6.4 audio acceptance passed: metallic tail absent,
  flutter/choppiness absent, and latency acceptable.

## M6.5 - Persistent Operator Settings

Status: PASS

Purpose: restore the operator's normal VoiceLab setup across launches without
persisting transient runtime state or relying on hard-coded numeric audio device
IDs.

### Scope

- Add a separate versioned project-root `settings.json` for stable operator
  preferences.
- Persist selected microphone identity, selected virtual microphone output
  identity, selected monitor output identity, monitor enabled state, monitor
  volume, soundboard volume, and last explicitly selected preset.
- Resolve saved devices through the M6.4 exact identity policy.
- Restore matching devices only when the stored identity resolves uniquely.
- Keep VoiceLab launching stopped.
- Flush dirty settings through the existing lifecycle configuration-save stage.

### Out of Scope

- Automatic audio start, automatic processing restoration, device fallback,
  approximate device matching, automatic default substitution, background device
  watchers, persistent telemetry logs, session-log export, AppData migration,
  installer, packaging, auto-update, profiles, friendly hardware aliases, DSP
  changes, external plugin execution, and broad UI redesign.

### Settings Schema

- `schema_version`: `1`.
- `devices.input`, `devices.virtual_output`, and `devices.monitor_output` store
  exact device identity fields: name, host API, input channel count, output
  channel count, and default sample rate.
- `monitor_enabled`: boolean.
- `monitor_volume`: finite number from `0.0` to `1.0`.
- `soundboard_volume`: finite number from `0.0` to `1.0`.
- `selected_preset`: optional preset name.

The numeric PortAudio device index is not stored as persistent identity.

### Completion Notes

- Configuration owns settings schema, validation, loading, dirty state, atomic
  saving, and lifecycle flush.
- `ApplicationService` exposes restored preferences, records explicit operator
  changes, resolves preferred identities against current device enumeration,
  and records passive telemetry events for settings load/save and restoration
  warnings.
- The UI reads restored preferences only through `ApplicationService`; it does
  not read or write JSON and does not import `AudioIO`, `Router`, or
  `sounddevice`.
- First launch no longer silently selects hard-coded numeric default device IDs
  or the first available devices. Device selectors remain unselected until the
  operator chooses devices or saved identities resolve uniquely.
- Hard-coded `DEFAULT_INPUT_ID`, `DEFAULT_OUTPUT_ID`, and `DEFAULT_MONITOR_ID`
  remain only as legacy development constants and are not authoritative
  persistence.
- Missing or ambiguous saved devices leave the corresponding active selector
  empty, preserve the preferred identity for later refresh, show concise
  guidance, and never silently select a replacement.
- If a preferred identity later reappears and resolves uniquely during manual
  refresh, it may be restored without starting processing.
- Stored monitor enabled state is restored exactly; if the saved monitor device
  is missing, monitoring remains enabled and M6.3 start validation requires the
  operator to select a monitor or disable monitoring.
- The last explicitly selected preset is restored through the canonical preset
  command path. Arbitrary unsaved effect slider states are not persisted.
- Missing, malformed, empty, wrong-root, invalid-field, and unsupported-schema
  settings files do not prevent launch. Unsupported future schemas are not
  interpreted as version `1`.
- Settings writes use a same-directory temporary file, flush, close, and atomic
  replacement strategy; failed saves leave the prior file intact where the
  operating system honors replacement atomicity.
- Automated M6.5 coverage passed for file load/save/corruption handling,
  validation, atomic-save behavior, device identity restoration, no silent
  substitution, first-launch unselected behavior, startup-stopped guard, dirty
  shutdown flush, save-failure telemetry, UI restore, M6.4 refresh cooperation,
  and prohibited UI persistence/import paths.
- Manual M6.5 live operator-settings acceptance passed with no implementation
  correction required.
- First launch without `settings.json` opened normally, all device selectors
  began unselected, processing did not start automatically, the UI remained
  responsive, and no unrelated first-listed devices were silently selected.
- Persisted settings restored after restart: selected microphone, VB-CABLE
  virtual output, monitor output, monitor-enabled state, monitor volume,
  soundboard volume, selected preset, and the selected preset's parameters.
- VoiceLab always relaunched stopped. Normal processing worked after explicit
  Start.
- Monitor-disabled state persisted, and virtual-microphone-only processing
  worked.
- Unavailable saved devices were not silently replaced; unavailable roles
  remained unselected and guidance was understandable.
- Explicit replacement worked, and reconnect plus `Refresh Devices` recovery
  restored the preferred identity according to policy.
- Final M6.5 audio regression passed for microphone, virtual mic, monitor,
  effects, pitch `0`, pitch `+4`, pitch `-4`, presets, soundboard, Start,
  Stop, close, and relaunch.
- Subjective M6.5 audio acceptance passed: metallic tail absent,
  flutter/choppiness absent, and latency acceptable.
- Optional destructive/error scenarios remained NOT TESTED because automated
  coverage passed.

## M7 - User-Facing Product Development

Status: In Progress

Purpose: turn the proven technical voice-processing foundation into product
workflows that normal operators can understand without changing frozen audio,
plugin, routing, lifecycle, or device-recovery contracts.

## M7.0 - Voice Character Experience

Status: PASS

Purpose: make the primary workflow voice-character selection, optional
character strength adjustment, explicit effects bypass, reset, and custom voice
management while preserving the existing validated effect chain and
application-service command boundary.

### Scope

- Add an immutable built-in voice character catalog.
- Add a pure character-strength resolver over existing preset/effect parameter
  scales.
- Expose character selection, strength, bypass, reset, active voice state, and
  custom voice commands through `ApplicationService`.
- Keep advanced technical controls available but collapsed by default.
- Preserve saved custom presets as custom voices.
- Persist selected built-in character and character strength as optional
  backward-compatible schema-version-1 settings fields.
- Add engine-owned user effects bypass that skips voice effects without
  stopping routing or mutating effect-chain runtime-failure state.

### Out of Scope

- Formant shifting, new DSP plugins, high-pass or band-pass filtering,
  telephone-style voices, identity-style voices, soundboard redesign, custom
  icons, import/export, hotkey assignment UI, diagnostics export, packaging,
  installer, auto-update, external plugin execution, and broad visual redesign.

### Built-In Character Catalog

Initial character targets use the existing preset/UI scale:

| Character | Gain | Robot | Lowpass | Pitch |
| --- | ---: | ---: | ---: | ---: |
| Natural | 10 | 0 | 4000 | 0 |
| Deep | 9 | 0 | 2200 | -4 |
| Heavy Bass | 10 | 0 | 1800 | -6 |
| Higher | 9 | 0 | 6500 | 4 |
| Robot | 12 | 100 | 4000 | 0 |
| Radio | 16 | 15 | 2300 | 0 |
| Muffled | 12 | 0 | 900 | 0 |

Compatibility aliases preserve existing built-in preset names where applicable:
`Natural`, `Deep Voice`, `High Voice`, `Robot`, `Radio`, and `Muffled`.
`Clean` and `Deep-ish` remain available through saved/custom voice selection.

### Completion Notes

- Character definitions live outside the UI and expose stable identifiers,
  display names, descriptions, target parameters, strength applicability, and
  compatibility aliases.
- Character targets validate through the existing preset/effect validation
  path before reaching the engine.
- Character strength is `0` to `100`; `0%` resolves to Natural, `100%` resolves
  to the character target, gain/robot/pitch interpolate linearly, and lowpass
  interpolates logarithmically to an integer frequency.
- Natural disables the strength control because strength has no audible meaning
  for the neutral baseline.
- Active voice state distinguishes built-in character, saved custom preset,
  unsaved custom advanced edits, and bypassed output.
- Manual Gain, Pitch, Robot, or Lowpass edits mark the active voice as
  `Custom - Unsaved`. Programmatic updates from character selection, strength,
  preset selection, reset, or startup restoration do not.
- Saved custom voices continue to use the existing preset file format and
  validation. Built-in character names and compatibility aliases cannot be
  overwritten or deleted through the custom voice commands.
- User bypass is owned by `ApplicationService` for commands/status and
  `AudioEngine` for execution. It skips the voice effect chain without stopping
  routing, disabling monitor output, changing selected devices, mutating
  effect-chain disabled sets, or clearing runtime-failure bypass state.
- Bypass defaults off on every launch and is not persisted.
- Reset Voice selects Natural, restores neutral parameters, sets default
  strength, turns bypass off, and preserves devices, monitor state, volumes,
  soundboard state, routing state, and processing state.
- Automated M7.0 coverage passed for catalog validation, character aliases,
  strength interpolation, service state transitions, custom-state behavior,
  built-in protection, bypass frame-contract behavior, bypass/runtime-failure
  separation, settings compatibility, offscreen UI character controls,
  advanced-control collapse/expand behavior, prohibited UI imports, and M5.4
  through M6.5 regression suites.
- Live launch after M7.0 exposed a Windows geometry warning caused by the main
  window minimum height exceeding the usable monitor area. The content now
  scrolls inside the window so the default launch height fits, and the corrected
  launch no longer emits the warning in live use.
- Manual M7.0 live voice-character acceptance passed after the sizing correction.
- Product presentation passed: character controls were clear, active state was
  visible, Advanced Controls began collapsed, technical diagnostics did not
  dominate normal use, and the layout fit the screen with no clipped or
  unreachable controls.
- Character listening passed for Natural, Deep, Heavy Bass, Higher, Robot,
  Radio, and Muffled. Natural remained a clean baseline; Deep was useful for
  ordinary transformed speech; Heavy Bass was distinct and stronger; Higher was
  usable; Robot was clearly robotic; Radio and Muffled were meaningfully
  different; all remained intelligible enough for their intended purpose.
- Strength sweeps passed for Deep, Robot, Higher, and Heavy Bass. `0%` matched
  Natural, intermediate values progressed meaningfully, `100%` reached the
  target character, labels stayed synchronized, and no stream restart,
  metallic tail, flutter/choppiness, or cumulative latency increase was
  observed.
- Bypass passed while running for pitch and Robot characters. Microphone audio
  became dry, routing stayed active, virtual mic and monitor remained active,
  selected character and strength were retained, and disabling bypass restored
  the prior effect state.
- Soundboard during bypass passed: soundboard playback remained active while
  microphone effects were bypassed.
- Reset Voice passed while running: Natural was restored, bypass turned off,
  strength returned to policy default, devices, monitor state, monitor volume,
  soundboard volume, routing, and processing state were preserved.
- Advanced controls and custom voices passed: controls began collapsed,
  expanded values matched selected character and strength, manual edits became
  `Custom - Unsaved`, selecting a character restored canonical values, custom
  save/select/delete worked, built-in names were protected, and no built-in
  character was modified.
- Persistence passed: selected character, strength, devices, monitor state,
  volumes, and saved custom voice availability restored according to policy;
  VoiceLab relaunched stopped; bypass relaunched off; Advanced Controls began
  collapsed.
- Device and final regression passed: Refresh Devices behavior, failed-start
  recovery, corrected retry, no silent replacement, microphone, virtual mic,
  monitor, monitor-disabled operation, Start, Stop, close, relaunch,
  soundboard, available hotkeys, Signalsmith active status, metallic-tail
  absence, flutter/choppiness absence, and acceptable latency all passed.
- No voice-character parameter tuning or naming change was required.
- Accepted limitations: formant-based, EQ/filter-specific, telephone-style, and
  identity-style voices remain deferred outside M7.0.
- Not tested: destructive device-enumeration failure and unconfigured hotkey
  paths where not safely reproducible or not configured.

## M7.1 - Live Audio Meters and Clipping Indication

Status: PROVISIONAL

Purpose: give the operator passive visual feedback that VoiceLab is receiving
microphone audio, producing processed voice audio, sending audio to the virtual
microphone route, and approaching overload, without letting meters control
audio, routing, effects, devices, character state, or settings.

### Scope

- Add immutable `LevelReading` and `AudioLevelSnapshot` application-facing
  contracts.
- Measure raw microphone input after capture, processed voice after the engine,
  final virtual-microphone output after mixer soundboard combination, and
  monitor output only when that routed bus is active.
- Use conventional block RMS and peak dBFS math with a `-60 dBFS` display
  floor and `0 dBFS` ceiling.
- Use `Overload` terminology for observed high level at or above `-1 dBFS`.
- Retain only the latest snapshot with a sequence number and capture timestamp.
- Rate-limit callback publication to 25 snapshots per second.
- Poll meters from the UI every 50 ms.
- Keep peak hold, decay, overload latch, stale-state detection, and no-signal
  state in the non-real-time presentation layer.
- Surface passive meter metadata through telemetry snapshots and operator
  diagnostics without per-block events.

### Out of Scope

- Automatic gain control, input gain, compression, limiting, noise gate,
  equalizer, device volume control, waveform display, spectrum analyzer,
  recording, persistent meter history, exported meter logs, LUFS measurement,
  calibration, microphone sensitivity setup, new DSP plugins, and broad UI
  redesign.

### Completion Notes

- Raw microphone audio first enters VoiceLab-owned code in
  `Router.main_callback`, then `Capture.capture_block` creates the capture
  `AudioFrame`.
- Processed voice is measured from the `AudioEngine.process_voice` return value
  before mixer soundboard combination.
- Output is measured from `OutputBuses.main_bus`, the final bus written to the
  virtual microphone route.
- Monitor is measured from `OutputBuses.monitor_bus` only when monitor routing
  is enabled; otherwise monitor reading is explicitly unavailable.
- Soundboard-only playback appears on Output and not on Microphone Input or
  Processed Voice.
- During Bypass Effects, Processed Voice measures the actual bypassed voice
  path and may match Microphone Input.
- Stopped, failed, and starting states reset or invalidate readings so stale
  running activity is not presented as current.
- The audio callback performs bounded latest-slot publication only. It does not
  emit Qt signals, query devices, write files, write settings, or record
  per-block telemetry events.
- UI uses only `ApplicationService.audio_level_snapshot()` for meter data.
- Known limitations: block-level readings are operational feedback rather than
  laboratory-grade measurement; values are not calibrated SPL or LUFS; display
  polling may miss transients; post-clamp output readings cannot reveal exact
  pre-clamp magnitude; silence detection does not prove device disconnection.
- Automated M7.1 coverage passed for meter math, immutable snapshot behavior,
  bounded retention, stage attribution, soundboard attribution, bypass truth,
  service passivity, operator diagnostics, UI meter construction and timer
  shutdown, display mapping, overload latch, prohibited imports, callback
  guards, and audio identity preservation.
- Manual M7.1 live meter hardware acceptance remains pending.
