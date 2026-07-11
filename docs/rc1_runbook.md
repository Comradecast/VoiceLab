# VoiceLab RC1 Runbook

## Supported Environment

- Windows 10 or later.
- 64-bit CPython matching the runtime interpreter used to launch VoiceLab.
- Python 3.13 is the verified RC1 development target.
- Microsoft C++ Build Tools with the MSVC compiler.
- External virtual microphone dependency: VB-CABLE or an equivalent
  user-installed virtual audio device.

Final RC1 hardware acceptance was completed on:

- Windows 11.
- Python 3.13.3.
- AMD64 / 64-bit runtime.
- pybind11 3.0.4.
- Signalsmith native module active.

## Setup

Create and activate a virtual environment, then install runtime/build
dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install numpy scipy soundfile sounddevice PySide6 pynput pedalboard setuptools wheel pybind11
```

Signalsmith Stretch and Signalsmith Linear are vendored under `third_party/`.
The compiled native module is a generated release artifact and is not committed.

## Native Pitch Backend

Build the native backend from the repository root with the target interpreter:

```powershell
.\.venv\Scripts\python.exe .\tools\build_signalsmith_backend.py
```

Expected output location:

```text
voice_lab/effects/_signalsmith_pitch*.pyd
```

Verify Signalsmith is active:

```powershell
.\.venv\Scripts\python.exe -c "from voice_lab.effects.signalsmith_backend import signalsmith_status; print(signalsmith_status())"
```

Expected status is `available=True` and `status='active'`.

If the native module is unavailable, pitch telemetry reports Pedalboard fallback
as `backend='pedalboard'` and `backend_status='fallback_active'`. Fallback is
diagnostic only and must not be treated as canonical RC1 success.

## Launch

```powershell
.\.venv\Scripts\python.exe main.py
```

Select microphone, virtual mic output, and optional monitor output in the UI.
Normal shutdown is through the window close button or application quit; it should
stop controllers, audio streams, router/device handles, effect backend buffers,
telemetry flushing, and configuration flushing.

After closing VoiceLab, no hidden `main.py` process should remain. The native
backend build command should be able to replace the `.pyd` after normal close.

## Known Limitations

- Recommended normal pitch range is `+/-4` semitones.
- `+/-8` semitones is usable but obviously processed.
- `+/-12` semitones is intentionally extreme.
- Some sung notes, bends, or transitions may sound flattened. This is deferred
  product-quality debt and is not an RC1 blocker.
- The former soundboard two-stage playback behavior was not reproduced during
  final RC1 hardware acceptance. Treat it as historical unless it becomes
  reproducible again.
- M6.1 adds primary operator status visibility in the application UI. Persistent
  logging remains out of scope for RC1/M6.1.

## Operator Status Visibility

The main window shows compact read-only operator status derived through
`ApplicationService`:

- processing state;
- route state;
- pitch state and backend in plain language;
- estimated pitch DSP latency when meaningful;
- latest command/status message;
- latest actionable warning or error;
- compact diagnostic backend fields.

The status refresh runs on the Qt UI thread about twice per second. It is
read-only: it does not discover devices, discover plugins, write configuration,
create effects, restart audio, select a backend, or mutate telemetry.

## Manual Device Refresh

M6.4 adds an explicit `Refresh Devices` action near the audio device selectors.
The action is available only while processing is stopped or after a failed
start. It is disabled while processing is starting, running, or stopping, and
the service rejects refresh commands in those states.

Refresh behavior:

- Audio device enumeration remains owned by `AudioIO`.
- The UI receives immutable application-facing device descriptors through
  `ApplicationService`.
- Existing selections are preserved only when the same device identity is
  matched safely.
- VoiceLab never preserves a selection by numeric index alone or display name
  alone.
- If the selected device disappears or becomes ambiguous, that selector is
  cleared and the operator must explicitly choose a replacement.
- Monitor-enabled state is unchanged by refresh.
- Effect parameters, presets, and soundboard state are unchanged by refresh.
- Refresh does not automatically stop or start processing.
- Refresh does not add background hot-plug monitoring or periodic polling.

Device identity uses the exact device name, host API identifier, input/output
channel capabilities, and default sample rate. A same-index match is preserved
only when identity still matches. A moved device is preserved only when there is
one unique exact identity match at the new index.

If enumeration fails, VoiceLab preserves the old selector contents and current
selections, reports:

```text
VoiceLab could not refresh audio devices. Check Windows audio services and try again.
```

Technical details remain in telemetry.

## Persistent Operator Settings

M6.5 adds a separate project-root operator settings file:

```text
settings.json
```

The file is versioned with `schema_version: 1` and is separate from
`presets.json`. Presets remain the owner of effect parameter combinations;
operator settings only remember stable setup preferences.

Persisted settings:

- selected microphone identity;
- selected virtual microphone output identity;
- selected monitor output identity;
- monitor enabled state;
- monitor volume;
- soundboard volume;
- last explicitly selected preset;
- selected built-in voice character, when applicable;
- character strength, when applicable.

Device identity is serialized with the same exact fields used by the M6.4
device model: device name, host API, input channel count, output channel count,
and default sample rate. PortAudio numeric device index is not persistent
identity and must not be used as a fallback.

Not persisted:

- current PortAudio index as identity;
- backend objects or raw backend mappings;
- active streams;
- processing-running state;
- audio-running or route-active state;
- effects bypass state;
- pitch backend processor identity;
- telemetry event history;
- arbitrary unsaved effect slider state;
- temporary paths or secrets.

Startup behavior:

- VoiceLab always launches stopped.
- Saved devices are selected only when the stored identity resolves uniquely.
- Missing or ambiguous saved devices leave the selector empty.
- No replacement device is silently selected.
- First launch does not select hard-coded numeric device IDs or the first
  available device automatically.
- If monitoring was saved as enabled but the saved monitor output is missing,
  monitoring remains enabled and Start requires selecting a monitor or disabling
  monitor output.
- If the saved preset still exists, it is restored through the normal preset
  command path. If it is missing, VoiceLab does not recreate it.
- If a saved built-in voice character still exists, it is restored through the
  normal voice-character command path.
- If both legacy selected-preset data and voice-character data are present, the
  voice-character fields are the canonical M7 operator state.

Manual `Refresh Devices` cooperates with saved preferred identities. If a
missing preferred device later returns and resolves uniquely, refresh may
restore it. If the identity is still missing or ambiguous, the selector remains
empty and the operator must choose explicitly.

Write policy:

- Settings are marked dirty on explicit operator changes.
- Dirty settings flush during normal lifecycle shutdown.
- Slider movement marks settings dirty in memory but does not write to disk on
  every UI tick.
- Saves use a same-directory temporary file followed by atomic replacement where
  supported by Windows.
- Save failures are reported through status/telemetry and do not prevent audio
  shutdown.

Corruption and unsupported schema behavior:

- Missing files use safe first-run state.
- Empty, malformed, wrong-root, unreadable, or partially invalid files do not
  prevent launch.
- Valid fields are preserved where possible when unrelated fields are invalid.
- Unsupported future schema versions are not interpreted as schema `1` and are
  not overwritten automatically on load.
- Raw serialized identity details are not shown in the primary UI.

## Voice Character Experience

M7.0 Status: PASS.

M7.0 changes the primary operator workflow from technical effect tuning to
voice-character selection. The effect sliders and saved preset tools remain
available as advanced controls.

Built-in characters:

| Character | Gain | Robot | Lowpass | Pitch |
| --- | ---: | ---: | ---: | ---: |
| Natural | 10 | 0 | 4000 | 0 |
| Deep | 9 | 0 | 2200 | -4 |
| Heavy Bass | 10 | 0 | 1800 | -6 |
| Higher | 9 | 0 | 6500 | 4 |
| Robot | 12 | 100 | 4000 | 0 |
| Radio | 16 | 15 | 2300 | 0 |
| Muffled | 12 | 0 | 900 | 0 |

Operator behavior:

- `Voice Character` selects one immutable built-in character.
- `Character Strength` ranges from `0` to `100`.
- Strength `0%` resolves to Natural; strength `100%` resolves to the selected
  character target.
- Gain, Robot, and Pitch interpolate linearly. Lowpass interpolates
  logarithmically.
- Natural disables the strength control.
- The active voice label distinguishes built-in character, saved custom voice,
  unsaved advanced edits, and bypassed output.
- Manual advanced Gain, Pitch, Robot, or Lowpass edits mark the active voice as
  `Custom - Unsaved`.
- Saved custom voices continue to use the existing preset storage and
  validation path.
- Built-in character names and compatibility aliases cannot be overwritten or
  deleted as custom voices.
- `Bypass Effects` skips user voice effects without stopping processing,
  changing routing, changing selected devices, changing monitor state, or
  clearing runtime-failure bypass state.
- Bypass defaults off on every launch and is not persisted.
- `Reset Voice` selects Natural, sets default strength, turns bypass off, and
  preserves devices, monitor state, volumes, soundboard state, processing
  state, and routing state.
- The main content scrolls when needed so the default launch size remains usable
  on smaller displays.

Deferred character types:

- Formant-based voices.
- EQ or high-pass/band-pass based voices.
- Telephone-style voices.
- Identity-style voices.

These require additional DSP or product policy decisions and are intentionally
outside M7.0.

## Manual M7.0 Hardware Checklist

M7.0 live voice-character acceptance is complete. All required manual scenarios
passed after the evidence-based window-sizing correction, and no
voice-character parameter tuning was required.

Product presentation:

- Character controls clear: PASS.
- Character description readable: PASS.
- Character Strength understandable: PASS.
- Active Voice state visible: PASS.
- Bypass Effects discoverable: PASS.
- Reset Voice discoverable: PASS.
- Start and Stop obvious: PASS.
- Essential device controls accessible: PASS.
- Advanced Controls began collapsed: PASS.
- Technical diagnostics did not dominate normal use: PASS.
- Layout usable with no clipped or unreachable controls: PASS.

Character listening:

- Natural clear baseline: PASS.
- Natural had no unintended pitch, robot, or severe filtering: PASS.
- Deep clearly lower, darker, usable, and intelligible: PASS.
- Heavy Bass distinct from Deep, stronger, understandable, and honestly named:
  PASS.
- Higher clearly higher, usable, and free of harsh digital edge: PASS.
- Robot clearly robotic, intelligible for novelty use, and removable by
  switching back to Natural: PASS.
- Radio distinct from Robot and Muffled, intelligible, and honestly named:
  PASS.
- Muffled clearly dark and filtered, distinct from Radio, and still audible:
  PASS.

Live behavior:

- Rapid character switching while processing: PASS.
- No route restart during character changes: PASS.
- No stale previous effect after switching: PASS.
- No accumulated latency: PASS.
- Deep strength sweep `0/25/50/75/100`: PASS.
- Robot strength sweep `0/25/50/75/100`: PASS.
- Higher strength sweep `0/50/100`: PASS.
- Heavy Bass strength sweep `0/50/100`: PASS.
- `0%` matched Natural and `100%` reached the defined target: PASS.
- Labels and advanced values stayed synchronized: PASS.
- Metallic tail remained absent: PASS.
- Flutter/choppiness remained absent: PASS.
- Latency remained acceptable: PASS.

Bypass, reset, and soundboard:

- Bypass while running made microphone audio dry: PASS.
- Virtual mic, monitor, and routing remained active during bypass: PASS.
- Selected character, strength, and advanced values remained selected beneath
  bypass: PASS.
- Disabling bypass restored the prior effect state: PASS.
- Runtime failure telemetry remained separate from user bypass: PASS.
- Soundboard remained audible during bypass and was not incorrectly bypassed:
  PASS.
- Reset Voice while running restored Natural, turned bypass off, reset strength
  according to policy, and preserved devices, monitor state, monitor volume,
  soundboard volume, routing, and processing state: PASS.

Advanced and custom voice behavior:

- Advanced Controls began collapsed and expanded without altering audio: PASS.
- Expanded values matched the selected character and strength: PASS.
- Manual advanced edits changed active state to `Custom - Unsaved`: PASS.
- Built-in character definitions were not modified by manual edits: PASS.
- Reselecting a built-in restored canonical values: PASS.
- Save Current as Custom Voice succeeded: PASS.
- Saved custom voice restored exact values: PASS.
- Saved custom voice persisted after relaunch: PASS.
- Delete Custom Voice succeeded safely: PASS.
- Built-in characters remained protected from delete and name collision:
  PASS.

Persistence and regression:

- Selected character restored: PASS.
- Character strength restored: PASS.
- Devices, monitor state, and volumes restored: PASS.
- VoiceLab relaunched stopped: PASS.
- Bypass relaunched off: PASS.
- Advanced Controls began collapsed after relaunch: PASS.
- Refresh Devices while stopped: PASS.
- Refresh Devices disabled while running: PASS.
- Safe missing-device start failure, recovery, corrected retry, and no silent
  replacement: PASS.
- Microphone, virtual mic, monitor, monitor-disabled operation, Natural, Deep,
  Heavy Bass, Higher, Robot, Radio, Muffled, strength, bypass, reset, advanced
  controls, custom voices, persistence, refresh, soundboard, available hotkeys,
  Start, Stop, close, relaunch, and Signalsmith active status: PASS.

Observed tuning issues:

- None.

Observed UX issues:

- Initial window geometry warning and excessive minimum height were corrected
  before final acceptance.

Accepted limitations:

- Formant-based voices remain deferred.
- EQ or high-pass/band-pass based voices remain deferred.
- Telephone-style voices remain deferred.
- Identity-style voices remain deferred.

Not tested:

- Destructive device-enumeration failure: NOT TESTED; not required and not
  safely reproducible.
- Unconfigured preset hotkey paths: NOT TESTED where no preset hotkey was
  configured.

## Live Audio Meters

M7.1 Status: PASS.

M7.1 adds passive live meters for normal operator feedback. The meters observe
audio levels but never change gain, normalize audio, compress audio, gate audio,
control effects, control routing, start or stop processing, select devices, or
write settings.

Displayed meters:

- `Microphone Input`: raw microphone audio after capture and before effects.
- `Processed Voice`: microphone audio after the effect chain or bypass path and
  before soundboard mixing.
- `Output`: final virtual-microphone bus after soundboard mixing.

Monitor decision:

- A separate monitor reading is captured in the application snapshot only when
  monitor routing is enabled and the monitor bus is active.
- The primary UI does not show a fourth monitor meter in M7.1 because the
  monitor bus is derived from the same mixed output with monitor volume and
  stereo formatting. Route status remains the operator-facing monitor indicator.

Meter math:

- Peak uses `max(abs(samples))`.
- RMS uses `sqrt(mean(samples ** 2))`.
- dBFS uses `20 * log10(value)` with a defined floor.
- Display floor is `-60 dBFS`.
- Display ceiling is `0 dBFS`.
- Empty, NaN, and infinite samples fail safely to finite readings.
- Raw samples are never exposed to the UI.

Overload terminology:

- The UI uses `Overload`, not `Clipping`, because VoiceLab observes high level
  but cannot always prove where clipping occurred.
- Overload threshold is peak at or above `-1 dBFS`.
- Overload is latched in the UI for about `1.8` seconds so the operator can
  notice it, then clears automatically.

Signal-present policy:

- Signal threshold is approximately `-55 dBFS` RMS.
- Running with no current reading shows waiting state.
- Brief pauses remain quiet signal state.
- Sustained silence of about `1.5` seconds shows no-signal state.
- Speaking clears no-signal state immediately.
- Silence detection does not prove device disconnection and does not replace
  device-failure messages.

Cadence and retention:

- Audio callback publication is rate-limited to 25 snapshots per second.
- The meter monitor retains only the latest immutable snapshot.
- Each snapshot has a sequence number and capture timestamp.
- The UI polls through `ApplicationService.audio_level_snapshot()` every 50 ms.
- UI peak hold is about `0.8` seconds and then decays outside the audio
  callback.

Stage behavior:

- Character changes do not recreate the meter path.
- Character strength changes affect meters only when actual audio changes.
- During `Bypass Effects`, Input remains measured, Processed Voice measures the
  bypassed voice path, and Output remains measured.
- Soundboard playback appears on Output, not Microphone Input or Processed
  Voice.
- Stop, failed start, and startup failure reset or invalidate readings so stale
  running activity is not shown as current.

Known limitations:

- Block-level meter readings are not laboratory-grade.
- Meter values are not calibrated SPL.
- No LUFS measurement.
- No waveform or spectrum display.
- Display polling may miss very short transients.
- Post-clamp output readings cannot reveal exact pre-clamp magnitude.
- Silence detection does not prove device disconnection.
- Meter color and overload zones are operational guidance, not mastering
  standards.

Manual M7.1 live meter acceptance is complete. All manual scenarios passed
except the explicitly listed NOT TESTED hardware-acceptance coverage gaps.

Manual M7.1 accepted results:

- Baseline speech meter response: PASS.
- Meter decay: PASS.
- Sustained silence/no-signal behavior: PASS.
- Quiet speech: PASS.
- Character switching: PASS.
- Character strength response: PASS.
- Bypass Effects attribution: PASS.
- Soundboard-only attribution: PASS.
- Voice plus soundboard attribution: PASS.
- Monitor-disabled operation: PASS.
- Stop clears or invalidates active meter state: PASS.
- Repeated Start/Stop: PASS.
- Device refresh behavior: PASS.
- Window scrolling and layout: PASS.
- Close while running: PASS.
- Relaunch behavior: PASS.
- Metallic tail remained absent: PASS.
- Flutter remained absent: PASS.
- Latency remained acceptable: PASS.
- Meters made no audible difference: PASS.

M7.1 hardware-acceptance coverage gaps:

- Input overload: NOT TESTED.
- Processed/output overload: NOT TESTED.
- Failed Start and retry: NOT TESTED.

Accepted limitation:

- The Output meter observes the existing post-clamp bus after the mixer's
  `0.95` clamp and cannot display exact pre-clamp magnitude beyond that clamp.

Do not treat M7.1 as complete overload or failed-start hardware coverage until
the NOT TESTED scenarios above are exercised.

Manual M7.1 checklist:

- Baseline with normal microphone, VB-CABLE output, monitor enabled, Natural,
  and processing started: meters leave Stopped, Input reacts to speech,
  Processed reacts to speech, Output reacts to speech, meters decay during
  silence, normal speech does not constantly overload, UI remains responsive,
  and audio remains clean.
- No signal: brief pauses do not immediately show failure, sustained silence
  shows quiet/no-signal state, speaking clears it immediately, and route remains
  running.
- Input overload: a safe loud input reports high level or overload, indication
  is visible long enough to notice, indication clears, VoiceLab does not alter
  gain, processing does not stop, and no crash occurs.
- Processed overload: high-gain custom state shows processed/output overload
  truthfully, clears automatically, and remains passive.
- Character changes: Natural, Deep, Heavy Bass, Higher, Robot, Radio, and
  Muffled keep meters updating with no route restart, frozen meter, stale
  stage, metallic tail, flutter, or unacceptable latency.
- Strength sweep: Deep and Robot sweeps reflect actual signal changes and do
  not move merely because the slider moves while silent.
- Bypass: Input remains active, Processed remains truthful, Output remains
  active, character state remains intact, and no stream restart occurs.
- Soundboard: while silent, soundboard appears on Output and is not
  misattributed to Microphone Input or Processed Voice.
- Monitor disabled: Input, Processed, and Output still work and route state is
  accurate.
- Stop and restart: meters promptly show Stopped, stale activity clears, meters
  recover after restart, and no duplicate timer activity appears.
- Failure recovery: safe missing-selection failure does not show stale running
  activity, existing failure message remains authoritative, corrected retry
  restores meters.
- Final regression: microphone, virtual mic, monitor, monitor disabled, all
  characters, strength, bypass, reset, custom voices, soundboard, settings,
  device refresh, failed-start retry, Start, Stop, close, relaunch, launches
  stopped, Signalsmith active, metallic tail absent, flutter absent, latency
  acceptable, and meters do not audibly affect processing.

## Device Failure Recovery

M6.3 normalizes startup and routing failures into stable categories before they
reach the primary UI. User-facing messages explain the failed role and practical
next action, while backend details remain in telemetry.

Supported failure categories:

- missing selection;
- device not found;
- device open failed;
- unsupported configuration;
- route startup failed;
- partial-start cleanup failed;
- unknown device error.

Affected roles are input, virtual output, monitor output, or the general route.

After a failed start, processing is not shown as running, routes are not shown
as active, Start Processing is available again, Stop Processing is disabled,
and the warning remains visible until a new start attempt replaces it or a
successful start clears it. VoiceLab does not silently choose replacement
devices, disable monitor output, or retry automatically.

Device lists are still loaded at UI startup. M6.3 does not add automatic
hot-plug monitoring or a manual device refresh action.

### M6.3 Manual Device-Recovery Acceptance

Manual M6.3 hardware acceptance result: PASS.

- Monitor unavailable: understandable failure message, correct device role,
  stopped processing state, inactive routes, recovered Start/Stop controls,
  responsive UI, and retry after disabling or changing monitor all passed.
- Microphone unavailable: understandable failure message, correct device role,
  control recovery, and retry passed.
- Stale device after relaunch: understandable failure message, no silent
  substitution, and retry passed.
- Virtual microphone unavailable: understandable failure message, correct device
  role, appropriate VB-CABLE guidance, and retry after restoration passed.
- Exclusive/open failure: NOT TESTED manually; automated generic-open-failure
  coverage passed.
- Normal regression passed for startup, virtual microphone, monitor, pitch
  `+4`, pitch `-4`, soundboard, stop, close, relaunch, metallic tail absent,
  flutter absent, and acceptable latency.

## Troubleshooting

- If Signalsmith is missing, rebuild with the active virtual environment and
  verify `pybind11` and MSVC Build Tools are installed.
- If rebuild fails with a locked `.pyd`, close VoiceLab and confirm no
  `main.py` process is still running.
- If device startup fails, verify microphone, virtual mic, and monitor device
  IDs are available in the UI device lists.
- If a connected or enabled device is missing from the selectors while stopped,
  click `Refresh Devices`.
- If a previously selected device was disconnected or disabled, click
  `Refresh Devices`, confirm the selector is cleared, then choose a replacement
  explicitly.
- If monitor startup fails, select another monitor output or uncheck
  `Enable monitor output`, then retry.
- If hotkeys fail, VoiceLab should continue running and report the setup failure
  through status/telemetry.

## Release Preparation

Before building a release package:

1. Close all running VoiceLab instances.
2. Rebuild the native backend with the exact release interpreter.
3. Verify Signalsmith status is active.
4. Include the matching generated `.pyd` in the release/package artifact.
5. Do not commit the generated `.pyd`.

## Manual RC1 Hardware Smoke Checklist

Current documented result: PASS. Final M5.6 manual hardware acceptance is
complete and no RC1 blockers were found.

Tested environment:

- Windows 11.
- Python 3.13.3.
- AMD64 / 64-bit runtime.
- pybind11 3.0.4.
- Signalsmith native module active.
- Virtual microphone and monitor processed-output paths confirmed through Steam
  voice test.

Automated backend verification:

- Signalsmith `available=True`.
- Pitch backend `signalsmith`.
- Backend status `active`.
- Backend telemetry readable.
- No fallback active.

Startup and devices:

- VoiceLab launches normally: PASS.
- Microphone input available: PASS.
- Virtual microphone available: PASS.
- Monitor available: PASS.
- Backend telemetry through UI: NOT TESTED; telemetry is not currently visible
  in the application.
- Unexpected fallback warning through UI: NOT TESTED; backend status is not
  currently visible in the application.
- Initial telemetry through UI: NOT TESTED; telemetry is not currently visible
  in the application.
- Starting processing: PASS.

Treat missing UI telemetry visibility as deferred usability work, not an RC1
failure, because automated verification confirmed the active Signalsmith
backend and no fallback.

Core audio path:

- Dry voice: PASS.
- Gain: PASS.
- Lowpass: PASS.
- Robot: PASS.
- Pitch `+4`: PASS.
- Pitch `-4`: PASS.
- Preset switching while processing: PASS.
- Live pitch changes while processing: PASS.
- Soundboard: PASS.
- Virtual microphone processed output: PASS.
- Monitor processed output: PASS.

Subjective acceptance:

- Metallic tail: ABSENT.
- Flutter/choppiness: ABSENT.
- Latency: ACCEPTABLE.
- Former soundboard two-stage behavior: NOT REPRODUCED.

Runtime stability:

- Duration: 30 minutes.
- Crash: NO.
- Stream loss: NO.
- Runaway/increasing latency: NO.
- Progressive distortion: NO.
- Repeated dropout: NO.
- Frozen UI: NO.
- Lost command response: NO.
- Additional notes: None.

Shutdown and relaunch:

- Stop processing normally: PASS.
- Close after stopping: PASS.
- Terminal prompt returns: PASS.
- Relaunch: PASS.
- Start processing after relaunch: PASS.
- Close while processing remains active: PASS.
- Terminal prompt returns after active close: PASS.
- No native-module lock remained after close: PASS.
- Native Signalsmith rebuild after close: PASS.

The successful rebuild copied:

```text
voice_lab/effects/_signalsmith_pitch.cp313-win_amd64.pyd
```

This confirms the application released the native module after shutdown.

Pitch guidance:

- `+/-4` semitones: recommended normal range.
- `+/-8` semitones: usable but obviously processed.
- `+/-12` semitones: intentionally extreme.

## Manual M6.4 Hardware Checklist

M6.4 Status: PASS.

Manual M6.4 live hardware acceptance is complete. All applicable manual
checklist items passed.

Live device-refresh acceptance:

- Baseline refresh preserved the same actual devices.
- Newly connected input and output devices appeared without relaunching.
- Unselected removed devices disappeared without disturbing current selections.
- Removed selected microphone, monitor, and virtual microphone selections were
  cleared.
- No replacement device was silently selected.
- Monitor enabled state remained explicit.
- VB-CABLE reappeared after restoration and manual refresh.
- `Refresh Devices` was disabled while processing.
- `Refresh Devices` became available again after stopping and after failed
  starts.
- Recovery and corrected retry succeeded.
- Identity preservation behaved correctly during observed device-list changes.
- Duplicate ambiguity: NOT TESTED; not safely reproducible.
- Forced enumeration failure: NOT TESTED; not safely reproducible.

Normal M6.4 regression:

- Normal microphone operation: PASS.
- Virtual microphone operation: PASS.
- Monitor operation: PASS.
- Monitor-disabled operation: PASS.
- Dry voice: PASS.
- Gain: PASS.
- Lowpass: PASS.
- Robot: PASS.
- Pitch `0`: PASS.
- Pitch `+4`: PASS.
- Pitch `-4`: PASS.
- Presets: PASS.
- Soundboard: PASS.
- Start: PASS.
- Stop: PASS.
- Close: PASS.
- Relaunch: PASS.
- Metallic tail: ABSENT.
- Flutter/choppiness: ABSENT.
- Latency: ACCEPTABLE.

Connected device appears:

1. Launch VoiceLab while stopped.
2. Connect or enable a disposable USB/Bluetooth input or output.
3. Click `Refresh Devices`.
4. Confirm the device appears without relaunching.
5. Confirm existing unrelated selections remain intact.

Disconnected selected device:

1. Select a disposable device while stopped.
2. Disconnect or disable it.
3. Click `Refresh Devices`.
4. Confirm its selector is cleared.
5. Confirm no replacement is selected.
6. Select a valid replacement manually.
7. Start successfully.

Index-change safety:

1. Note a selected device.
2. Connect or disconnect another device that may change enumeration.
3. Click `Refresh Devices`.
4. Confirm VoiceLab preserves the correct device by identity rather than by
   numeric index alone.

Refresh failure:

- Test only if safely reproducible; otherwise record `NOT TESTED`.

Regression:

- Normal microphone start.
- Virtual microphone output.
- Monitor output.
- Monitor disabled mode.
- Pitch `0`.
- Pitch `+4`.
- Pitch `-4`.
- Presets.
- Soundboard.
- Stop.
- Close.
- Relaunch.
- Metallic tail absent.
- Flutter absent.
- Latency acceptable.

## Manual M6.5 Hardware Checklist

M6.5 Status: PASS.

Manual M6.5 live operator-settings acceptance is complete. All required manual
scenarios passed with no issues, and no implementation correction was required.

Clean first launch:

- First launch without `settings.json` opened normally.
- Input, virtual microphone, and monitor selectors began unselected.
- Processing did not start automatically.
- No unrelated first-listed devices were silently selected.
- UI remained responsive.
- First-run behavior was understandable.

Normal persistence:

- Selected microphone restored after restart.
- Selected VB-CABLE virtual output restored.
- Selected monitor output restored.
- Monitor-enabled state restored.
- Monitor volume restored.
- Soundboard volume restored.
- Selected preset and its parameters restored.
- VoiceLab relaunched stopped.
- Normal processing worked after explicit Start.

Monitor-disabled persistence:

- Monitor-disabled state persisted.
- Virtual-microphone-only processing worked.
- Route status did not claim monitor was active.

Missing saved-device behavior:

- Unavailable saved device was not silently replaced.
- Unavailable role remained unselected.
- Guidance was understandable.
- Explicit replacement worked.
- Reconnect and `Refresh Devices` recovery worked.

Final M6.5 audio regression:

- Microphone: PASS.
- Virtual mic: PASS.
- Monitor: PASS.
- Effects: PASS.
- Pitch `0`: PASS.
- Pitch `+4`: PASS.
- Pitch `-4`: PASS.
- Presets: PASS.
- Soundboard: PASS.
- Start: PASS.
- Stop: PASS.
- Close: PASS.
- Relaunch: PASS.
- Metallic tail: ABSENT.
- Flutter/choppiness: ABSENT.
- Latency: ACCEPTABLE.

Optional destructive/error scenarios:

- Malformed settings file: NOT TESTED - automated coverage passed.
- Empty/wrong-root settings file: NOT TESTED - automated coverage passed.
- Unsupported future schema: NOT TESTED - automated coverage passed.
- Save failure: NOT TESTED - automated coverage passed.

Persistence across restart:

1. Select normal microphone.
2. Select VB-CABLE virtual output.
3. Select monitor output.
4. Enable monitor.
5. Set monitor and soundboard volumes.
6. Select a preset.
7. Close VoiceLab normally.
8. Relaunch.
9. Confirm all settings restore and processing remains stopped.

Missing saved microphone:

1. Save a disposable microphone as selected.
2. Close VoiceLab.
3. Disconnect it.
4. Relaunch.
5. Confirm microphone selection is empty, no replacement is selected, guidance
   is understandable, and reconnect plus `Refresh Devices` can restore the same
   identity if it resolves uniquely.

Missing saved monitor:

1. Save monitor enabled with a disposable monitor device.
2. Close VoiceLab.
3. Disconnect it.
4. Relaunch.
5. Confirm monitor remains enabled, monitor selection is empty, Start requires
   selecting a monitor or disabling monitoring, and no silent substitution
   occurs.

Changed enumeration index:

- Where observable, reconnect devices in a different order, relaunch, and
  confirm the same identity restores at its new index.
- If index movement is not observed, automated coverage is sufficient.

Corrupt settings:

- With a backed-up disposable settings file, confirm malformed JSON does not
  prevent application launch, then restore the valid file.

Regression:

- Normal microphone.
- Virtual mic.
- Monitor.
- Monitor-disabled operation.
- Dry voice.
- Effects.
- Pitch.
- Presets.
- Soundboard.
- Start/Stop.
- Close/relaunch.
- Metallic tail absent.
- Flutter absent.
- Latency acceptable.
