# VoiceLab Architecture Specification v1.1

## 1. Vision

VoiceLab is a modular real-time voice processing platform for experimentation, diagnostics, customization, and extensibility.

It is not merely a voice changer. It is a voice-processing workstation.

This specification defines implementable contracts between subsystems. It does not define implementation code.

## 2. Non-Negotiable Architectural Rules

VoiceLab follows the rules in `NON_NEGOTIABLES.md`. The rules most relevant to implementation are:

- The engine never imports UI.
- The UI never processes audio.
- Effects are plugins, not engine code.
- Characters are configuration, not Python code.
- Every responsibility has exactly one owner.
- Data flows through defined interfaces; side-door coupling is forbidden.
- Every component should be independently testable.

## 3. Glossary

| Term | Meaning |
| --- | --- |
| Audio Engine | The runtime subsystem that owns audio flow, processing lifecycle, and coordination of capture, effect chain, mixer, and router. |
| Audio Block | A bounded group of audio frames processed as one unit by the engine and its subsystems. |
| Audio Frame | One sample instant across all channels in a stream. For stereo output, one frame contains one left sample and one right sample. |
| Effect | A single audio transformation with defined parameters, validation rules, processing behavior, and telemetry. |
| Plugin | A loadable implementation unit that provides one or more effects through the plugin contract. |
| Effect Chain | The deterministic ordered sequence of enabled effect instances applied to audio blocks. |
| Mixer | The subsystem that combines processed microphone audio and auxiliary audio into output buses. |
| Router | The subsystem that delivers mixer buses to output destinations such as virtual mic and monitor. |
| Character | A configuration preset for effect chain selection, effect enable/bypass state, and effect parameter values. |
| Telemetry Event | A timestamped report of a significant occurrence such as plugin failure, device loss, command rejection, or routing change. |
| Telemetry Snapshot | The latest sampled state used for display or diagnostics, such as levels, latency, device state, and effect state. |
| Command | A validated request from UI or controller code to change application, engine, configuration, routing, preset, or soundboard state. |
| Auxiliary Audio Source | A non-microphone source, such as soundboard playback, that feeds the mixer. |
| Output Bus | A named mixer output stream, such as `main_bus` or `monitor_bus`, that the router can deliver to a destination. |

## 4. Architectural Invariants

Architectural invariants are assertions that should always be true. They are used to review changes, tests, and refactors.

- Exactly one Audio Engine exists at runtime.
- The Audio Engine owns audio flow.
- The Effect Chain executes in deterministic order.
- Effects never route audio directly to output devices.
- Audio never flows directly from an effect to an output device.
- The Mixer is the only subsystem that combines microphone and auxiliary audio.
- The Router never modifies audio except for required device adaptation.
- Telemetry observes application state and never changes application state.
- Configuration is the single source of truth for persistent user choices.
- Character presets affect effects only in v1.
- UI and controller subsystems change state only through commands.
- Every command returns success or failure.
- Every responsibility has exactly one owner.
- Every subsystem knows only what it needs to perform its responsibility.
- Runtime plugin failures bypass the failed plugin when possible instead of crashing audio.

## 5. System Scope and External Dependencies

| Item | VoiceLab ownership |
| --- | --- |
| Microphone capture | VoiceLab owns device selection and stream capture through an audio I/O adapter. |
| Virtual microphone output | VoiceLab owns the generic output abstraction and routing contract. |
| VB-CABLE | User-installed external dependency. VoiceLab does not bundle, install, or update it. |
| Other virtual mic backends | Architecturally supported through the virtual mic abstraction, not implemented in v1. |
| Monitor output | VoiceLab owns routing to a selected local playback device. |
| Audio effects | VoiceLab owns the plugin contract and chain execution; plugins own effect behavior. |
| UI | VoiceLab owns presentation and user commands, but not audio processing. |

`Virtual Mic` means a generic destination that exposes processed audio as an input device to other applications. In v1, this targets VB-CABLE-style routing.

## 6. High-Level Runtime Pipeline

```text
Microphone
      |
      v
Capture
      v
Audio Engine
      v
Effect Chain
      v
Mixer
  |        |
  v        v
main_bus  monitor_bus
  |        |
  v        v
Router
  |        |
  v        v
Virtual Mic   Monitor

Telemetry observes Capture, Engine, Effects, Mixer, Router, and Outputs.
UI reads state and telemetry, and sends commands through the command interface.
Hotkeys send commands through the controller subsystem.
```

| Stage | Responsibility | Input | Output | Must not do |
| --- | --- | --- | --- | --- |
| Capture | Read microphone audio into the engine format. | OS microphone stream. | Audio blocks. | Apply effects or update UI directly. |
| Audio Engine | Own real-time audio flow and processing lifecycle. | Audio blocks, commands, configuration. | Processed stream state and output buses. | Import UI or implement effect-specific behavior. |
| Effect Chain | Invoke enabled effect plugins in configured order. | Audio blocks and effect parameters. | Processed audio blocks and effect telemetry. | Discover devices or route audio. |
| Mixer | Combine primary and auxiliary sources into output buses. | Processed mic audio and auxiliary audio. | `main_bus` and `monitor_bus`. | Select OS devices or perform effect processing. |
| Router | Deliver buses to configured destinations. | Mixer buses and routing config. | Audio to virtual mic and monitor devices. | Change audio content except required device adaptation. |
| Telemetry | Collect sampled metrics and events. | Subsystem reports. | Snapshots, events, logs. | Control audio flow. |
| UI | Present state and send user commands. | State snapshots and telemetry. | Commands. | Process audio or mutate engine internals. |

## 7. Subsystem Responsibilities

| Responsibility | Owner |
| --- | --- |
| Audio device discovery | Audio I/O adapter |
| Microphone capture | Capture |
| Input format conversion to engine format | Capture |
| Engine lifecycle | Audio Engine |
| Effect ordering | Effect Chain |
| Effect behavior | Effect Plugin |
| Effect parameter validation | Effect Plugin |
| Effect enable/bypass state | Effect Chain |
| Soundboard playback source | Application service |
| Soundboard audio mixing | Mixer |
| Dry/wet handling | Mixer unless an effect declares an internal dry/wet parameter |
| Gain staging across sources | Mixer |
| Virtual mic destination selection | Router |
| Monitor destination selection | Router |
| Routing state validation | Router |
| Configuration loading and saving | Configuration service |
| Configuration validation coordination | Application service |
| UI rendering | UI |
| UI command dispatch | UI through command interface |
| Hotkey handling | Controller subsystem |
| Telemetry aggregation | Telemetry service |

Every responsibility has exactly one owner. Other subsystems may request work from the owner only through defined interfaces.

## 8. Audio Data Contract

The engine audio format for v1 is:

- sample rate: 48 kHz
- processing sample format: `float32`
- input channels: mono
- output channels: stereo

`AudioFrame` is the authoritative runtime contract for audio data and audio-format metadata. It owns:

- sample rate
- channel count
- frame count
- sample format
- monotonic block index or timestamp

Shape conventions:

- Mono audio uses NumPy shape `(frames,)`.
- Multichannel audio uses NumPy shape `(frames, channels)`.
- `channel_count` must match the sample shape.
- `frame_count` must match `samples.shape[0]`.
- v1 contract samples use dtype `float32`, and `sample_format` must be `float32`.

`AudioContext` carries processing metadata alongside an `AudioFrame`. When attached to an `AudioFrame`, duplicated fields must agree with the frame. `AudioContext` must not become a second independent source of truth for sample rate, frame count, sample format, block index, or timestamp.

Timestamp semantics:

- `timestamp` is optional.
- When present, it is a non-negative monotonic time value in seconds.
- It is not wall-clock or calendar time.

Block-index semantics:

- `block_index` is optional.
- When present, it is a non-negative integer.
- Within one processing session it should increase monotonically from startup or stream reset.
- VoiceLab does not define a full transport timeline in v1.

Processing-stage values are a validated string vocabulary. Valid v1 values are:

- empty string for unspecified or not currently staged
- `capture`
- `engine`
- `main_bus`
- `monitor_bus`

Buffer ownership:

- Frozen dataclasses do not make contained NumPy arrays immutable.
- The subsystem creating an `AudioFrame` or `AuxiliaryAudio` owns the sample buffer it passes.
- Subsystems receiving a contract object must treat the sample buffer as read-only unless the interface explicitly grants mutation ownership.
- A subsystem that needs to mutate audio across a boundary must produce a new contract object or a clearly owned buffer.

Effect plugin boundary for RC1:

- Subsystem contracts use `AudioFrame`.
- `EffectChain` may unwrap `AudioFrame.samples` for current DSP plugins.
- DSP plugins may continue operating on NumPy arrays internally.
- `AudioEngine` and `EffectChain` must preserve the `AudioFrame` boundary around plugin processing.

`AuxiliaryAudio` is the v1 contract for non-microphone clip or block audio entering the mixer. It uses the same shape, frame count, channel count, dtype, and sample-format invariants as `AudioFrame`. It is intentionally clip/block based; streaming auxiliary sources are not defined in v1.

Deprecated compatibility paths may temporarily accept raw NumPy arrays:

- `AudioEngine.process_voice(...)`
- `Mixer.mix(...)`
- `Mixer.queue_sound(...)`
- `AudioIO.write_frame(...)`

Canonical runtime code must use `AudioFrame`, `AuxiliaryAudio`, and `OutputBuses` instead of these raw-array paths. The compatibility paths must not be expanded.

## 9. Engine Contract

The Audio Engine owns:

- starting and stopping audio processing
- coordinating capture, effect chain, mixer, and router
- applying validated live configuration changes
- maintaining real-time engine state
- reporting engine status and failures to telemetry

The Audio Engine does not own:

- UI rendering
- device installation
- plugin discovery policy
- individual effect algorithms
- character preset persistence
- hotkey capture

Configuration changes should apply live while audio is running. Changes that cannot be applied safely must be rejected with a telemetry event and command result.

## 10. Effect Chain Contract

The Effect Chain owns:

- the ordered list of enabled effect plugin instances
- effect bypass state
- passing audio blocks through effects in order
- applying validated effect parameter changes
- bypassing an effect after runtime failure when possible
- reporting chain and effect status to telemetry

The v1 chain is linear. The architecture should not prevent later branching, but v1 code must not require branching.

## 11. Effect Plugin Contract

Every effect plugin must expose:

- stable identity
- version
- parameter definitions
- parameter validation rules
- lifecycle expectations
- audio processing behavior
- telemetry fields or events
- test entry points independent of UI, microphone, and virtual cable

Effect plugins may:

- transform audio blocks passed to them
- expose effect-specific telemetry
- reject invalid parameters

Effect plugins must not:

- import UI
- discover or open audio devices
- route audio to outputs
- mutate unrelated engine state
- depend on global mutable state unless explicitly justified

Load failure disables the plugin and reports telemetry. Runtime failure bypasses the plugin and reports an error. Audio should not crash if bypass is possible.

## 12. Plugin Discovery and Loading

Plugins load at application startup only in v1.

Hot reload is explicitly out of scope for v1.

Plugin discovery must define:

- plugin search locations
- required plugin metadata
- compatibility checks
- disabled plugin behavior
- telemetry for load success and failure

Invalid or incompatible plugins are disabled, reported through telemetry, and excluded from available effect chains.

## 13. Mixer Contract

The Mixer owns audio combination and bus creation.

Inputs:

- processed microphone audio from the Effect Chain
- auxiliary audio sources such as soundboard playback
- mixer configuration

Outputs:

- `main_bus`: intended for virtual mic routing
- `monitor_bus`: intended for local monitoring

Virtual mic and monitor receive identical audio by default in v1. The architecture still treats them as separate buses so later mixer behavior can diverge without changing router contracts.

The Mixer owns:

- source gain
- dry/wet blend when not owned by a specific effect
- combining microphone and auxiliary sources
- bus-level mute or gain if supported

The Mixer does not own:

- OS device selection
- virtual mic backend selection
- plugin behavior

## 14. Router Contract

The Router owns delivery of mixer buses to output destinations.

The Router maps:

- `main_bus` to the configured virtual mic backend
- `monitor_bus` to the configured monitor output device

The Router owns:

- destination availability checks
- routing state validation
- output stream lifecycle
- device loss reporting
- runtime route changes when safe

The Router must not perform effect processing. Device-required adaptation is allowed only when necessary to satisfy the output device contract.

## 15. Virtual Mic and Monitor Output Contract

The virtual mic output is a generic abstraction. In v1, the only implemented target is VB-CABLE-style routing to a user-installed virtual audio device.

VoiceLab must report when the configured virtual mic target is missing or unavailable. Missing virtual mic output must not prevent local monitoring if monitor output is available.

The monitor output is optional. If unavailable, VoiceLab may continue processing for the virtual mic when possible and must report monitor failure through telemetry.

Default behavior:

- `main_bus` and `monitor_bus` contain identical audio.
- `main_bus` routes to virtual mic.
- `monitor_bus` routes to monitor output.

## 16. Configuration Contract

Configuration is the source of truth for:

- app settings
- audio device selections
- routing settings
- effect chain settings
- character presets
- UI preferences, when persistent
- hotkey bindings
- soundboard asset references and settings

Configuration must define:

- persistence format
- default values
- validation rules
- migration policy
- ownership for loading and saving
- which changes are live-applicable

The UI must not mutate engine internals directly. Persistent user changes flow through the application command interface and configuration service.

## 17. Character Preset Contract

A character preset is configuration for effect behavior.

In v1, a character preset may contain:

- character id
- display name
- effect chain selection
- effect enable/bypass state
- effect parameter values

A character preset must not contain:

- Python code
- routing or device changes
- virtual mic backend selection
- monitor device selection
- hotkey bindings

## 18. UI / Engine Boundary

The UI communicates through an application or engine command interface.

UI may:

- display engine state
- display telemetry snapshots and events
- request configuration changes
- request engine lifecycle changes
- request preset selection
- request soundboard actions

UI must not:

- process audio
- import engine internals for mutation
- write directly into real-time engine state
- bypass validation

Commands must return success or failure. Invalid UI edits are rejected at the command or validation boundary and reported without partially mutating engine state.

## 19. Telemetry Contract

Telemetry is both sampled and event-based.

Sampled telemetry includes current or recent values such as:

- input level
- output level
- latency estimate
- dropout count
- active device status
- active effect status
- CPU or processing load where available

Event telemetry includes:

- plugin load failure
- plugin runtime failure
- device loss
- invalid command rejection
- config validation failure
- engine start and stop
- routing changes

The UI may poll the latest telemetry snapshot. Serious events must be pushed, logged, or otherwise preserved so they are not lost between polls.

Telemetry observes subsystems. It does not control them.

## 20. Real-Time Processing Constraints

VoiceLab targets real-time operation under 50 ms round-trip latency, with under 25 ms preferred where practical.

v1 supported audio format:

- 48 kHz
- `float32`
- mono input
- stereo output

The real-time audio path must avoid:

- blocking UI calls
- plugin discovery or loading
- disk I/O
- network I/O
- unbounded allocation
- long-running locks
- direct configuration file writes

When processing overruns occur, VoiceLab must report telemetry. If a plugin causes runtime failure or repeated overruns, bypassing the plugin is preferred over crashing audio.

## 21. Error Handling and Recovery

| Failure | Required behavior |
| --- | --- |
| Missing microphone | Do not start capture; report telemetry and command failure. |
| Microphone lost during processing | Stop or pause capture safely; report telemetry. |
| Missing virtual mic target | Disable virtual mic route; keep monitor route if available. |
| Missing monitor target | Disable monitor route; keep virtual mic route if available. |
| Plugin load failure | Disable plugin; report telemetry; continue startup if possible. |
| Plugin runtime failure | Bypass plugin; report telemetry; keep audio running if possible. |
| Invalid configuration | Reject invalid fields or config; report validation failure. |
| Invalid UI command | Reject command; report result without partial mutation. |
| Telemetry failure | Do not stop audio solely because telemetry failed. |

## 22. Testability Requirements

The architecture must support tests without requiring the GUI, microphone, or virtual cable.

Required test seams:

- fake microphone input
- fake output device
- offline audio block processing
- effect plugin tests independent of engine
- effect chain tests with fake plugins
- engine lifecycle tests without UI
- router tests without real VB-CABLE
- telemetry tests without UI
- configuration validation tests
- command interface tests
- hotkey/controller tests without audio processing
- soundboard source tests without physical output

## 23. Documentation Ownership and Versioning

Canonical documentation paths:

- `ARCHITECTURE.md`
- `NON_NEGOTIABLES.md`
- `ROADMAP.md`
- `DECISION_QUEUE.md`
- `ENGINEERING_PROCESS.md`

Root-level files are canonical. Copies under `docs/` are not canonical and must not contain competing architecture rules.

Architectural changes must update documentation before or with implementation. `NON_NEGOTIABLES.md` defines rules; `ARCHITECTURE.md` defines contracts and boundaries; `ROADMAP.md` defines sequencing and planned scope; `DECISION_QUEUE.md` tracks unresolved architecture decisions; `ENGINEERING_PROCESS.md` defines the contribution workflow.

## 24. Lifecycle

The lifecycle defines when subsystems exist and the order in which startup and shutdown work must occur. Startup failures should report telemetry as soon as telemetry is available.

### Application Startup

1. Application startup
2. Load configuration
3. Initialize telemetry
4. Discover plugins
5. Validate plugins
6. Initialize engine
7. Initialize mixer
8. Initialize router
9. Open devices
10. Start audio
11. Accept commands

### Shutdown

1. Stop commands
2. Stop audio
3. Flush telemetry
4. Close devices
5. Unload plugins
6. Save configuration
7. Exit

Lifecycle ownership must follow the subsystem ownership rules in this document. A later lifecycle step must not assume an earlier step succeeded unless that success is explicit.

## Decision Queue

Open architecture questions are tracked in `DECISION_QUEUE.md`. Each unresolved question must have one decision page.
