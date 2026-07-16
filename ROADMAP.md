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

Status: PASS

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
- Manual M7.1 live meter hardware acceptance passed with three remaining
  hardware-acceptance coverage gaps: Input overload, Processed/output
  overload, and Failed Start and retry were NOT TESTED.
- Live acceptance passed for baseline speech meter response, meter decay,
  sustained silence/no-signal behavior, quiet speech, character switching,
  character strength response, Bypass Effects attribution, soundboard-only
  attribution, voice plus soundboard attribution, monitor-disabled operation,
  Stop clearing or invalidating active meter state, repeated Start/Stop, device
  refresh behavior, window scrolling and layout, close while running, and
  relaunch behavior.
- Live final audio regression passed: metallic tail remained absent, flutter
  remained absent, latency remained acceptable, and meters made no audible
  difference.
- Output-meter limitation accepted: Output observes the existing post-clamp bus
  after the mixer clamp to `0.95`; it cannot display exact pre-clamp magnitude
  beyond that clamp.
- Hardware overload coverage is incomplete because Input overload and
  Processed/output overload were NOT TESTED.
- Hardware failed-start meter coverage is incomplete because Failed Start and
  retry was NOT TESTED.

## M7.2 - Custom Voice Management and Operator Polish

Status: PASS

Purpose: make saved custom voices safer and clearer for normal operators by
distinguishing built-in and custom voices, adding rename and duplicate
operations, requiring confirmation for delete and overwrite, and protecting
`Custom - Unsaved` advanced edits from silent discard.

### Scope

- Keep built-in voice characters immutable and unchanged.
- Keep custom voices in the existing `presets.json` mapping and keep selected
  voice state in existing operator settings.
- Add application-service operations for classified voice listing, custom voice
  name validation, rename, duplicate, delete, and explicit overwrite.
- Add non-selectable built-in and custom sections to the primary voice selector.
- Add Rename Custom Voice and Duplicate Custom Voice actions next to existing
  save/delete custom voice actions.
- Require delete confirmation for saved custom voices.
- Require overwrite confirmation before replacing an existing custom voice.
- Prompt before selecting another voice or Reset Voice would discard
  `Custom - Unsaved` advanced edits.
- Keep bypass separate from voice identity.

### Out of Scope

- DSP changes, character target changes, pitch configuration changes, meter
  changes, routing changes, device behavior changes, soundboard changes,
  packaging, import/export, and broad visual redesign.

### Completion Notes

- Built-in character definitions remain owned by
  `voice_lab.config.voice_characters`.
- Custom voice persistence remains owned by `ConfigurationService` and the
  existing preset file shape: a mapping of custom voice name to validated
  `gain`, `robot`, `lowpass`, and `pitch` values.
- Existing `presets.json` and `settings.json` files load without migration.
- Custom voice names are trimmed, empty names are rejected, built-in names and
  `Custom - Unsaved` state names are reserved, and custom-name conflicts are
  detected case-insensitively for new operations.
- Rename writes one updated preset mapping, removes the old name, updates the
  active selection when applicable, and persists through relaunch.
- Duplicate preserves the source voice, copies validated parameters to the new
  name, selects the duplicate, and persists through relaunch.
- Delete is available only for saved custom voices, requires confirmation in
  the UI, deletes exactly the selected custom voice, and resolves an active
  deleted custom voice to Natural without changing devices, routing, volumes,
  processing state, bypass state, soundboard behavior, or audio code.
- Saving over an existing custom voice requires explicit UI confirmation; a
  cancel leaves the existing custom voice unchanged.
- Programmatic UI refresh and startup restoration do not create unsaved prompts.
- Automated M7.2 coverage passed for custom voice classification, rename,
  duplicate, delete, overwrite authorization, reserved and conflicting name
  validation, persistence compatibility, unsaved discard/cancel behavior,
  bypass identity separation, grouped selector behavior, action enabled states,
  UI cancel paths, and prohibited UI imports.
- Manual M7.2 live UI acceptance is complete with documented limits.
- Luke confirmed that every M7.2 scenario he could practically test passed.
  No live product failure was observed.
- Live PASS results were recorded for built-in/custom selector distinction,
  custom voice save, rename, duplicate, delete confirmation, overwrite
  confirmation, unsaved-change Cancel and Discard behavior, relaunch
  persistence, application regression behavior, and final audio regression.
- Final audio regression where tested: metallic tail remained absent, flutter
  remained absent, latency remained acceptable.
- Untested scenarios are not represented as passed. Any manual edge scenario
  not practically executed remains NOT TESTED.
- The pre-acceptance audit identified automated-test/evidence coverage gaps,
  not known product failures. These remain non-blocking automated coverage
  debt:
  rename empty-string rejection; exact em dash `Custom — Unsaved` reserved-name
  rejection; rename conflict unchanged-data assertion; unrelated custom voice
  unchanged during overwrite; advanced manual change direct `Custom - Unsaved`
  pre-reset assertion; cancelled Reset preserving unsaved selection and
  parameters; confirmed selector discard executing exactly once; programmatic
  selector rebuild false-prompt prevention; startup restoration false-prompt
  condition; direct disabled section-header assertion; and
  Rename/Duplicate/Delete disabled state for `Custom - Unsaved`.

## M8.0 - Input Processing Foundation

Status: PASS

Purpose: add a configurable, default-disabled real-time input-processing
foundation for microphone clarity, background-noise control, dynamic-range
control, and voice-path peak protection without changing existing voice
characters, routing, device behavior, meters, soundboard behavior, or
Signalsmith pitch configuration.

### Scope

- Add global operator settings for High-Pass Filter, Noise Gate, Compressor,
  and voice-path Limiter.
- Keep all four processors disabled by default so legacy `settings.json` and
  `presets.json` files load without migration and preserve the pre-M8 voice
  path when processors remain disabled.
- Keep M8.0 input-processing settings out of custom voice presets.
- Preserve the existing character-effect order: Pitch Shift, Robot, Lowpass,
  Gain.
- Use the final voice path: High-Pass, Noise Gate, Compressor, Pitch Shift,
  Robot, Lowpass, Gain, Limiter.
- Keep AudioEngine as the owner of voice processing, Mixer as the only owner of
  combining voice and soundboard audio, Router as the owner of route delivery,
  AudioIO as the owner of sounddevice, and UI communication through
  ApplicationService.
- Preserve Bypass Effects as the single bypass path. Bypass remains inside
  active routing, does not stop audio, does not change routes, and does not
  erase input-processing settings.

### Processor Controls

- High-Pass Filter: Enabled, Cutoff 40 Hz through 200 Hz; default 80 Hz and
  disabled.
- Noise Gate: Enabled, Threshold -70 dBFS through -20 dBFS, Release 40 ms
  through 1000 ms; defaults -45 dBFS, 180 ms, disabled. Internally this is a
  conservative downward expander with fixed 8 ms attack, 50 ms hold, 2.5:1
  ratio, and -36 dB attenuation floor.
- Compressor: Enabled, Threshold -40 dBFS through 0 dBFS, Ratio 1.0:1 through
  10.0:1, Attack 1 ms through 100 ms, Release 20 ms through 1000 ms, Makeup
  Gain 0 dB through +12 dB; defaults -18 dBFS, 3.0:1, 10 ms, 150 ms, 0 dB,
  disabled.
- Limiter: Enabled, Ceiling -12 dBFS through -0.5 dBFS, Release 20 ms through
  500 ms; defaults -1 dBFS, 80 ms, disabled.

### Completion Notes

- M8.0 processors are built-in effects with stable plugin metadata and
  deterministic chain order. The order is not dependent on filesystem
  discovery.
- Runtime parameter changes update effect configuration through
  ApplicationService and AudioEngine without restarting streams, reopening
  devices, writing files from the callback, or moving ownership into Router or
  Mixer.
- Processor state is bounded to filter/envelope scalars; no unbounded
  histories, FFT processing, callback queues, callback Qt activity, callback
  settings writes, callback device queries, or repetitive callback logging were
  added.
- Microphone Input meters remain pre-processing, Processed Voice meters remain
  post input-processing, character processing, and limiter, and Output meters
  remain the existing post-mix post-clamp bus.
- The M8.0 Limiter acts only on the processed voice path before Mixer. Mixer
  still owns final bus clipping, soundboard audio is not limited by M8.0, and
  Output still observes the existing post-clamp final bus.
- Automated verification covers processor contracts, high-pass attenuation,
  gate attenuation and release, compressor ratio and smoothing, limiter ceiling,
  chain order, bypass, settings compatibility, presets compatibility,
  UI/service boundaries, callback/source guards, and bounded repeated
  processing.
- Live M8.0 launch found acceptance issues before PASS: the single-column
  scrolling layout was confusing, Input Processing looked like a global
  checkbox, and the operator could not tell whether High-Pass, Noise Gate,
  Compressor, or Limiter were acting.
- The correction replaces the long single-column layout with a persistent
  transport area and five top-level tabs: Voice, Input Processing, Routing,
  Soundboard, and Diagnostics. Start, Stop, Bypass Effects, processing state,
  route state, and active voice remain visible outside the tabs.
- Input Processing is now a navigation tab, not a global enable control. Each
  processor panel has its own Enabled control, parameter values and units, an
  OFF/ENABLED state, and passive activity feedback.
- Processor-activity feedback is latest-state only and bounded: High-Pass
  reports enabled state and cutoff, Noise Gate reports Open/Reducing and gain
  reduction, Compressor reports gain reduction, and Limiter reports gain
  reduction plus ceiling-hit indication.
- Deterministic activation probes confirmed measurable DSP response at
  diagnostic settings: High-Pass attenuated 50 Hz to about 6.2% RMS while
  preserving 1 kHz at about 99.9%; Noise Gate reduced a below-threshold block
  to about 3.2% RMS while passing an above-threshold block unchanged;
  Compressor reduced a loud block by about 22.5 dB while leaving quiet material
  unchanged; Limiter held an over-ceiling block to the -12 dBFS ceiling while
  leaving safe material unchanged.
- M8.0 live hardware and audible acceptance passed after the layout and
  visibility correction. Confirmed live PASS results: revised tabbed layout
  and navigation, persistent transport controls, processors-disabled baseline
  transparency, existing voice behavior remains acceptable, High-Pass audible
  activation, High-Pass useful low-frequency effect, Noise Gate audible
  activation, Noise Gate useful practical settings, Compressor audible
  activation, Compressor expected practical behavior, Limiter audible
  activation, Limiter usefulness, combined normal processing chain, Bypass
  Effects behavior and recovery, Reset Voice/Input Processing separation,
  routing and normal application behavior, processor activity visibility, no
  reported metallic tail, no reported flutter, acceptable latency, and no
  observed DSP activation defect.
- Practical starting settings accepted as useful: High-Pass enabled at 80-100
  Hz; Noise Gate around -45 dBFS with about 200 ms release; Compressor
  threshold -18 dBFS, ratio 3:1, attack 10 ms, release 150 ms, makeup gain
  0 to +2 dB; Limiter ceiling -1 dBFS and release 80 ms. Extreme diagnostic
  settings remain activation evidence only, not normal recommended defaults.
- The 15-minute combined-processing stability run was NOT TESTED and was
  waived by Luke as non-blocking. No instability was observed during practical
  testing, the omitted timed run is not represented as completed, no known
  product failure remains, and prior lifecycle acceptance plus fixed-size
  bounded processor-state evidence support treating the omitted run as
  non-blocking.

## M8.1 - Real-Time Formant Backend Prototype

Status: PASS

Purpose: prove whether the existing local Signalsmith backend can support
real-time formant shifting in a bounded streaming path before any user-facing
character, preset, persistence, or production-chain integration is attempted.

### Scope

- Add an explicit `main.py --formant-lab` launch mode for isolated prototype
  evaluation.
- Preserve normal launch behavior and the production chain:
  High-Pass, Noise Gate, Compressor, Pitch Shift, Robot, Lowpass, Gain,
  Limiter.
- In formant-lab mode only, replace the Pitch Shift stage with an
  Experimental Pitch/Formant stage in the same chain position.
- Extend the local native Signalsmith wrapper with `set_formant_semitones`
  and `set_formant_factor`, backed by the local
  `signalsmith-stretch.h` `setFormantSemitones` and `setFormantFactor` API.
- Keep prototype pitch/formant settings session-only. No settings schema,
  preset schema, custom voice persistence, built-in character targets, routing,
  devices, meters, soundboard behavior, M8.0 input processing behavior, or
  Signalsmith production pitch configuration were changed.
- Add a guarded Formant Lab UI panel only when launched with `--formant-lab`.
- Use an immutable whole-configuration runtime snapshot for Formant Lab
  parameters. ApplicationService validates a complete snapshot outside the
  callback, AudioEngine replaces the active snapshot as one reference, and the
  Experimental Pitch/Formant effect reads one snapshot reference at the start
  of each process block.

### Completion Notes

- Local API evidence exists in
  `third_party/signalsmith-stretch/signalsmith-stretch.h`: the library exposes
  `setFormantFactor`, `setFormantSemitones`, and `setFormantBase`. The M8.1
  prototype uses formant semitones/factor on the same native streaming
  instance as pitch shifting.
- Positive formant semitones map to `2 ** (semitones / 12)`, following the
  local Signalsmith README example where a factor above 1 shifts formants up.
- Automated focused tests confirm the native and Python wrapper methods are
  exposed, normal production chain order is unchanged, formant-lab chain order
  is isolated, normal service launch does not expose Formant Lab, invalid
  formant values are rejected, service reset returns session values to neutral,
  and deterministic vowel-like probes preserve F0 while moving the spectral
  envelope down/up for negative/positive formant settings.
- Automated smoke evidence confirmed the prototype produces finite output,
  reports Signalsmith backend telemetry, and reports the expected current
  formant factor and latency metadata.
- The M8.1 runtime hardening correction removes the pre-live audit's mixed
  scalar-update risk. The callback path uses no lock, queue, history, stream
  restart, device reopen, route interruption, settings write, preset write, or
  native backend reconstruction for ordinary Formant Lab parameter changes.
- Luke's live evaluation confirmed the backend is technically viable and that
  neutral operation is usable. Subtle formant moves can be useful, with the
  plausible natural-character range around +/-0.5 to +/-2 semitones.
  Approximately +/-3 already commonly sounded odd, and larger standalone
  values generally did not sound natural.
- Live evaluation also confirmed that pitch plus formant alone is insufficient
  for intended production character targeting: pitch +3 / formant +1 sounded
  like a man attempting to imitate a woman. The backend remains viable as an
  M8.2 character-transformation component, but raw standalone formant controls
  are not sufficient production character targets.
- Final M8.1 live hardware/audio smoke passed. Confirmed PASS results: normal
  launch unchanged, normal mode launches stopped, prototype launches stopped,
  neutral pitch 0 / formant 0 sound, subtle formant around +/-1 audible and
  usable, live pitch/formant parameter changes, Prototype A/B Bypass preserves
  values, Stop/Start recovery, close while processing, prototype relaunch,
  normal relaunch unchanged, no crash, no severe burst, and acceptable latency.
- Parameter-change artifact: severe clicks or bursts were NONE; a minor
  transition artifact was OBSERVED when changing formant rapidly toward one
  extreme or the other. The output can briefly sound as though prototype bypass
  is active before formant processing settles and becomes audible again. This
  is MINOR / NON-BLOCKING: it was not persistent, did not crash processing,
  did not alter settings, did not create growing latency, was associated with
  extreme live parameter changes, and can be avoided by staying away from
  extreme settings. No correction is required before beginning the next epic;
  this remains known DSP transition debt.
- Accepted technical conclusion: Signalsmith provides genuine independent
  formant control; formant-only shifts preserve fundamental pitch
  substantially; pitch and formant run in one native Signalsmith processing
  stage; formant processing adds no measured latency beyond the accepted
  production pitch path; normal production mode remains isolated; immutable
  whole-parameter snapshot replacement prevents mixed per-block pitch/formant
  configurations; no callback lock, queue, history, stream restart, device
  reopen, or persistence change was introduced; native lifecycle and `.pyd`
  release/rename/relaunch checks passed.
- Perceptual conclusion: the plausible natural formant range is approximately
  +/-0.5 to +/-2 semitones, approximately +/-3 begins to sound unnatural, and
  larger shifts are primarily experimental or special-effect territory. Pitch
  and formant alone are insufficient for accurate intended-character
  transformation; pitch +3 / formant +1 still sounded like a man attempting to
  imitate a woman.
- M8.1 closes with formant shifting accepted as one bounded component of the
  future adaptive/target-based character-transformation engine. Production
  integration of raw formant values into existing characters remains deferred,
  and the next epic must target complete character transformation rather than
  exposing more isolated offsets.

## M9.0 - Passive Source Voice Analysis Lab

Status: PASS

Purpose: add an explicit, target-neutral `main.py --voice-analysis-lab`
prototype mode that passively measures the operator's raw microphone signal as
bounded acoustic data for future target-based character transformation.

### Scope

- Normal launch remains unchanged and does not display Source Analysis.
- Normal production chain remains unchanged:
  High-Pass, Noise Gate, Compressor, Pitch Shift, Robot, Lowpass, Gain,
  Limiter, then Mixer.
- Formant Lab chain remains unchanged and still replaces only Pitch Shift with
  Experimental Pitch/Formant in `--formant-lab` mode.
- The analyzer is not a DSP plugin and does not alter audio samples, DSP
  parameters, devices, routes, meters, soundboard behavior, settings schema,
  presets schema, characters, or Signalsmith configuration.
- The analyzer observes the raw `Capture.capture_block` microphone frame in
  `Router.main_callback`, before AudioEngine processing, Mixer, soundboard,
  monitor routing, and virtual-output routing.
- Router performs only bounded publication to a passive analysis tap. Pitch,
  spectral, resonance, and profile calculations run outside the callback.
- UI communicates only through `ApplicationService`; it does not import NumPy,
  SciPy, analyzer internals, AudioEngine, Router, or DSP modules.

### Architecture

- Raw Capture -> passive `SourceAnalysisTap` -> non-callback
  `SourceVoiceAnalyzer` worker -> immutable `VoiceAnalysisSnapshot` ->
  `ApplicationService` -> UI polling.
- `SourceAnalysisTap` is a cadence-capped one-slot mailbox. Newer accepted raw
  frames replace stale pending analysis input, dropped replacements are
  counted, and cadence-skipped frames are counted separately.
- Callback work added in analysis mode is one raw-frame publication call plus a
  copy only when the cadence gate accepts the frame. No callback FFT, F0,
  profile, Qt access, file I/O, settings write, device query, analyzer wait,
  blocking queue put, unbounded queue, unbounded history, or repetitive logging
  was added.
- The worker owns all mutable analysis state and retains a fixed rolling
  profile window of at most 240 readings: 20 Hz for 12 seconds.
- Application-facing snapshots are frozen scalar dataclasses:
  `VoiceAnalysisReading`, `VoiceSourceProfile`, `VoiceAnalysisStatus`, and
  `VoiceAnalysisSnapshot`. No arrays are exposed to ApplicationService or UI.

### Measurements

- F0 uses deterministic normalized autocorrelation over a Hann-windowed
  rolling analysis window with local-peak selection, supported practical range
  60 Hz through 500 Hz, confidence threshold 0.42 for current voicing, and
  0.50 for profile inclusion. Pure dominant tones above the supported range
  are rejected instead of being reported as stable subharmonics.
- Rolling pitch profile uses reliable voiced frames only. It reports median
  F0, 10th and 90th percentile F0, Hz span, semitone span, voiced duration,
  voiced-frame ratio, and readiness.
- Profile readiness requires at least 2.0 seconds of reliable voiced readings.
  Once ready, the rolling profile remains ready while at least 1.0 second of
  retained high-confidence voiced evidence remains. Silence and unvoiced frames
  are excluded from F0 statistics and do not immediately erase the last
  profile; Reset Source Analysis clears the profile.
- Spectral analysis uses a Hann window and real FFT outside the callback.
  Ratios are normalized to total 80 Hz through 10 kHz speech-region energy and
  truncate bands at Nyquist.
- Band definitions: chest/low 80-300 Hz, low-mid 300-900 Hz, presence
  2-5 kHz, brightness 5-8 kHz, sibilance 5-10 kHz.
- Spectral tilt is a dB energy-ratio metric:
  `10 * log10((2-8 kHz energy) / (80-900 Hz energy))`.
- Resonance/formant output is approximate and validity-gated. M9.0 uses
  smoothed spectral-envelope peak estimates for F1, F2, and F3 on suitable
  voiced frames; noisy consonants, silence, and unreliable frames report
  unavailable estimates rather than invented precision.
- Reliability states distinguish collecting, ready, insufficient level,
  insufficient voiced speech, stale, analyzer unavailable, and analyzer
  failure.

### Status

- Automated implementation, regression verification, and Luke's final live
  source-analysis acceptance are complete.
- Final live M9.0 PASS results: normal launch unchanged, Source Analysis
  absent from normal mode, Voice Analysis Lab launch, application launches
  stopped, Start activates analysis, Stop/reset behavior, repeated Start/Stop,
  close/relaunch behavior, audio transparency, no added audible latency,
  metallic tail absent, flutter absent, no crackle or new audible block
  boundaries, normal speech F0 behavior appears plausible, lower and higher
  voice changes are reflected, quiet/loud speech behavior appears plausible,
  sustained vowels collect stable data, rapid speech continues updating,
  silence/unvoiced behavior appears correct, confidence behavior appears
  plausible, rolling profile collects and reaches useful state, median and
  pitch-range measurements appear plausible, spectral descriptors respond
  plausibly, analyzed/skipped/dropped status behaves normally, no UI freezing,
  no analyzer failure, and data collection appears fully functional in
  practical use.
- M9.0 creates no source-profile file and exports no profile. Analysis values
  are intentionally session-only, the bounded source profile exists only in
  memory, nothing is written to `settings.json` or `presets.json`, and Reset,
  Stop/restart, and relaunch begin fresh transient analysis state according to
  the implemented lifecycle. No file was expected from Luke during acceptance.
- Future target-character processing will consume the live in-memory profile
  directly. Persistent analysis export remains deferred diagnostics scope.
- Accepted technical conclusions: raw microphone analysis occurs before DSP and
  Mixer; analysis does not alter audio; callback publication uses a stable
  owned copy; analysis runs outside the callback; mailbox capacity remains one
  frame; rolling profile remains bounded to 240 scalar readings; the F0
  estimator is accepted for practical source profiling; spectral energy ratios
  are accepted as comparative descriptors; `spectral_tilt_db` is an
  energy-ratio index, not a fitted dB-per-octave slope; F1/F2/F3 estimates are
  weak descriptors only and are not approved as direct automatic control
  inputs; and no identity or gender classification is performed.
- The analyzer is accepted as the source-profile foundation for feminine,
  masculine, deep-masculine, giant, and other target profiles.
- Known non-blocking debt: real-hardware close-while-processing was not
  separately isolated as a dedicated test beyond Luke's practical live use;
  lock-free mailbox diagnostic counters may rarely undercount or lose a
  pending frame during a thread interleaving; approximate resonance estimates
  remain weak descriptors; and lower-sample-rate Nyquist truncation lacks a
  dedicated focused test. These are not known product failures and do not block
  M9.0 acceptance.
- The lab is target-neutral. It measures acoustic properties only and does not
  classify the operator as male, female, masculine, feminine, young, old, or
  any other identity category.
- The next epic is the target-based character-transformation engine. The first
  target work must support both feminine and deep-masculine transformation
  directions.

## M9.1 - Adaptive Target Engine Core

Status: PASS

Purpose: add the target-neutral planning core that relates the accepted M9.0
source profile to an explicit target voice profile and produces an immutable
transformation plan for future character work.

### Scope

- Add an explicit `main.py --target-planner-lab` launch mode.
- Preserve normal launch, `--formant-lab`, and `--voice-analysis-lab`
  behavior.
- Target Planner Lab launches stopped, enables the accepted passive source
  analyzer, shows Source Analysis plus Target Planner UI, and keeps all target
  values session-only.
- Normal production chain remains unchanged:
  High-Pass, Noise Gate, Compressor, Pitch Shift, Robot, Lowpass, Gain,
  Limiter.
- Formant Lab chain remains unchanged and still replaces only Pitch Shift with
  Experimental Pitch/Formant.
- The planner is not a DSP plugin. It does not alter audio samples, DSP
  settings, routes, devices, meters, soundboard behavior, characters,
  `settings.json`, `presets.json`, built-in voice targets, or Signalsmith
  configuration.
- No planner work runs in the audio callback, and no planner queue, stream
  restart, device reopen, persistence write, or callback lock was added.

### Architecture

- Core relationship:
  `Source Voice Profile + Target Voice Profile + Character Strength =
  Immutable Transformation Plan`.
- `TargetVoiceProfile` is a frozen scalar contract with identity/version,
  pitch goals, bounded formant hint, spectral goals/limits, texture goals,
  M8.0-compatible dynamics recommendations, and safety/capability metadata.
- `TransformationPlan` is a frozen scalar contract with plan identity, state,
  pitch, formant, spectral, texture, dynamics, required capabilities, and
  warnings.
- `TransformationPlanner.plan(...)` is pure and stateless. It has no dependency
  on `AudioEngine`, `EffectChain`, `Router`, DSP effects, settings, presets,
  devices, callbacks, queues, or history.
- Character Strength is normalized from UI `0..100` to planner `0..1`. `0%`
  produces a fully neutral applied plan with no required future transformation
  capability; `100%` produces the full bounded target. Intermediate strengths
  are monotonic.
- M9.0 source evidence used directly for planning: median F0, lower/upper F0,
  pitch span, voiced duration, profile readiness, aggregate reliability,
  chest/low-mid/presence/brightness/sibilance ratios, and spectral tilt
  energy-ratio index.
- Approximate F1/F2/F3 resonance estimates remain weak descriptors only and do
  not directly determine automatic formant shift.
- The planner is target-neutral. It does not classify source or target identity,
  gender, age, or quality, and does not implement production feminine,
  masculine, deep-masculine, giant, or other character identities.

### Planning Rules

- Pitch center request is `12 * log2(target_median_f0 / source_median_f0)`,
  scaled by strength, then clamped to the target pitch limit.
- Pitch-range scale is derived from `target_span / source_span`, interpolated
  from neutral by strength, and clamped to target range limits.
- Formant recommendation is target-intent based:
  `target.nominal_formant_shift_st * strength`, clamped to the target maximum
  and restrained to a natural planning limit of `+/-2` semitones.
- Spectral band recommendations use
  `10 * log10(target_ratio / source_ratio)`, scaled by strength and clamped;
  missing or zero source evidence degrades only that control.
- Spectral tilt uses target tilt index minus source tilt index, scaled by
  strength and clamped.
- De-essing, texture, and dynamics are deterministic recommendations only. No
  de-esser or dynamics mutation was added.
- Dynamics recommendations use M8.0 ranges; compressor neutral is `1:1` with
  `0 dB` makeup, and limiter recommendations are target data only.
- Capabilities describe processors required for the current applied plan, not
  every latent target requirement. Latent target requirements are gated by
  active character strength, while requested target intent remains inspectable.

### Completion Notes

- Added diagnostic target profiles for manual inspection: Diagnostic Neutral,
  Higher / Brighter Reference, and Lower / Weightier Reference. These are
  planning references, not production characters.
- Target Planner UI states `Experimental - Planning Only - Audio Is Not
  Modified`, exposes source summary, target controls, character strength,
  calculated plan, capability/warning output, reference-load actions, and
  reset. It intentionally has no Apply, Preview, Save, or Export action.
- Automated verification covers immutable contracts, validation, plan states,
  pitch formulas, pitch-range behavior, formant intent isolation from F1/F2/F3,
  spectral and tilt formulas, de-ess/texture/dynamics recommendations,
  capability reporting, lab-mode isolation, normal/formant chain isolation,
  settings/presets compatibility, UI exposure, callback/source guards, and
  audio transparency.
- Final M9.1 live Target Planner Lab acceptance passed after the zero-strength
  planner-neutrality correction. Confirmed PASS results: Target Planner Lab
  launch, Source Analysis tab present, Target Planner tab present, launches
  stopped, normal launch unchanged, Formant Lab unchanged, Voice Analysis Lab
  unchanged, normal and prototype effect chains unchanged, planner outside DSP
  and callback, source collection, collecting state, ready source producing a
  ready plan, Stop/reset behavior, source-profile rebuild updating plans, no
  planner failure, and no analyzer failure.
- Zero-strength neutrality passed for Diagnostic Neutral, Higher / Brighter,
  and Lower / Weightier: applied pitch shift zero, pitch-range scale `1.0`,
  formant shift zero, all spectral and tilt adjustments zero, de-essing zero,
  breathiness zero, harmonic weight zero, compressor and limiter neutral,
  capability tuple empty, and no processor-required warnings.
- Strength interpolation passed: 50% values appeared between neutral and full
  target, 100% produced the full bounded plan, interpolation appeared
  monotonic, capability requirements appeared only for active transformation,
  and changing strength did not alter source measurements or target contracts.
- Higher / Brighter and Lower / Weightier diagnostic directions passed. Pitch,
  formant, spectral, tilt, texture, de-essing, compressor/limiter where
  applicable, clamp warnings, and no identity or gender classification behaved
  as expected. These remain diagnostic references, not finished feminine or
  deep-masculine product characters.
- Clamps and degradation passed: requested and applied values are both visible,
  pitch clamps appeared correct, formant planning stayed within accepted
  natural limits, spectral clamp behavior appeared correct, stale source
  handling appeared correct, missing evidence degraded only the affected
  control, F1/F2/F3 remained weak descriptors that do not directly control
  formant planning, and confidence/warnings were understandable.
- Reset and session-state acceptance passed: Reset Target Profile, Reset
  Planner Lab, source analysis unaffected by target reset, devices/routes/
  selected voice/M8.0 settings/soundboard/monitor/volumes unchanged,
  planner values session-only, relaunch restored planner defaults, no target
  profile or plan file was created, and `settings.json` and `presets.json`
  were unchanged.
- Audio transparency passed: no audible pitch, formant, EQ, latency, metallic
  tail, flutter, crackle, new block boundaries, meter behavior change,
  soundboard behavior change, monitor behavior change, Bypass Effects behavior
  change, or UI freezing was observed.
- Accepted M9.1 technical conclusions: `TargetVoiceProfile` is the immutable
  acoustic target contract, `TransformationPlan` is the immutable diagnostic
  plan contract, source profile plus target profile plus character strength is
  the accepted planning architecture, pitch-center planning is accepted,
  pitch-range planning is accepted as a future processor requirement,
  restrained target-intent formant planning is accepted, spectral band and
  tilt-index planning are accepted as diagnostic EQ requirements, de-essing,
  breathiness, harmonic-weight, and dynamics recommendations are accepted as
  plans/future capability requirements, capabilities describe the current
  applied plan, 0% strength is fully neutral, requested and applied values
  remain separately inspectable, planner output remains diagnostic and does
  not alter audio, planner state remains session-only, no source/target/plan
  persistence is required yet, and the planner performs no identity, gender,
  age, or speaker classification.
- Known non-blocking debt: diagnostic target values remain provisional; the
  planner does not yet execute DSP; pitch-range mapping, parametric EQ,
  de-esser, breathiness synthesis, and harmonic enhancement processors do not
  yet exist; approximate F1/F2/F3 remain weak descriptors; target profiles are
  not yet persisted; and no finished feminine or deep-masculine character
  exists. These are expected future milestones, not M9.1 failures.
- The next work begins applying the accepted plan to a controlled experimental
  audio path. It must preserve the planner as the single source of
  transformation intent, support both higher/brighter and lower/weightier
  directions, avoid one-direction-only architecture, begin as a bounded
  experimental execution lab, avoid immediately replacing production
  characters, and preserve normal VoiceLab behavior.

## M9.2 - Controlled Transformation Execution Lab

Status: PASS. Luke completed practical live Transformation Execution Lab
acceptance.

Purpose: add `main.py --transformation-execution-lab`, an isolated controlled
partial-execution mode that consumes the accepted immutable
`TransformationPlan` without becoming a second planner authority.

M9.2 is accepted as execution infrastructure. Continuous reactive replanning is
not accepted as the final normal character-control experience; it remains an
experimental diagnostic/adaptive behavior.

### Implementation Notes

- Normal launch, Formant Lab, Voice Analysis Lab, and Target Planner Lab remain
  isolated and unchanged.
- Transformation Execution Lab includes Source Analysis, Target Planner, and
  Plan Execution tabs. It launches stopped and plan execution launches
  disabled.
- The execution path reuses the accepted Formant Lab chain:
  High-Pass, Noise Gate, Compressor, Experimental Pitch/Formant, Robot,
  Lowpass, Gain, Limiter, then Mixer.
- The executor supports only `adaptive_pitch_center`, `formant_shift`,
  `compressor`, and `limiter`.
- Execution reporting distinguishes planned, M9.2-supported,
  backend-executable, actively executing, backend-unavailable, unsupported, and
  unknown capabilities.
- Execution snapshots expose requested pitch separately from the applied target
  and mark pitch saturation when the M9.1 diagnostic target math reaches the
  target's maximum pitch shift.
- Pitch/formant execution claims are reconciled against the current combined
  backend health. Native backend unavailability or EffectChain runtime bypass
  neutralizes pitch/formant targets and removes them from active execution
  capability reporting.
- Valid Compressor and Limiter overlays may continue during pitch/formant
  backend degradation; the status reports degraded or unavailable execution
  instead of ordinary unsupported-plan partial execution.
- Unsupported capabilities remain visible and are not approximated:
  `pitch_range_mapping`, `parametric_eq`, `spectral_tilt_shaping`,
  `breathiness`, `harmonic_enhancement`, `de_esser`, and unknown future
  capability identifiers.
- Runtime dynamics are session-only overlays on Compressor and Limiter.
  Disabling execution, stale/invalid plans, Stop, and Return to Neutral restore
  the M8.0 baseline settings without writing `settings.json` or
  `presets.json`.
- Pitch/formant execution uses exactly
  `TransformationPlan.pitch.applied_pitch_shift_st` and
  `TransformationPlan.formant.applied_formant_shift_st`. The executor does not
  read source F0, target F0, F1/F2/F3, EQ values, or target-profile dynamics
  directly.
- A bounded low-rate controller runs at 10 Hz when processing is running. It
  retains only the latest plan and latest execution target. UI polling can
  refresh snapshots, but execution does not depend on the UI being open.
- The audio callback does not call the planner or executor. Effects read the
  latest immutable runtime target once per block and perform bounded scalar
  smoothing for pitch/formant.
- Global Bypass Effects remains the single audio bypass authority. Execution
  status reports `bypassed` while preserving the retained target for safe
  smoothing when bypass is removed.
- Application-facing execution snapshots are frozen scalar contracts with
  frozen nested compressor, limiter, and pitch/formant backend health
  snapshots.
- Recovery from a runtime-bypassed combined pitch/formant backend is Stop, then
  Start. Start begins with execution disabled and backend health re-evaluated.
- Latency is inherited from the accepted combined Signalsmith pitch/formant
  stage. M9.2 does not add a second pitch/formant stage and does not claim
  normal-production latency.

### Verification Notes

- Focused M9.2 automated tests cover immutable execution contracts, capability
  mapping, unknown unsupported capabilities, disabled and zero-strength
  neutrality, dynamics overlays, smoothing, mode isolation, guarded UI exposure,
  backend-health reconciliation, native-unavailable reporting, runtime backend
  failure reporting, global bypass distinction, recovery reset, command
  rejection outside execution mode, and a 1,000-iteration bounded controller
  probe.
- Luke's final practical live acceptance recorded PASS for mode/lifecycle
  isolation, audible pitch execution in the planned direction, the formant
  execution path, visible target/current runtime values, absence of metallic
  artifacts/flutter/crackle/new audible block boundaries, finite stable active
  transformation, one combined Signalsmith pitch/formant stage, no second full
  latency stage, neutral disabled and 0% behavior, Return to Neutral, M8.0
  baseline preservation, unsupported capability visibility, fail-closed
  unsafe states, global bypass authority, backend truthfulness, immutable
  snapshots, readiness hysteresis, target/clamp reporting, and session-only
  behavior with unchanged settings, presets, and production characters.
- Accepted technical conclusions: `TransformationExecutor` is subordinate to
  `TransformationPlan`; the planner remains the sole transformation-intent
  authority; adaptive pitch-center execution, restrained formant execution,
  session-only compressor/limiter overlays, runtime smoothing,
  backend-health propagation, immutable execution snapshots, readiness
  hysteresis, and the one combined Signalsmith pitch/formant stage are
  accepted. Inherited latency remains approximately 4800 frames / 100 ms at
  48 kHz.
- M9.2 does not replace production characters and does not establish continuous
  reactive replanning as the final user experience.
- Product-control conclusion: continuous source-driven replanning can feel as
  though the selected character is moving underneath the operator. Continuous
  adaptation remains experimental and must not become default production
  character behavior. Live source analysis should produce a suggested starting
  plan, not continuously override deliberate operator control by default.
- Next milestone direction: Calibrate, Lock, and Manual Trim. Flow: Source
  analysis -> capture a calibration profile -> generate a suggested
  `TransformationPlan` -> lock the plan -> execute stable fixed values -> allow
  manual trims. Expected controls include Calibrate Source, Lock Suggested
  Transformation, Recalibrate, Pitch Trim, Formant Trim, Character Strength,
  Return to Suggested Plan, Return to Neutral, and Adaptive Updating default
  Off.
- Neural voice conversion remains a future optional plugin capability, not a
  required VoiceLab core feature. It must be loadable, disableable,
  replaceable, and absent without breaking VoiceLab. Current development
  remains focused on stable DSP character control.
- Known non-blocking debt: continuous adaptation is not the preferred default
  UX; plan-lock and manual pitch/formant trim do not exist yet; pitch-range
  mapping, parametric EQ, spectral-tilt shaping, de-essing, breathiness
  synthesis, and harmonic enhancement remain unsupported; diagnostic target
  values remain provisional; no finished feminine or deep-masculine character
  exists yet. These are future milestones rather than M9.2 failures.
- M9.2 is a controlled partial-execution lab, not a finished feminine,
  masculine, deep-masculine, giant, childlike, elderly, creature, or synthetic
  character system.

## M9.3 - Calibrate, Lock, and Manual Trim

Status: PASS. Luke completed practical live Calibrate/Lock Lab acceptance.

M9.3 is accepted as the primary stable experimental control workflow.
Continuous adaptation remains optional experimental behavior and is not the
default character-control model.

M9.3 adds an isolated stable-control workflow on top of the accepted M9.0,
M9.1, and M9.2 labs. It does not change normal production launch behavior,
production character presets, target-reference formulas, persistence schemas,
or the audio effect chain.

### Scope

- Launches only with `main.py --calibrate-lock-lab`.
- Enables Source Analysis, Target Planner, Plan Execution, and Calibrate &
  Lock tabs in one isolated lab mode.
- Captures an immutable session-only calibration snapshot from a ready M9.0
  rolling source profile.
- Rejects corrupt calibration evidence before mutation: successful calibration
  snapshots contain only finite numeric scalar evidence or explicit unavailable
  values, and failed captures preserve existing session state.
- Generates a suggested `TransformationPlan` through the existing M9.1 planner
  from the frozen calibration source, current target, and current strength.
- Lets the operator explicitly lock the suggested plan before execution.
- Executes the locked plan through the existing M9.2 execution controller and
  runtime when Adaptive Updating is Off.
- Adds bounded manual pitch trim around `+/-4` semitones and bounded manual
  formant trim around `+/-1` semitone. Final runtime values still respect M9.2
  execution clamps.
- Keeps Adaptive Updating default Off. Continuous remains an optional
  experimental mode that preserves M9.2 live replanning behavior.

### Stable Execution Semantics

- A locked plan is the execution authority while Adaptive Updating is Off.
- Live source changes, current-frame voiced/unvoiced state, target edits,
  strength edits, UI polling, analyzer gates, and analyzer staleness do not
  mutate locked execution while Adaptive Updating is Off.
- Target or strength edits refresh a new suggestion and mark the locked plan as
  stale/different without changing the locked runtime target until the operator
  locks again.
- Recalibrate captures a new calibration and refreshes the suggestion without
  changing the existing lock until the operator locks again.
- Return to Suggested Plan clears manual trims and preserves the lock.
- Return to Neutral disables execution and neutralizes runtime influence while
  preserving calibration, suggestion, lock, and trim state for re-enable.
- No target file, plan file, execution cache, settings entry, preset entry, or
  production character state is created by M9.3.

### Live Acceptance

- Calibrate/Lock Lab launches stopped with Source Analysis, Target Planner,
  Plan Execution, and Calibrate & Lock tabs present.
- Execution launches disabled, Adaptive Updating defaults Off, no calibration,
  suggestion, or lock exists at launch, and pitch/formant trims begin at zero.
- Source collecting/ready states and live source-analysis values update
  visibly. Calibrate Source succeeds after the source becomes ready, captured
  calibration values remain frozen, and live source measurements continue
  updating separately.
- Calibration does not alter audio. Recalibration produces a new suggestion and
  does not alter the active lock.
- Suggested transformation appears after calibration. Lock Suggested
  Transformation succeeds and does not automatically enable execution; the
  operator must explicitly enable execution.
- Locked values remain fixed. Live source changes, collecting/ready changes,
  target edits, character-strength edits, and newer suggestions do not move or
  neutralize a valid locked plan while Adaptive Updating is Off.
- Enabling execution makes the locked transformation audible. The resulting
  voice is usable/decent, runtime values converge to their fixed targets, and
  locked execution is more predictable than continuous reactive replanning.
- Pitch and formant trims change predictably, remain fixed until deliberate
  change, preserve immutable locked base values, report clamps clearly, and do
  not restart the stream.
- Return to Suggested Plan clears trims, restores the locked base, and does not
  silently apply a newer unlocked suggestion.
- Continuous mode uses live adaptive planning only when explicitly selected.
  Switching back to Off restores the retained lock without reopening the stream
  or leaving stale maximum/corrupted targets.
- Return to Neutral disables execution, returns pitch/formant to neutral,
  clears plan-driven dynamics overrides, and preserves calibration, suggestion,
  lock, and documented trim session state for re-enable.
- Luke operated the Calibrate/Lock Lab for approximately 30 minutes with no
  crackle, flutter, metallic tail, growing delay, sudden unexplained target
  jumps, UI freeze, analyzer failure, or controller failure. Stable locked
  behavior remained usable over the extended run.

### Verification Notes

- Focused M9.3 automated tests cover immutable calibration/suggestion/lock/trim
  contracts, capture rejection for inactive/collecting/stale/failure/missing-F0
  sources, nonfinite/invalid/inconsistent calibration evidence, optional
  descriptor rejection, atomic failed-capture state preservation,
  frozen-calibration planning, dirty target/strength state, manual trim
  clamp/projection behavior, Return to Suggested Plan, locked execution
  stability against live source and target edits, Adaptive Updating Off versus
  Continuous behavior, dynamics lock/relock behavior, Return to Neutral,
  guarded UI exposure, effect-chain isolation, disabled audio equivalence, and
  bounded repeated operations without settings or preset mutation.
- Accepted corrective commit: `abdfb61019e70b28f91a66362711b7006f2e0172`
  (`Reject nonfinite calibration evidence`). NaN and infinity cannot enter a
  successful frozen calibration; required pitch evidence must be finite,
  positive, ordered, and within the accepted M9.0 range; source age and voiced
  evidence must be finite and nonnegative; optional numeric descriptors may be
  `None` but must be finite when present; validation completes before state
  mutation and failed capture preserves prior calibration, suggestion, lock,
  trims, mode, execution state, and runtime target.
- Known non-blocking debt: diagnostic target profiles remain provisional; no
  finished production feminine or deep-masculine character exists yet;
  pitch-range mapping, spectral-tilt execution, de-essing,
  breathiness synthesis, and harmonic enhancement remain unsupported; backend
  availability is visible through Plan Execution rather than duplicated fully
  in Calibrate & Lock; long-term neural conversion remains an optional plugin
  concern unrelated to M9.3; no persistence of calibration/lock/trim is
  currently intended. These are future milestones, not M9.3 failures.

## M9.4 - Parametric EQ Foundation

Status: PASS. Luke completed practical live acceptance of the Parametric EQ
Foundation and the corrected laboratory workflow.

M9.4 adds one manual five-band Parametric EQ authority in an isolated lab mode.
It does not change normal production mode, prior lab chains, production
characters, settings schema, presets schema, M9.1 planner formulas, M9.2
execution mapping, M9.3 lock authority, or Signalsmith configuration.

The original form-style Parametric EQ tab was rejected before live DSP
acceptance. The accepted M9.4 interaction model is a graph-first visual EQ
editor with five fixed draggable nodes, one selected-band inspector, compact
global controls, optional Post-EQ spectrum visualization, and diagnostics
collapsed by default.

Accessible interaction scaling was added after initial live use showed the
original precise graph movements were too subtle for Luke to audition reliably.
Graph drag is coarse by default, Shift provides fine adjustment, the graph
shows compact Coarse/Fine value feedback during interaction, the inspector
offers explicit fine stepping, and whole-EQ A/B is prominent through the
existing local bypass authority. DSP ranges and behavior are unchanged.

Final live acceptance confirmed Parametric EQ processing, the graph-first UI,
Input Processing, Routing, Diagnostics, Source Analysis, and the corrected
workflow. No pop, buzz, crackle, bad/growing delay, or obvious transition
instability was observed. Transition telemetry settles truthfully.

The workflow correction preserves accepted DSP behavior and distinguishes
Suggested Plan, Stored/Locked Plan, and Applied Runtime. It also distinguishes
Neutral Target, Return Audio to Neutral, and Clear Stored Transformation.

### Scope

- Launches only with `main.py --parametric-eq-lab`.
- Includes Source Analysis, Target Planner, Plan Execution, Calibrate & Lock,
  and Parametric EQ tabs.
- Parametric EQ is presented as a native Qt frequency-response graph, not a
  five-row primary form.
- Uses a bounded immutable 256-point visualization snapshot derived from the
  applied coefficient bank as the graph source of truth.
- Adds a bounded optional Post-EQ spectrum display using a one-slot latest-frame
  mailbox and worker-side FFT; Input/Output/Both spectrum modes remain deferred.
- Adds exactly one Parametric EQ stage after Experimental Pitch/Formant and
  before Robot. Limiter remains downstream.
- Uses one final manual EQ plan authority owned by `ParametricEqController`.
- Uses RBJ biquad formulas for Low Shelf, Low-Mid Peak, Mid Peak, Presence
  Peak, and High Shelf bands.
- Designs coefficients outside the audio callback and publishes one latest
  immutable coefficient bank to the effect.
- Uses a bounded dual-path crossfade transition for coefficient, flat, local
  bypass, disable, and re-enable changes. Dry/neutral endpoints are explicit
  transition destinations, so neutralizing commands settle and do not leave
  stale transition telemetry.
- Global Bypass Effects bypasses EQ immediately, reports any in-flight EQ
  transition as pending rather than audibly progressing, and lets the latest
  requested EQ state settle after bypass release.
- Reports zero added algorithmic latency for Parametric EQ.
- Keeps EQ values, enable/bypass state, and plans session-only with no
  persistence.

### Band Model

- Low Shelf: default 120 Hz, 60-250 Hz, +/-6 dB, fixed slope/Q 1.0.
- Low-Mid Peak: default 300 Hz, 150-800 Hz, +/-6 dB, Q 0.3-6.0.
- Mid Peak: default 1000 Hz, 500-2500 Hz, +/-6 dB, Q 0.3-6.0.
- Presence Peak: default 3000 Hz, 1500-6000 Hz, +/-6 dB, Q 0.3-6.0.
- High Shelf: default 8000 Hz, 4000-12000 Hz, +/-6 dB, fixed slope/Q 1.0,
  with applied frequency also capped at 45% of sample rate.

### Verification Notes

- Focused M9.4 automated tests cover immutable EQ contracts, five ordered
  bands, validation and clamp behavior, nonfinite rejection, stable finite
  coefficients, directional frequency responses, flat neutrality, individual
  band and five-band cascade behavior, dynamic updates, local/global bypass,
  invalid-plan preservation, neutral/bypass transition settling, Reset Flat
  during transition, global-bypass pending/resume behavior, runtime-failure
  transition clearing, graph coordinate mapping, graph rendering, accessible
  coarse/fine quantization, value overlay feedback, inspector step behavior,
  prominent whole-EQ A/B, node selection/drag/Q/reset, response-snapshot
  truthfulness, bounded Post-EQ spectrum behavior, mode and chain isolation,
  guarded UI exposure, M9.3 authority isolation, session-only state, bounded
  1,000-operation updates, and lifecycle thread shutdown.
- Planner `parametric_eq` remains unsupported in M9.4.
- Planner `spectral_tilt_shaping` remains unsupported in M9.4.
- Spectral-tilt execution is deferred and must map into this EQ authority in a
  later milestone.
- Mode-aware Voice controls disable production Pitch Shift in experimental
  pitch/formant chains and show the actual active chain.
- Soundboard is disabled in experimental voice laboratories and normal
  production Soundboard behavior remains unchanged.
- The nasal/vowel artifact is separate pitch/formant work: it occurs with
  transformation active and EQ bypassed, worsens substantially with negative
  formant movement, and should not be concealed with static EQ. Luke commonly
  prefers pitch around -3 to -4 st with positive formant compensation around
  +1 to +2.5 st. Rounded W onsets, R resonance, and vowel transitions can be
  exaggerated on words such as "words", "wrong", "why", and "what".
- Final live UI PASS: graph-first interface, primary graph workspace, five
  understandable fixed draggable nodes, usable selected-band inspector,
  secondary/collapsed diagnostics, understandable response curve, working
  Post-EQ spectrum, and usable resizing.
- Final live accessibility PASS: coarse graph movement, Shift fine adjustment,
  understandable frequency snapping, Q coarse/fine adjustment, value/mode
  overlay, prominent EQ ON/BYPASS comparison, and stored EQ returning after
  bypass. Coarse interaction was added because Luke is partially deaf and
  ordinary EQ changes were initially difficult to audition; this was not a DSP
  defect.
- Final live DSP PASS: EQ reaches the active audio path; individual and
  combined EQ plans operate; flat EQ and Reset EQ to Flat are neutral; local
  bypass and global bypass remain distinct; zero added EQ algorithmic latency.
- Final workflow PASS: lab production Pitch Shift is not editable when absent;
  Gain, Robot, and Lowpass remain available when present; target/strength edits
  update suggestions only; explicit re-lock is required; Clear Stored
  Transformation clears lock and trims; Soundboard is disabled in experimental
  labs; Parametric EQ remains independent from transformation lock authority.
- Known non-blocking debt: pitch/formant naturalness live acceptance,
  provisional diagnostic target profiles, planner EQ, spectral-tilt execution,
  de-essing, breathiness synthesis, harmonic enhancement, finished production
  feminine/deep-masculine characters, Input/Output/Both spectrum modes, and
  optional future neural conversion.

## M9.5 - Pitch/Formant Naturalness

Status: PASS. Luke completed live Pitch/Formant Naturalness acceptance.

M9.5 corrects diagnostic target planning so pitch depth and formant movement
are no longer treated as the same acoustic direction. It keeps the existing
combined Signalsmith pitch/formant execution path, runtime limits, latency,
settings schema, presets schema, production characters, Parametric EQ
authority, and laboratory reset semantics unchanged.

### Scope

- Adds explicit pitch and formant strategy metadata to immutable target
  profiles and transformation plans.
- Keeps Neutral fully neutral at all strengths.
- M9.6 later replaces the prior Higher / Brighter absolute-F0 behavior with
  Natural Bright relative upward pitch and restrained positive formant
  movement.
- Replaces the old Lower / Weightier diagnostic direction with Natural Deep:
  relative pitch down, moderate positive formant compensation, compressor, and
  limiter recommendations.
- Adds Large / Cavernous as the explicit stylized large-vocal-tract reference:
  relative pitch down plus restrained negative formant movement.
- Keeps `lower_weightier` as a compatibility alias for Natural Deep only.
- Adds a naturalness guard that blocks negative formant movement for natural
  downward-pitch targets and reports degraded planning instead of silently
  creating an inconsistent target.
- Expands manual formant trim authority to `+/-2.0` st so Natural Deep can be
  compared against final formant `0` and a modest deliberate negative final
  formant. Runtime formant safety remains the existing `+/-2.0` st clamp.
- Adds a warning when manual trim or a stylized target produces negative pitch
  plus negative final formant. The warning is based on final applied runtime
  values and does not mutate the locked plan or trims.
- Corrects Neutral so it has no active planner capabilities at any strength.
- Restores protected production preset selection so normal production Pitch
  Shift updates remain truthful while running; experimental pitch/formant lab
  chains still do not expose production Pitch Shift.

### Verification Notes

- Focused M9.5 tests cover immutable strategy contracts, invalid strategies,
  all-target zero-strength neutrality, target ordering, Natural Deep positive
  formant compensation, Large / Cavernous stylized negative formant movement,
  naturalness guard behavior, upward-target regression, deterministic
  planning, lock isolation, Clear Stored Transformation, manual-trim warning,
  Off and Continuous adaptive modes, UI target exposure, and deterministic
  finite audio through the inherited one-stage pitch/formant path.
- M9.1 through M9.4 regressions remain green.
- Planner `parametric_eq` and `spectral_tilt_shaping` remain unsupported.
- No pitch-range mapping, phoneme model, speech model, de-essing, breathiness,
  harmonic enhancement, spectral tilt, neural conversion, production character
  replacement, persistence, second pitch/formant stage, Signalsmith buffering
  change, or EQ concealment was added.

### Live Acceptance

- Natural Deep at approximately `-3.5 st` pitch and `+1.505 st` formant was
  judged substantially more natural than the prior lower-voice behavior. Luke
  reported that it "sounds pretty dang good", is clearly good and usable, and
  materially improves problematic W/R/vowel phrases such as "words", "wrong",
  "why", and "what". The result no longer primarily resembles someone
  deliberately forcing their throat lower.
- Positive formant compensation is the accepted natural-deep policy. Lowering
  pitch for a natural deep voice must not automatically lower formants.
- Large / Cavernous at approximately `-4.5 st` pitch and `-1.5 st` formant was
  judged ridiculous and exaggerated, which is the intended stylized
  large-vocal-tract behavior. It remains useful as a deliberate creative effect
  and must not be presented as the natural deep-voice default.
- Natural Deep sounds natural enough for continued product development,
  improves the old W/R/vowel resonance behavior, is clearly preferable to the
  prior negative-formant lower voice, and remains distinct from pitch-only
  behavior.
- Large / Cavernous is clearly stylized and exaggerated. Its vowel and
  resonance exaggeration is expected rather than considered a defect.
- Target strength scales predictably. Manual trim can reach formant zero and
  can produce deliberate negative final formant with truthful warnings.
- Calibration creates suggestions reliably, locking works reliably, execution
  applies the stored plan, Return Audio to Neutral remains correct, and Clear
  Stored Transformation remains correct.
- No new crackle, flutter, metallic tail, stream restart, growing delay, or
  M9.4 Parametric EQ regression was reported.

### Accepted Architecture

- Natural Deep uses explicit relative downward pitch strategy and positive
  natural-compensation formant strategy.
- Large / Cavernous uses explicit downward pitch plus size-coupled negative
  formant strategy.
- Pitch direction and formant direction are decoupled, target strength is
  applied once, planner values remain deterministic, and Natural Deep does not
  planner-generate negative formant.
- The naturalness guard applies to invalid negative natural-compensation intent
  regardless of pitch sign.
- Manual trim remains additive operator authority. Manual formant trim range is
  `+/-2.0 st`, while the runtime formant safety limit remains `+/-2.0 st`.
  Negative final formant through manual trim remains allowed and truthfully
  warned.
- One combined Signalsmith Pitch/Formant stage remains. Inherited active
  latency remains approximately 4800 frames / 100 ms at 48 kHz. No additional
  pitch or formant stage was introduced.
- Parametric EQ remains independent, and no static EQ compensation is used to
  conceal pitch/formant artifacts.
- Continuous remains Off by default, explicit lock authority remains required,
  and no persistence or schema changes were introduced.
- `lower_weightier` remains a lookup compatibility alias that resolves to
  canonical Natural Deep semantics, does not appear as a fifth visible target,
  stores plans with the canonical target identity, and no longer creates
  alias-driven dirty state.
- Neutral produces zero pitch and zero formant at every strength, Neutral
  dynamics remain neutral, Neutral active capabilities remain empty, and
  unsupported planner capabilities do not escape as applied capabilities.
- Protected Deep Voice preset behavior now restores its intended full default
  strength. Production Pitch Shift works in normal production mode, remains
  absent from experimental pitch/formant lab chains, and no duplicate pitch
  stage was introduced.

### Known Non-Blocking Debt

- Natural Deep values are accepted diagnostic defaults, not finished universal
  character presets.
- More source voices should eventually be tested.
- Natural Bright still requires live acceptance and separate final-character
  development.
- Finished feminine and masculine character profiles remain future work.
- De-essing, breathiness, harmonic enhancement, spectral-tilt execution,
  planner-driven Parametric EQ, and neural voice conversion remain unsupported
  or optional future work.
- Additional articulation-sensitive phrase testing may continue as tuning
  evidence, but does not block M9.5.

## M9.6 - Higher / Brighter Naturalness

Status: PROVISIONAL. Implementation and automated verification are complete;
live Natural Bright acceptance is still required before PASS.

M9.6 separates natural upward brightening from deliberately exaggerated
small-vocal-tract stylization. It preserves the accepted Natural Deep and
Large / Cavernous behavior from M9.5.

### Scope

- Keeps canonical target ID `diagnostic-higher-brighter`, but changes its
  visible name and semantics to Natural Bright.
- Retains legacy `higher_brighter` lookup compatibility and adds
  `natural_bright` lookup without creating a duplicate visible target or
  alias-driven dirty state.
- Adds `diagnostic-small-cartoon` as the explicit stylized upward comparison
  target.
- Uses this visible target order: Neutral, Natural Bright, Natural Deep, Small
  / Cartoon, Large / Cavernous.
- Natural Bright uses relative pitch `+3.5 st` and restrained positive formant
  `+1.0 st` at full strength. Strength applies once, source F0 does not alter
  the requested semitone movement, and normal target values do not hit planner
  clamps.
- Small / Cartoon uses relative pitch `+6.0 st` and size-coupled stylized
  positive formant `+2.0 st` at full strength. It warns at nonzero strength
  that the result may sound chipmunk-like, thin, nasal, or sharply sibilant.
- Zero strength is fully neutral for all visible targets and aliases:
  requested/applied pitch and formant are zero, dynamics are neutral, active
  capabilities are empty, stylized state is false, and warnings are absent.
- Natural Bright is a diagnostic natural upward/brightening foundation, not a
  finished feminine voice.

### Non-Changes

- No additional pitch, formant, or Signalsmith stage was introduced.
- Signalsmith buffering and inherited active latency remain unchanged at
  approximately 4800 frames / 100 ms at 48 kHz.
- Manual pitch/formant trims remain additive operator authority. Manual formant
  trim remains `+/-2.0 st`; runtime formant safety remains `+/-2.0 st`.
- Explicit lock authority remains required, Continuous remains Off by default,
  and target/strength changes update suggestions only until re-locked.
- No production character preset, production Pitch Shift behavior, settings
  schema, presets schema, target persistence, plan persistence, de-essing,
  breathiness synthesis, harmonic enhancement, spectral-tilt execution,
  planner-driven Parametric EQ, static EQ compensation, phoneme/speech
  recognition, identity classification, or neural conversion was added.
- Natural Deep remains approximately `-3.5 st` pitch and `+1.505 st` formant
  at full strength.
- Large / Cavernous remains approximately `-4.5 st` pitch and `-1.5 st`
  formant at full strength.
- Planner `parametric_eq` and `spectral_tilt_shaping` remain unsupported.

### Live Acceptance Required

- Natural Bright must sound more natural than the old absolute-F0 Higher /
  Brighter behavior.
- Natural Bright must be preferable to pitch-only, or live testing must identify
  a better formant value.
- Natural Bright must not sound primarily chipmunk-like or helium-like and must
  remain clearly distinct from Small / Cartoon.

### M9.6 UX Correction - Unified Transformation Workflow

Status: PROVISIONAL. Implementation and automated verification are complete;
live unified-workflow acceptance is still required before PASS.

The first M9.6 implementation exposed truthful subsystem tabs as the main user
path, but that forced repeated movement between Source Analysis, Target Planner,
Calibrate & Lock, Plan Execution, and Parametric EQ. The corrected workflow adds
a primary `Transform` page so the normal task is completed in one place.

Accepted implementation scope:

- Top-level laboratory navigation starts with `Transform`, then Input
  Processing, Routing, and Diagnostics.
- The Transform page exposes analysis readiness, calibration, five target
  choices, strength, Preview, Apply Transformation / Apply Changes, Applied
  Transformation, manual pitch/formant adjustments, Advanced Tone Shaping
  Parametric EQ, Return Audio to Neutral, Resume Stored Transformation, and
  Clear Transformation.
- `ApplicationService.apply_suggested_transformation()` is an explicit atomic
  user action that locks the current immutable suggestion and enables execution
  in one coherent command result.
- Target, strength, and calibration changes update Preview only. Stored and
  audible runtime remain unchanged until Apply Transformation / Apply Changes.
- A compact persistent transformation summary is visible above all tabs and is
  derived from ApplicationService snapshots.
- Source Analysis, Target Planner, Plan Execution, Calibrate & Lock, and
  Parametric EQ diagnostics remain available and read the same service state.

Non-changes:

- No DSP behavior, target value, planner formula, Signalsmith configuration,
  Signalsmith latency, Parametric EQ DSP, persistence, settings schema, presets
  schema, production character, explicit-lock authority, or Continuous default
  was changed.

Acceptance remains blocked on live confirmation that the unified workflow gives
one obvious next action, makes audible versus unapplied state obvious, supports
return/resume/clear without stale-state confusion, and preserves diagnostic
inspection for advanced users.

### M9.6 UX Correction - Core Voice Shaping on Transform

Status: PROVISIONAL. Implementation and automated verification are complete;
live core-shaping acceptance is still required before PASS.

Luke's live unified-workflow pass found the remaining practical issue: common
voice-shaping controls still required leaving `Transform`. The corrected page
now includes `Core Voice Shaping` between Manual Adjustment and Advanced Tone
Shaping.

Implemented scope:

- Output Character controls expose existing Gain, Robot, and Lowpass
  authorities from the active voice chain.
- Input Cleanup exposes the existing Input Processing High-Pass enabled state
  and cutoff as a compact quick control.
- `Open Full Input Processing` remains the path to Noise Gate, Compressor,
  Limiter, and detailed input cleanup.
- Transform and the original Voice/Input Processing pages synchronize through
  ApplicationService-owned state.
- Global Bypass Effects remains separate and is reported as making the shaping
  controls inaudible without clearing or toggling their values.

Non-changes:

- No Gain, Robot, Lowpass, High-Pass, Parametric EQ, Pitch/Formant, or
  controller instance was duplicated.
- No DSP behavior, chain order, target value, Signalsmith latency, settings
  schema, presets schema, persistence, production Pitch Shift behavior, or
  Soundboard laboratory isolation changed.
- Strength must scale predictably, sibilants must remain usable, vowels must
  remain recognizable, the lock/calibration workflow must remain reliable, and
  no stability regression may occur.
