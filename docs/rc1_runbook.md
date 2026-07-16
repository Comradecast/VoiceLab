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

## Custom Voice Management

M7.2 Status: PASS.

M7.2 improves saved custom voice management without changing DSP, routing,
devices, meters, soundboard behavior, or built-in character targets.

Behavior:

- The primary voice selector separates built-in voices from custom voices with
  non-selectable section labels.
- Built-in voices remain Natural, Deep, Heavy Bass, Higher, Robot, Radio, and
  Muffled.
- Custom voices continue to load from the existing `presets.json` mapping.
- Selected built-in/custom voice and character strength continue to use the
  existing operator settings fields.
- `Rename Custom Voice` renames a saved custom voice.
- `Duplicate Custom Voice` duplicates a saved custom voice under a new name.
- Saved custom voice deletion requires confirmation.
- Saving over an existing custom voice requires explicit overwrite
  confirmation.
- Built-in names and `Custom - Unsaved` state names are reserved.
- Empty or whitespace-only custom voice names are rejected.
- Custom-name conflicts are rejected unless the operator explicitly confirms an
  overwrite for a save operation.
- `Custom - Unsaved` advanced edits prompt before selecting another voice or
  Reset Voice discards them.
- Cancel keeps the current unsaved parameters and active state unchanged.
- Discard performs the requested voice change or reset once.
- Bypass remains separate from voice identity and is not represented as a
  custom voice.

Manual M7.2 live UI acceptance is complete with documented limits. Luke
confirmed that every M7.2 scenario he could practically test passed. No live
failure was observed. Untested scenarios are not represented as passed.

Manual M7.2 PASS results:

- Built-in/custom selector distinction: PASS.
- Custom voice save: PASS.
- Rename Custom Voice: PASS.
- Duplicate Custom Voice: PASS.
- Delete Custom Voice confirmation: PASS.
- Overwrite confirmation: PASS.
- Unsaved-change Cancel behavior: PASS.
- Unsaved-change Discard behavior: PASS.
- Relaunch persistence: PASS.
- Application launches stopped: PASS.
- Processing Start/Stop regression: PASS.
- Soundboard regression: PASS.
- Meter regression: PASS.
- Window scrolling/layout: PASS.
- Close and relaunch: PASS.
- Metallic tail remained absent: PASS.
- Flutter remained absent: PASS.
- Latency remained acceptable: PASS.

Manual M7.2 NOT TESTED:

- Any scenario not practically executed by Luke remains NOT TESTED.
- No additional specific live failure scenario was reported.

Automated coverage debt from the pre-acceptance audit:

- Rename empty-string rejection: AUTOMATED COVERAGE DEBT.
- Exact em dash `Custom — Unsaved` reserved-name rejection: AUTOMATED
  COVERAGE DEBT.
- Rename conflict unchanged-data assertion: AUTOMATED COVERAGE DEBT.
- Overwrite unrelated custom voice unchanged assertion: AUTOMATED COVERAGE
  DEBT.
- Advanced manual change direct `Custom - Unsaved` pre-reset assertion:
  AUTOMATED COVERAGE DEBT.
- Cancelled Reset preserving unsaved selection and parameters: AUTOMATED
  COVERAGE DEBT.
- Confirmed selector discard executing exactly once: AUTOMATED COVERAGE DEBT.
- Programmatic selector rebuild false-prompt prevention: AUTOMATED COVERAGE
  DEBT.
- Startup restoration false-prompt condition: AUTOMATED COVERAGE DEBT.
- Section header disabled/non-selectable model behavior direct assertion:
  AUTOMATED COVERAGE DEBT.
- Rename/Duplicate/Delete disabled for `Custom - Unsaved`: AUTOMATED COVERAGE
  DEBT.

These coverage-debt items are not known product failures and did not block live
operator acceptance.

Manual M7.2 checklist:

- Built-in/custom selector distinction.
- Select every built-in voice.
- Select an existing custom voice.
- Save a new custom voice.
- Rename Custom Voice.
- Rename Cancel.
- Duplicate Custom Voice.
- Duplicate Cancel.
- Delete custom voice Cancel.
- Confirm custom voice deletion.
- Built-in Rename/Delete protection.
- Custom-name conflict behavior.
- Overwrite Cancel.
- Overwrite confirmation.
- Unsaved selector-change Cancel.
- Unsaved selector-change Discard.
- Unsaved Reset Cancel.
- Unsaved Reset Discard.
- Bypass with built-in voice.
- Bypass with saved custom voice.
- Bypass with `Custom - Unsaved`.
- Character strength behavior.
- Advanced-control behavior.
- Relaunch persistence.
- Application still launches stopped.
- Processing Start/Stop regression.
- Soundboard regression.
- Meter regression.
- Window scrolling/layout.
- Close and relaunch.
- Metallic tail absent.
- Flutter absent.
- Latency acceptable.

## Input Processing Foundation

M8.0 Status: PASS.

M8.0 adds a default-disabled global input-processing foundation for the
microphone voice path. These settings are operator settings, not custom voice
parameters, and are not stored in `presets.json`.

Signal order:

- Raw Microphone.
- High-Pass Filter.
- Noise Gate.
- Compressor.
- Pitch Shift.
- Robot.
- Lowpass.
- Gain.
- Voice-path Limiter.
- Mixer.
- Router outputs.

Ownership and limitations:

- AudioEngine owns the processors and existing character effects.
- Mixer still owns soundboard mixing and final bus clipping.
- Router still owns route delivery.
- UI updates settings only through ApplicationService.
- The Limiter acts on the processed voice path before Mixer. It does not limit
  soundboard audio or the final mixed Output bus.
- Output meter still observes the existing post-clamp final mixed bus.
- Microphone Input meter remains raw pre-processing.
- Processed Voice meter reflects active input processing, character effects,
  and the voice limiter.
- Bypass Effects uses the existing bypass path and does not erase
  input-processing settings.

Controls and ranges:

- High-Pass Filter: Enabled, Cutoff 40 Hz through 200 Hz, default 80 Hz,
  disabled.
- Noise Gate: Enabled, Threshold -70 dBFS through -20 dBFS, Release 40 ms
  through 1000 ms, defaults -45 dBFS and 180 ms, disabled. Internally this is
  a conservative downward expander with fixed attack, hold, ratio, and
  attenuation floor.
- Compressor: Enabled, Threshold -40 dBFS through 0 dBFS, Ratio 1.0:1 through
  10.0:1, Attack 1 ms through 100 ms, Release 20 ms through 1000 ms, Makeup
  Gain 0 dB through +12 dB, defaults -18 dBFS, 3.0:1, 10 ms, 150 ms, 0 dB,
  disabled.
- Limiter: Enabled, Ceiling -12 dBFS through -0.5 dBFS, Release 20 ms through
  500 ms, defaults -1 dBFS and 80 ms, disabled.

Manual M8.0 live acceptance is complete with one explicit waived coverage gap.

Live correction note:

- Initial M8.0 live launch found that the single-column scrolling layout was
  confusing and made Input Processing look like a global checkbox.
- The operator could not determine whether High-Pass, Noise Gate, Compressor,
  or Limiter were audibly acting.
- The corrected layout uses a persistent transport area plus Voice, Input
  Processing, Routing, Soundboard, and Diagnostics tabs.
- Start Processing, Stop Processing, Bypass Effects, current processing state,
  current route state, and active voice remain visible outside the tabs.
- Input Processing is a tab, not a global DSP enable checkbox.
- Each processor panel shows its own Enabled control, current values and
  units, OFF/ENABLED state, and passive activity feedback.
- Activity feedback is latest-state only: High-Pass reports active cutoff,
  Noise Gate reports Open/Reducing and gain reduction, Compressor reports gain
  reduction, and Limiter reports gain reduction plus ceiling-hit indication.
- Deterministic activation evidence confirmed measurable response at diagnostic
  settings: High-Pass 50 Hz RMS attenuation to about 6.2% with 1 kHz preserved
  at about 99.9%; Noise Gate below-threshold RMS to about 3.2% with
  above-threshold passage unchanged; Compressor loud-block reduction about
  22.5 dB with quiet material unchanged; Limiter over-ceiling peak constrained
  to the -12 dBFS ceiling with safe material unchanged.
- M8.0 live audible and hardware acceptance was repeated after this correction.

Manual M8.0 PASS results:

- Revised tabbed layout and navigation: PASS.
- Persistent transport controls: PASS.
- Processors-disabled baseline transparency: PASS.
- Existing voice behavior remains acceptable: PASS.
- High-Pass audible activation: PASS.
- High-Pass is useful and clearly affects low-frequency content: PASS.
- Noise Gate audible activation: PASS.
- Noise Gate is useful with practical settings: PASS.
- Compressor audible activation: PASS.
- Compressor behaves as expected with practical settings: PASS.
- Limiter audible activation: PASS.
- Limiter is particularly useful and appreciated: PASS.
- Combined normal processing chain: PASS.
- Bypass Effects behavior and recovery: PASS.
- Reset Voice/Input Processing separation: PASS.
- Routing and normal application behavior: PASS.
- Processor activity visibility: PASS.
- No reported metallic tail: PASS.
- No reported flutter: PASS.
- Latency remains acceptable: PASS.
- No observed DSP activation defect: PASS.

Practical starting settings accepted as useful:

- High-Pass: enabled, 80-100 Hz.
- Noise Gate: approximately -45 dBFS, approximately 200 ms release.
- Compressor: threshold -18 dBFS, ratio 3:1, attack 10 ms, release 150 ms,
  makeup gain 0 to +2 dB.
- Limiter: ceiling -1 dBFS, release 80 ms.

The extreme diagnostic settings were used only to prove audible activation and
are not normal recommended defaults.

Manual M8.0 NOT TESTED:

- 15-minute combined-processing stability run: NOT TESTED - waived by Luke as
  non-blocking.

No instability was observed during practical testing. The omitted timed run is
not represented as completed, no known product failure remains, and prior
lifecycle acceptance plus fixed-size bounded processor-state evidence support
treating the omitted run as non-blocking.

M8.0 live acceptance checklist:

Baseline Compatibility:

- Application launches stopped.
- All new processors default disabled on legacy settings.
- Baseline Natural voice unchanged with processors disabled.
- Existing characters remain distinct.
- Metallic tail absent.
- Flutter absent.
- Latency remains acceptable.
- No audible difference when all four processors are disabled.

High-Pass Filter:

- Enable while running.
- Disable while running.
- Cutoff sweep.
- Low-frequency rumble reduction.
- Normal speech remains intelligible.
- No clicks during enable/disable.
- Persistence after relaunch.

Noise Gate:

- Enable while running.
- Disable while running.
- Background noise attenuation.
- Quiet speech remains audible.
- Initial consonants are not cut off.
- Ordinary pauses do not chatter.
- Release sweep.
- Threshold sweep.
- Persistence after relaunch.

Compressor:

- Enable while running.
- Disable while running.
- Quiet/loud speech consistency.
- Threshold sweep.
- Ratio sweep.
- Attack sweep.
- Release sweep.
- Makeup gain.
- No obvious pumping under ordinary settings.
- No crackle or discontinuity.
- Persistence after relaunch.

Limiter:

- Enable while running.
- Disable while running.
- Loud voice peak control.
- Ceiling sweep.
- Release sweep.
- No crackle.
- No persistent gain reduction after speech stops.
- Persistence after relaunch.

Combined Chain:

- All four enabled together.
- Switch every built-in voice.
- Select a saved custom voice.
- Edit advanced voice controls.
- Character strength sweep.
- Bypass Effects.
- Disable bypass and recover exact configuration.
- Reset Voice does not reset input processing.
- Reset Input Processing does not reset voice.
- Reset Input Processing Cancel.
- Reset Input Processing confirmation.
- Voice plus soundboard.
- Soundboard-only attribution.
- Monitor enabled.
- Monitor disabled.
- Meters remain truthful.
- Input meter remains raw.
- Processed meter reflects processing.
- Output meter includes soundboard.

Lifecycle and Regression:

- Repeated Start/Stop.
- Change processor parameters while running.
- Device refresh while stopped.
- Failed Start and retry where practical.
- Stop clears active meter state.
- Close while running.
- Relaunch.
- Settings restoration.
- Window scrolling/layout.
- 15-minute combined-processing stability: NOT TESTED - waived by Luke as
  non-blocking.
- No increasing latency.
- No metallic tail.
- No flutter.
- No new audible block boundaries.

## Real-Time Formant Backend Prototype

M8.1 Status: PASS.

M8.1 adds an isolated experimental formant-shift prototype for local evidence
gathering only. Launch it with:

```powershell
.\.venv\Scripts\python.exe main.py --formant-lab
```

Normal launch remains:

```powershell
.\.venv\Scripts\python.exe main.py
```

Normal launch must not show Formant Lab controls and must preserve the
production chain:

- High-Pass.
- Noise Gate.
- Compressor.
- Pitch Shift.
- Robot.
- Lowpass.
- Gain.
- Limiter.

Formant Lab launch replaces only the Pitch Shift stage with:

- Experimental Pitch/Formant.

Prototype controls:

- Enable Prototype.
- Prototype A/B Bypass.
- Prototype Pitch, -12.0 through +12.0 semitones.
- Formant, -12.0 through +12.0 semitones.
- Reset Prototype.

Automated M8.1 evidence:

- Local native Signalsmith wrapper exposes `set_formant_semitones`.
- Local native Signalsmith wrapper exposes `set_formant_factor`.
- Python backend wrapper exposes both formant controls.
- Formant semitone validation rejects non-finite and out-of-range values.
- Formant factor conversion is `2 ** (formant_semitones / 12)`.
- Normal effect-chain order remains unchanged.
- Formant Lab effect-chain order is isolated to explicit prototype launch.
- Normal service launch does not expose Formant Lab state.
- Prototype service launch exposes Formant Lab state.
- Prototype updates and reset are session-only.
- Prototype runtime updates use one immutable whole-configuration snapshot.
  Validation happens before the callback, the active snapshot is replaced by
  one reference, and the callback-side effect reads one snapshot at the start
  of each process block. There is no callback lock, queue, history, stream
  restart, device reopen, route interruption, settings write, preset write, or
  native backend reconstruction for ordinary Formant Lab parameter changes.
- Deterministic vowel-like probes preserve estimated F0 under formant-only
  changes.
- Deterministic vowel-like probes move the spectral envelope down for negative
  formant settings and up for positive formant settings.
- Prototype output remains finite.
- Prototype backend telemetry reports Signalsmith latency/status metadata.

Live perceptual findings recorded before final closeout:

- Neutral operation is usable.
- Subtle formant changes can be useful.
- Approximately +/-0.5 to +/-2 semitones is the plausible natural-character
  range.
- Approximately +/-3 and beyond commonly sounded unnatural.
- Pitch plus formant alone is insufficient for intended production character
  targeting.
- Pitch +3 / formant +1 sounded like a man attempting to imitate a woman.
- The backend remains viable as an M8.2 character-transformation component.
- Raw standalone formant controls are not sufficient for production character
  targeting.

Final M8.1 live acceptance results:

- Normal launch unchanged: PASS.
- Normal mode launches stopped: PASS.
- Prototype launches stopped: PASS.
- Neutral pitch 0 / formant 0 sound: PASS.
- Subtle formant approximately +/-1 is audible and usable: PASS.
- Live pitch/formant parameter changes: PASS.
- Prototype A/B Bypass preserves values: PASS.
- Stop/Start recovery: PASS.
- Close while processing: PASS.
- Prototype relaunch: PASS.
- Normal relaunch remains unchanged: PASS.
- No crash: PASS.
- No severe burst: PASS.
- Latency remains acceptable: PASS.

Parameter-change artifact:

- Severe clicks or bursts: NONE.
- Minor transition artifact: OBSERVED.
- Exact observation: when changing the formant rapidly toward one extreme or
  the other, there can be a brief period where the output sounds as though
  prototype bypass is active before the formant processing settles and becomes
  audible again.
- Classification: MINOR / NON-BLOCKING.
- The artifact was not persistent, did not crash processing, did not alter
  settings, did not create growing latency, and was associated with extreme
  live parameter changes.
- Luke can avoid it by staying away from extreme settings.
- No correction is required before beginning the next epic.
- The artifact remains known DSP transition debt.

Accepted M8.1 backend decision:

- Signalsmith provides genuine independent formant control.
- Formant-only shifts preserve fundamental pitch substantially.
- Pitch and formant run in one native Signalsmith processing stage.
- Formant processing adds no measured latency beyond the accepted production
  pitch path.
- Normal production mode remains isolated.
- Immutable whole-parameter snapshot replacement prevents mixed per-block
  pitch/formant configurations.
- No callback lock, queue, history, stream restart, device reopen, or
  persistence change was introduced.
- Native lifecycle and `.pyd` release/rename/relaunch checks passed.
- The backend is accepted as a bounded component for the next
  adaptive/target-based character-transformation engine.

Perceptual closeout:

- Plausible natural formant range is approximately +/-0.5 to +/-2 semitones.
- Approximately +/-3 begins to sound unnatural.
- Larger shifts are primarily experimental or special-effect territory.
- Pitch and formant alone are insufficient for accurate intended-character
  transformation.
- Pitch +3 / formant +1 still sounded like a man attempting to imitate a
  woman.
- The next epic must target complete character transformation rather than
  expose more isolated offsets.
- Production integration of raw formant values into existing characters remains
  deferred. Do not represent the full +/-12 prototype range as
  production-quality.

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

## M9.0 Passive Source Voice Analysis Lab

M9.0 Status: PASS.

Launch:

```powershell
.\.venv\Scripts\python.exe main.py --voice-analysis-lab
```

Scope:

- M9.0 is an experimental passive-analysis lab.
- Normal launch remains unchanged and Source Analysis is absent in normal mode.
- The analyzer observes raw microphone input at the same conceptual point as
  the Microphone Input meter: after capture, before AudioEngine, Mixer,
  soundboard, monitor routing, and virtual-output routing.
- Analysis values are session-only and are not written to `settings.json` or
  `presets.json`.
- The analyzer does not alter audio, DSP settings, routes, devices, meters,
  soundboard behavior, character targets, or Signalsmith configuration.
- The analyzer is target-neutral. It measures acoustic properties only and
  must not be treated as identity, gender, age, or quality classification.
- M9.0 does not create or export a source-profile file.
- Analysis values are intentionally session-only.
- The bounded source profile exists only in memory.
- Nothing is written to `settings.json` or `presets.json`.
- Reset, Stop/restart, and relaunch begin fresh transient analysis state
  according to the implemented lifecycle.
- No source-profile file was expected during live acceptance.
- Future target-character processing will consume the live in-memory profile
  directly. Persistent analysis export remains deferred diagnostics scope.

Implementation notes:

- Callback work is bounded publication to a one-slot `SourceAnalysisTap`.
- Expensive F0, FFT, spectral, resonance, and profile calculations run on the
  `SourceVoiceAnalyzer` worker outside the callback.
- Backlog is prevented by newest-wins replacement; dropped replacements and
  cadence-skipped frames are visible in Runtime Status.
- Profile retention is fixed at 240 readings: 20 Hz for 12 seconds.
- Profile readiness requires at least 2 seconds of reliable voiced speech.
- F0 supported practical range is 60 Hz through 500 Hz.
- Spectral ratios use total 80 Hz through 10 kHz speech-region energy and
  truncate bands at Nyquist.
- Bands: chest 80-300 Hz, low-mid 300-900 Hz, presence 2-5 kHz, brightness
  5-8 kHz, sibilance 5-10 kHz.
- Spectral tilt is a dB high/low energy-ratio metric.
- Resonance estimates are approximate smoothed-envelope peak estimates. Invalid
  or unreliable frames show unavailable values rather than false precision.
- `spectral_tilt_db` is an energy-ratio index, not a fitted dB-per-octave
  slope.
- F1/F2/F3 estimates are weak descriptors only and are not approved as direct
  automatic control inputs.
- The analyzer is accepted as the source-profile foundation for feminine,
  masculine, deep-masculine, giant, and other target profiles.

Final live M9.0 accepted results:

- Normal launch unchanged: PASS.
- Source Analysis absent from normal mode: PASS.
- Voice Analysis Lab launch: PASS.
- Application launches stopped: PASS.
- Start activates analysis: PASS.
- Stop/reset behavior: PASS.
- Repeated Start/Stop: PASS.
- Close/relaunch behavior: PASS.
- Audio transparency: PASS.
- No added audible latency: PASS.
- Metallic tail absent: PASS.
- Flutter absent: PASS.
- No crackle or new audible block boundaries: PASS.
- Normal speech F0 behavior appears plausible: PASS.
- Lower and higher voice changes are reflected: PASS.
- Quiet/loud speech behavior appears plausible: PASS.
- Sustained vowels collect stable data: PASS.
- Rapid speech continues updating: PASS.
- Silence/unvoiced behavior appears correct: PASS.
- Confidence behavior appears plausible: PASS.
- Rolling profile collects and reaches useful state: PASS.
- Median and pitch-range measurements appear plausible: PASS.
- Spectral descriptors respond plausibly: PASS.
- Analyzed/skipped/dropped status behaves normally: PASS.
- No UI freezing: PASS.
- No analyzer failure: PASS.
- Data collection appears fully functional in practical use: PASS.

Accepted technical conclusions:

- Raw microphone analysis occurs before DSP and Mixer.
- Analysis does not alter audio.
- Callback publication uses a stable owned copy.
- Analysis runs outside the callback.
- Mailbox capacity remains one frame.
- Rolling profile remains bounded to 240 scalar readings.
- The F0 estimator is accepted for practical source profiling.
- Spectral energy ratios are accepted as comparative descriptors.
- No identity or gender classification is performed.

Known non-blocking debt:

- Real-hardware close-while-processing was not separately isolated as a
  dedicated test beyond practical live use.
- Lock-free mailbox diagnostic counters may rarely undercount or lose a
  pending frame during a thread interleaving.
- Approximate resonance estimates remain weak descriptors.
- Lower-sample-rate Nyquist truncation lacks a dedicated focused test.
- These are not known product failures and do not block M9.0 acceptance.

Next milestone direction:

- The next epic is the target-based character-transformation engine.
- The first target work must support both feminine and deep-masculine
  directions.

Live M9.0 acceptance checklist:

Isolation and lifecycle:

- Normal launch unchanged.
- Source Analysis absent in normal mode.
- Analysis-lab launch works.
- Source Analysis tab visible.
- Application launches stopped.
- Start activates analysis.
- Stop clears active status.
- Repeated Start/Stop.
- Close while processing.
- Relaunch analysis lab.
- Relaunch normal mode.

Audio transparency:

- Analysis enabled produces no audible difference.
- No added latency.
- No metallic tail.
- No flutter.
- No crackle.
- No new block boundaries.
- Soundboard remains unchanged.
- Monitor enabled/disabled unchanged.
- Bypass Effects unchanged.

F0 behavior:

- Normal voice.
- Deliberately lower voice.
- Deliberately higher voice.
- Quiet voice.
- Loud voice.
- Sustained vowel.
- Rapid speech.
- Whispered or unvoiced speech.
- Lower voice reports lower F0.
- Higher voice reports higher F0.
- Quiet/loud level does not radically alter F0.
- Sustained vowel is stable.
- Rapid speech updates.
- Whisper is not falsely treated as stable voiced pitch.
- Silence becomes unvoiced.
- Confidence behaves plausibly.

Rolling profile:

- Profile begins collecting.
- Ready state appears after sufficient voiced speech.
- Median F0 is stable.
- Lower/upper pitch range is plausible.
- Voiced duration increases.
- Silence does not immediately erase profile.
- After the profile reaches ready, brief speech gaps and unvoiced consonants do
  not repeatedly return the rolling profile to collecting while retained voiced
  evidence remains sufficient.
- Stale state appears appropriately.
- Reset Source Analysis clears profile.
- Profile rebuilds after reset.

Spectral characteristics:

- Ordinary voice.
- Chest-heavy low voice.
- Brighter voice.
- Sustained `ah`.
- Sustained `ee`.
- Strong `s`.
- Strong `sh`.
- Chest ratio responds to chest-heavy speech.
- Brightness responds to brighter speech.
- Sibilance responds to `s` and `sh`.
- Resonance estimates change plausibly between vowels where available.
- Invalid estimates are shown as unavailable rather than false precision.

Runtime status:

- Analyzed count increases.
- Dropped count remains bounded and understandable.
- Dropped frames do not create growing delay.
- Snapshot age remains current.
- No analyzer failure.
- No UI freezing.

Final audio regression:

- Microphone.
- Virtual mic.
- Monitor.
- Monitor-disabled operation.
- Dry voice.
- Input processing.
- Effects.
- Pitch.
- Presets.
- Soundboard.
- Start/Stop.
- Close/relaunch.
- Metallic tail absent.
- Flutter absent.
- Latency acceptable.

## M9.1 Adaptive Target Engine Core

M9.1 Status: PASS.

Launch:

```powershell
.\.venv\Scripts\python.exe main.py --target-planner-lab
```

Scope:

- M9.1 is an experimental planning-only lab.
- Target Planner Lab launches stopped.
- Target Planner Lab enables the accepted M9.0 passive source analyzer and
  displays both Source Analysis and Target Planner tabs.
- Normal launch, `--voice-analysis-lab`, and `--formant-lab` remain isolated.
- Normal audio chain remains High-Pass, Noise Gate, Compressor, Pitch Shift,
  Robot, Lowpass, Gain, Limiter.
- Formant Lab chain remains High-Pass, Noise Gate, Compressor, Experimental
  Pitch/Formant, Robot, Lowpass, Gain, Limiter.
- The planner produces recommendations only. It does not modify audio, DSP
  parameters, devices, routes, meters, soundboard behavior, settings, presets,
  built-in characters, or Signalsmith configuration.
- Target values and calculated plans are session-only and are not written to
  `settings.json` or `presets.json`.
- The Target Planner UI states `Experimental - Planning Only - Audio Is Not
  Modified`.
- The UI intentionally has no Apply, Preview, Save, or Export action.

Implementation notes:

- Core relationship:
  `Source Voice Profile + Target Voice Profile + Character Strength =
  Immutable Transformation Plan`.
- `TargetVoiceProfile` and `TransformationPlan` are frozen scalar contracts.
- `TransformationPlanner` is pure and stateless.
- Character Strength maps UI `0..100` to planner `0..1`.
- Strength `0%` produces a fully neutral applied plan: no applied pitch,
  pitch-range, formant, spectral, de-essing, texture, dynamics, or future
  processor capability is required.
- Pitch center uses `12 * log2(target_median_f0 / source_median_f0)`, strength
  scaling, and target clamping.
- Pitch range uses `target_span / source_span`, strength interpolation, and
  target clamping.
- Formant recommendation comes from target intent only and is clamped to a
  natural planning maximum of `+/-2` semitones.
- F1/F2/F3 remain weak descriptors only and do not directly determine automatic
  formant shift.
- Spectral recommendations use source/target energy-ratio comparisons, and
  missing source evidence degrades only the affected control.
- Dynamics are recommendations only and use M8.0-compatible ranges. Live M8.0
  settings are not mutated.
- Capabilities describe processors required for the current applied plan, not
  every latent target requirement. Latent target requirements are gated by
  active character strength, while requested target intent remains inspectable
  through requested values and target metadata.
- No planner code runs in the audio callback.

Diagnostic references:

- Diagnostic Neutral.
- Higher / Brighter Reference.
- Lower / Weightier Reference.

These references are target-neutral planning aids, not production characters
and not identity or gender classifiers.

Automated M9.1 verification covers:

- immutable planner contracts;
- target-profile validation;
- strength `0/50/100` behavior;
- pitch-center and pitch-range formulas;
- formant recommendation isolation from F1/F2/F3;
- spectral ratio and tilt formulas;
- de-essing, texture, and dynamics recommendations;
- plan state reporting;
- lab-mode UI exposure;
- normal/formant/analysis mode isolation;
- normal and target-planner audio transparency;
- settings and presets compatibility;
- callback/source architecture guards.

Final M9.1 live Target Planner Lab acceptance is complete.

Launch and isolation PASS results:

- Target Planner Lab launch.
- Source Analysis tab present.
- Target Planner tab present.
- Application launches stopped.
- Normal launch unchanged.
- Formant Lab unchanged.
- Voice Analysis Lab unchanged.
- Normal and prototype effect chains unchanged.
- Planner remains outside DSP and callback.

Source collection and planner-state PASS results:

- Source collection begins correctly.
- Collecting state behaves correctly.
- Ready source produces ready plan.
- Stop/reset behavior appears correct.
- Source-profile rebuild produces updated plans.
- No planner failure.
- No analyzer failure.

Zero-strength neutrality PASS results for Neutral, Higher / Brighter, and
Lower / Weightier:

- Applied pitch shift is zero at `0%`.
- Applied pitch-range scale is `1.0` at `0%`.
- Applied formant shift is zero at `0%`.
- Applied spectral adjustments are zero at `0%`.
- Applied tilt adjustment is zero at `0%`.
- De-essing is zero at `0%`.
- Breathiness is zero at `0%`.
- Harmonic weight is zero at `0%`.
- Compressor recommendation is neutral at `0%`.
- Limiter recommendation is neutral at `0%`.
- Capability tuple is empty at `0%`.
- No processor-required warnings appear at `0%`.

Strength interpolation PASS results:

- `50%` values appear between neutral and full target.
- `100%` produces the full bounded target plan.
- Interpolation appears monotonic.
- Capability requirements appear only for active transformation.
- Changing strength does not alter source measurements.
- Changing strength does not modify target contracts.

Higher / Brighter diagnostic direction PASS results:

- Requested and applied pitch directions are positive.
- Positive formant intent remains restrained.
- Chest/low weighting responds in the expected direction.
- Presence and brightness respond in the expected direction.
- Tilt-index adjustment responds correctly.
- Breathiness, harmonic, and de-esser requirements appear appropriately.
- Clamp warnings are understandable.
- No identity or gender classification is inferred.
- This remains a diagnostic higher/brighter target, not a finished feminine
  character.

Lower / Weightier diagnostic direction PASS results:

- Requested and applied pitch directions are negative where expected.
- Negative formant intent remains restrained.
- Chest weighting responds in the expected direction.
- Low-mid shaping is visible.
- Brightness and tilt respond in the expected direction.
- Harmonic enhancement, compressor, and limiter recommendations appear
  appropriately.
- Clamp warnings are understandable.
- No identity or gender classification is inferred.
- This remains a diagnostic lower/weightier target, not a finished
  deep-masculine character.

Clamps and degradation PASS results:

- Requested and applied values are both visible.
- Pitch clamp behavior appears correct.
- Formant planning remains within accepted natural limits.
- Spectral clamp behavior appears correct.
- Stale source handling appears correct.
- Missing evidence degrades only the affected control.
- F1/F2/F3 remain weak descriptors and do not directly control formant
  planning.
- Plan confidence and warnings appear understandable.

Reset and session-state PASS results:

- Reset Target Profile works.
- Reset Planner Lab works.
- Source analysis is not modified by target reset.
- Devices, routes, selected voice, M8.0 settings, soundboard, monitor, and
  volumes remain unchanged.
- Planner values remain session-only.
- Relaunch restores planner defaults.
- No target-profile file is created.
- No plan file is created.
- `settings.json` is unchanged.
- `presets.json` is unchanged.

Audio transparency PASS results:

- No audible pitch, formant, or EQ change.
- No added latency.
- Metallic tail absent.
- Flutter absent.
- Crackle absent.
- No new audible block boundaries.
- Meter, soundboard, monitor, and Bypass Effects behavior unchanged.
- No UI freezing.

Accepted technical conclusions:

- `TargetVoiceProfile` is accepted as the immutable acoustic target contract.
- `TransformationPlan` is accepted as the immutable diagnostic plan contract.
- Source profile plus target profile plus character strength is accepted as
  the planning architecture.
- Pitch-center planning is accepted.
- Pitch-range planning is accepted as a future processor requirement.
- Restrained target-intent formant planning is accepted.
- Spectral band and tilt-index planning are accepted as diagnostic EQ
  requirements.
- De-essing planning is accepted as a future processor requirement.
- Breathiness and harmonic-weight planning are accepted as target-intent
  capability requirements.
- Dynamics recommendations are accepted as plans only and do not modify M8.0.
- Capabilities describe the current applied plan.
- `0%` character strength produces a fully neutral applied plan.
- Requested and applied values remain separately inspectable.
- Planner output remains diagnostic and does not alter audio.
- Planner state remains session-only.
- No source, target, or plan persistence is required at this stage.
- The planner performs no identity, gender, age, or speaker classification.
- Higher / Brighter and Lower / Weightier remain diagnostic references, not
  finished product characters.

Known non-blocking debt:

- Diagnostic target values remain provisional.
- The planner does not yet execute DSP.
- Pitch-range mapping processor does not yet exist.
- Parametric EQ execution does not yet exist.
- De-esser does not yet exist.
- Breathiness synthesis does not yet exist.
- Harmonic enhancement does not yet exist.
- Approximate F1/F2/F3 remain weak descriptors.
- Target profiles are not yet persisted.
- No finished feminine or deep-masculine character exists yet.
- These are expected future milestones, not M9.1 failures.

Next epic direction:

- The next milestone begins applying the accepted plan to a controlled
  experimental audio path.
- The next implementation must preserve the planner as the single source of
  transformation intent, support both higher/brighter and lower/weightier
  directions, avoid hardcoding a one-direction-only architecture, begin with a
  bounded experimental execution lab, avoid immediately replacing production
  characters, and preserve normal VoiceLab behavior.

## M9.2 Controlled Transformation Execution Lab Live Acceptance

Status: PASS.

Luke completed practical live Transformation Execution Lab acceptance. M9.2 is
accepted as execution infrastructure. Continuous reactive replanning is not
accepted as the final normal character-control experience and remains an
experimental diagnostic/adaptive behavior.

Mode isolation:

- Normal launch unchanged: PASS.
- Formant Lab unchanged: PASS.
- Voice Analysis Lab unchanged: PASS.
- Target Planner Lab unchanged and planning-only: PASS.
- `main.py --transformation-execution-lab` launches: PASS.
- Source Analysis tab present: PASS.
- Target Planner tab present: PASS.
- Plan Execution tab present: PASS.
- Launches stopped: PASS.
- Plan execution launches disabled: PASS.

Baseline:

- Start with execution disabled: PASS.
- Audio matches neutral Formant Lab behavior: PASS.
- Inherited Formant Lab latency is understandable: PASS.
- No unexpected extra delay: PASS.
- Source analysis collects correctly: PASS.
- Target planner produces plans: PASS.
- Execution does not activate automatically: PASS.

Zero-strength neutrality:

- For Neutral, Higher / Brighter, and Lower / Weightier, enable execution at
  `0%`.
- No audible pitch change: PASS.
- No audible formant change: PASS.
- No planner-induced dynamics change: PASS.
- Effective pitch remains zero: PASS.
- Effective formant remains zero: PASS.
- No supported capability executes: PASS.
- Baseline M8.0 processing remains: PASS.

Higher / Brighter partial execution:

- At `50%` and `100%`, positive pitch movement is audible: PASS.
- Positive formant movement is audible: PASS.
- Changes are smooth: PASS.
- No crackle, flutter, or severe metallic tail beyond accepted Formant Lab
  behavior: PASS.
- Pitch/formant values follow the plan: PASS.
- Requested pitch, applied target pitch, and pitch saturation state are visible
  separately: PASS.
- Unsupported EQ, tilt, breathiness, harmonic, and de-esser requirements are
  listed and not approximated: PASS.
- Result is recognized as incomplete, not a finished feminine character.

Lower / Weightier partial execution:

- At `50%` and `100%`, negative pitch movement is audible: PASS.
- Negative formant movement is audible: PASS.
- Compressor override appears where requested: PASS.
- Limiter override appears where requested: PASS.
- Baseline settings restore when disabled: PASS.
- Changes are smooth: PASS.
- No crackle, flutter, or severe pumping: PASS.
- Unsupported EQ, tilt, harmonic, and de-esser requirements are listed and not
  approximated: PASS.
- Result is recognized as incomplete, not a finished deep-masculine character.

Target and strength changes:

- While execution is enabled, change strength gradually.
- Switch diagnostic targets.
- Edit target values.
- No stream restart: PASS.
- No device reopen: PASS.
- No hard discontinuity: PASS.
- Parameters converge promptly: PASS.
- No persistent zippering: PASS.
- No growing delay: PASS.

Disable and neutral return:

- Disable execution: PASS.
- Pitch returns to zero smoothly: PASS.
- Formant returns to zero smoothly: PASS.
- Compressor override clears: PASS.
- Limiter override clears: PASS.
- M8.0 baseline remains: PASS.
- Source profile remains: PASS.
- Target values remain: PASS.
- Stream continues: PASS.

Reset and failure handling:

- Return to Neutral works: PASS.
- Reset Target Profile works: PASS.
- Reset Planner Lab works: PASS.
- Reset Source Analysis blocks execution until profile rebuild: PASS.
- Stale source neutralizes safely: PASS.
- Stop clears execution: PASS.
- Start again begins disabled: PASS.
- Native backend unavailable state is visible in Plan Execution backend health:
  PASS.
- Backend-unavailable pitch/formant capabilities are listed separately from
  unsupported plan processors: PASS.
- Runtime-bypassed pitch/formant effects do not remain reported as active:
  PASS.
- Pitch-only fallback, if introduced later, must not claim formant execution:
  PASS.
- Recovery from a runtime-bypassed combined pitch/formant backend is Stop, then
  Start; Start begins execution disabled and re-evaluates backend health: PASS.
- No stale plan remains active: PASS.

Global Bypass:

- Bypass Effects behaves as before: PASS.
- Execution status shows bypassed: PASS.
- No second bypass authority: PASS.
- Removing bypass resumes smoothly: PASS.
- No stale parameter jump: PASS.

Session state:

- No target file created: PASS.
- No plan file created: PASS.
- No execution cache created: PASS.
- `settings.json` unchanged: PASS.
- `presets.json` unchanged: PASS.
- Execution snapshots exposed to the application remain frozen scalar contracts
  with frozen compressor, limiter, and backend-health snapshots: PASS.
- Relaunch restores execution disabled: PASS.
- Planner defaults restored according to M9.1 behavior: PASS.

Audio and lifecycle:

- No new full latency stage: PASS.
- No unexplained latency growth: PASS.
- Repeated Start/Stop: PASS.
- Close while processing: PASS.
- Relaunch Execution Lab: PASS.
- Relaunch normal mode: PASS.
- No UI freeze: PASS.
- No controller failure: PASS.
- No analyzer failure: PASS.
- No worker leak: PASS.

Accepted M9.2 technical conclusions:

- `TransformationExecutor` is accepted as subordinate to
  `TransformationPlan`.
- The planner remains the sole transformation-intent authority.
- M9.2 executes only supported capabilities.
- Unsupported capabilities remain visible and are not approximated.
- Adaptive pitch-center execution is accepted.
- Restrained formant execution is accepted.
- Session-only compressor and limiter overlays are accepted.
- Runtime smoothing is accepted for controlled experimental execution.
- Backend-health propagation is accepted.
- Immutable execution snapshots are accepted.
- Readiness hysteresis is accepted.
- One combined Signalsmith pitch/formant stage is accepted.
- Inherited latency remains approximately 4800 frames / 100 ms at 48 kHz.
- M9.2 does not replace production characters.
- M9.2 does not establish continuous reactive replanning as the final user
  experience.

Product-control conclusion:

Continuous source-driven replanning can feel as though the selected character
is moving underneath the operator. Continuous replanning therefore remains an
experimental adaptive mode and must not become the default production character
behavior. Ordinary character use should eventually hold selected values until
the operator changes or recalibrates them. Live source analysis remains useful
for producing a suggested starting plan, but source analysis should not
continuously override deliberate operator control by default.

Next milestone direction: Calibrate, Lock, and Manual Trim.

Required conceptual flow:

Source analysis -> capture a calibration profile -> generate a suggested
`TransformationPlan` -> lock the plan -> execute stable fixed values -> allow
manual trims.

Expected controls include Calibrate Source, Lock Suggested Transformation,
Recalibrate, Pitch Trim, Formant Trim, Character Strength, Return to Suggested
Plan, Return to Neutral, and Adaptive Updating default Off.

The next milestone must preserve M9.0 source analysis, M9.1 planning, and M9.2
execution; retain continuous adaptation only as an optional experimental mode;
make locked stable execution the primary lab workflow; avoid production
character replacement; and avoid target or plan persistence unless explicitly
scoped later.

Optional neural conversion boundary:

Neural voice conversion remains a future optional plugin capability. It is not
a required VoiceLab core feature, and it must be loadable, disableable,
replaceable, and absent without breaking VoiceLab. Current development remains
focused on stable DSP character control. No neural dependencies or
implementation are part of M9.2 or the immediate next milestone.

Known non-blocking M9.2 debt:

- Continuous adaptation is not the preferred default UX.
- No plan-lock workflow exists yet.
- No manual pitch/formant trim exists yet.
- Pitch-range mapping remains unsupported.
- Parametric EQ remains unsupported.
- Spectral-tilt shaping remains unsupported.
- De-essing remains unsupported.
- Breathiness synthesis remains unsupported.
- Harmonic enhancement remains unsupported.
- Diagnostic target values remain provisional.
- No finished feminine or deep-masculine character exists yet.

These are future milestones rather than M9.2 failures.

## M9.3 Calibrate, Lock, and Manual Trim Live Acceptance

Status: PASS.

Luke completed practical live Calibrate/Lock Lab acceptance. M9.3 is accepted
as the primary stable experimental control workflow. Continuous adaptation
remains an optional experimental mode and is not the default character-control
model. Launch with:

```powershell
.\.venv\Scripts\python.exe main.py --calibrate-lock-lab
```

Mode and initial state PASS results:

- Calibrate/Lock Lab launches: PASS.
- Required tabs are present: PASS.
- Application launches stopped: PASS.
- Execution launches disabled: PASS.
- Adaptive Updating defaults Off: PASS.
- No calibration exists at launch: PASS.
- No suggestion exists at launch: PASS.
- No lock exists at launch: PASS.
- Pitch and formant trims begin at zero: PASS.

Source analysis and calibration PASS results:

- Collecting and ready state changes are visible: PASS.
- Source-analysis values update visibly: PASS.
- Calibrate Source succeeds after the source becomes ready: PASS.
- Captured calibration values remain frozen: PASS.
- Live source measurements continue updating separately: PASS.
- Calibration does not alter audio: PASS.
- Recalibration produces a new suggestion: PASS.
- Recalibration does not alter the active lock: PASS.
- Successful calibration snapshots should contain only finite numeric evidence
  or explicit unavailable values. NaN, infinity, boolean, nonnumeric,
  out-of-range, or inconsistent pitch evidence must fail before any calibration
  state changes.
- Failed calibration attempts should preserve the prior calibration,
  suggestion, lock, trims, execution-enabled state, and runtime target.

Accepted finite calibration correction:

- Corrective commit
  `abdfb61019e70b28f91a66362711b7006f2e0172` (`Reject nonfinite calibration
  evidence`) is accepted.
- NaN and infinity cannot enter a successful frozen calibration.
- Required pitch evidence must be finite, positive, ordered, and within the
  accepted M9.0 range.
- Source age and voiced evidence must be finite and nonnegative.
- Optional numeric descriptors may be `None` but must be finite when present.
- Validation completes before state mutation.
- Failed capture preserves prior calibration, suggestion, lock, trims, mode,
  execution state, and runtime target.
- Successful calibrations contain only finite numeric scalars or explicit
  unavailable values.

Suggestion and locking PASS results:

- Suggested transformation appears after calibration: PASS.
- Lock Suggested Transformation succeeds: PASS.
- Locking does not automatically enable execution: PASS.
- The operator must explicitly enable execution: PASS.
- Locked values remain fixed: PASS.
- Live source changes do not move the locked plan in Off mode: PASS.
- Source collecting/ready changes do not neutralize a valid locked plan: PASS.
- Target edits change the suggestion only: PASS.
- Character-strength edits change the suggestion only: PASS.
- Newer-suggestion state is visible: PASS.
- Explicit re-lock updates the executed transformation: PASS.

Audible execution PASS results:

- Enabling execution makes the locked transformation audible: PASS.
- The resulting voice sounds usable/decent: PASS.
- Locked execution is more predictable than continuous reactive replanning:
  PASS.
- Current runtime values converge to their fixed targets: PASS.
- No reactive target chasing is observed in Off mode: PASS.

Manual trim PASS results:

- Pitch trim changes pitch predictably: PASS.
- Formant trim changes formant predictably: PASS.
- Trims remain fixed until deliberately changed: PASS.
- Locked base values remain immutable: PASS.
- Final values reflect locked base plus trim: PASS.
- Clamp reporting is understandable: PASS.
- Trims do not cause stream restart: PASS.
- Return to Suggested Plan clears trims and restores the locked base: PASS.
- A newer unlocked suggestion is not silently applied: PASS.

Adaptive Updating PASS results:

- Off mode uses the locked plan: PASS.
- Continuous mode uses live adaptive planning: PASS.
- Switching to Continuous is explicit: PASS.
- Switching back to Off restores the retained lock: PASS.
- The lock remains stored while Continuous is active: PASS.
- Mode switching does not reopen the stream: PASS.
- No stale maximum or corrupted target survives mode switching: PASS.
- Slow adaptation remains deferred.

Return to Neutral PASS results:

- Return to Neutral disables execution: PASS.
- Pitch and formant return to neutral: PASS.
- Plan-driven dynamics overrides clear: PASS.
- Calibration remains available: PASS.
- Suggestion remains available: PASS.
- Locked plan remains available: PASS.
- Stored trim policy behaves as documented: PASS.
- Re-enabling execution restores the retained stable transformation: PASS.

Extended stability PASS results:

Luke operated the Calibrate/Lock Lab for approximately 30 minutes.

- No crackle observed: PASS.
- No flutter observed: PASS.
- No metallic tail observed: PASS.
- No growing delay observed: PASS.
- No sudden unexplained target jumps observed: PASS.
- No UI freeze observed: PASS.
- No analyzer/controller failure observed: PASS.
- Stable locked behavior remained usable over the extended run: PASS.

Accepted primary workflow:

Live source analysis -> capture frozen calibration -> generate suggested
transformation -> explicitly lock the suggestion -> enable execution -> apply
stable manual pitch/formant trims.

Accepted authority rules:

- Live analysis owns current measurements.
- Calibration owns frozen source evidence.
- Planner owns suggested transformation intent.
- Explicit Lock owns stable transformation selection.
- Manual trim owns deliberate pitch/formant offsets.
- Executor remains subordinate to the locked or adaptive `TransformationPlan`.
- Runtime owns smoothing and effective effect values.
- UI does not manipulate effects directly.

While Adaptive Updating is Off:

- Live source changes do not alter locked execution.
- Target edits do not alter locked execution.
- Strength edits do not alter locked execution.
- Recalibration does not alter locked execution.
- Suggestion changes do not alter audio.
- Only explicit re-lock or manual trim changes the selected transformation.

Session and persistence:

- Calibration, suggestion, lock, manual trims, and adaptive mode are
  session-only.
- No calibration, suggestion, lock, trim, or execution-cache file is created.
- `settings.json` schema is unchanged.
- `presets.json` schema is unchanged.
- Production characters are unchanged.

Architecture and chain:

```text
High-Pass
-> Noise Gate
-> Compressor
-> Experimental Pitch/Formant
-> Robot
-> Lowpass
-> Gain
-> Limiter
-> Mixer
```

- Exactly one combined Signalsmith pitch/formant stage is used.
- No production Pitch Shift is present in the same chain.
- No second formant stage is present.
- No additional audio stream, AudioIO owner, or Router owner is added.
- Inherited latency remains approximately 4800 frames / 100 ms at 48 kHz.
- Normal mode, Formant Lab, Voice Analysis Lab, Target Planner Lab, and
  Transformation Execution Lab remain unchanged.

Known non-blocking debt:

- Diagnostic target profiles remain provisional.
- No finished production feminine character exists yet.
- No finished production deep-masculine character exists yet.
- Pitch-range mapping remains unsupported.
- Parametric EQ remains unsupported.
- Spectral-tilt execution remains unsupported.
- De-essing remains unsupported.
- Breathiness synthesis remains unsupported.
- Harmonic enhancement remains unsupported.
- Backend availability is visible through Plan Execution rather than duplicated
  fully in Calibrate & Lock.
- Long-term neural conversion remains an optional plugin concern and is
  unrelated to M9.3.
- No persistence of calibration/lock/trim is currently intended.

These are future milestones, not M9.3 failures.

## M9.4 Parametric EQ Foundation Live Acceptance

Status: PASS.

Luke completed practical live acceptance of the Parametric EQ Foundation and
the corrected laboratory workflow. Launch with:

```powershell
.\.venv\Scripts\python.exe main.py --parametric-eq-lab
```

Launch and isolation PASS results:

- Parametric EQ Lab launches stopped: PASS.
- Source Analysis, Target Planner, Plan Execution, Calibrate & Lock, and
  Parametric EQ tabs are present: PASS.
- Transformation execution launches disabled: PASS.
- Adaptive Updating defaults Off: PASS.
- EQ starts disabled or flat-neutral: PASS.
- All band gains start at 0 dB: PASS.
- No EQ persistence is restored: PASS.
- Normal mode, Formant Lab, Voice Analysis Lab, Target Planner Lab,
  Transformation Execution Lab, and Calibrate/Lock Lab remain unchanged: PASS.

Parametric EQ UI PASS results:

- Graph-first interface is accepted: PASS.
- Graph occupies the primary workspace: PASS.
- Five fixed draggable nodes are understandable: PASS.
- Selected-band inspector is usable: PASS.
- Diagnostics remain secondary/collapsed: PASS.
- Response curve is understandable: PASS.
- Post-EQ spectrum operates: PASS.
- Resizing remains usable: PASS.

Expected Parametric EQ chain:

```text
High-Pass
-> Noise Gate
-> Compressor
-> Experimental Pitch/Formant
-> Parametric EQ
-> Robot
-> Lowpass
-> Gain
-> Limiter
-> Mixer
```

- Exactly one Parametric EQ stage is present.
- Exactly one combined Experimental Pitch/Formant stage is present.
- No production Pitch Shift is present in the same chain.
- Parametric EQ is after pitch/formant transformation and before Robot.
- Limiter remains downstream of EQ.
- Parametric EQ reports zero added algorithmic-latency frames.
- Overall lab latency remains inherited from the pitch/formant stage,
  approximately 4800 frames / 100 ms at 48 kHz.

Interaction accessibility PASS results:

- Coarse graph movement is visible and usable: PASS.
- Shift fine-adjustment is available: PASS.
- Frequency snapping is understandable: PASS.
- Q coarse/fine adjustment works: PASS.
- Interaction overlay reports values and mode: PASS.
- Whole-EQ EQ ON/BYPASS comparison is prominent: PASS.
- Stored EQ returns after bypass: PASS.

Luke is partially deaf and initially found ordinary EQ changes difficult to
hear. Coarse interaction was added to improve audition accessibility; direct
numeric precision remains available; whole-EQ A/B remains the primary
comparison tool. This was an interaction/accessibility consideration, not a DSP
defect.

Accepted manual EQ controls:

- Drag one of the five fixed graph nodes to adjust frequency and gain.
- Normal graph drag uses coarse audible steps: gain snaps to 0.5 dB,
  and frequency snaps to practical band-dependent Hz increments.
- Hold Shift while dragging for fine adjustment: gain snaps to 0.1 dB
  and frequency uses smaller band-dependent Hz increments.
- Use the selected-band inspector for precise frequency, gain, and peak-band Q.
- Mouse wheel over a selected peak node adjusts Q in 0.25 steps; Shift uses
  0.05 steps. Shelf bands keep fixed slope/Q behavior.
- Double-click a node or use Reset Band to restore one band.
- The graph displays a compact interaction overlay with band name, frequency,
  gain, Q for peak bands, and Coarse/Fine mode while adjusting.
- Use the prominent whole-EQ A/B control, EQ ON / BYPASS, to compare processed
  EQ against dry local-bypassed EQ without losing stored EQ values.
- Low Shelf: body/chest weight, 60-250 Hz, +/-6 dB.
- Low-Mid Peak: mud/boxiness, 150-800 Hz, +/-6 dB, Q 0.3-6.0.
- Mid Peak: nasal/central color, 500-2500 Hz, +/-6 dB, Q 0.3-6.0.
- Presence Peak: intelligibility/upper-mid clarity, 1500-6000 Hz, +/-6 dB,
  Q 0.3-6.0.
- High Shelf: brightness/air, 4000-12000 Hz, +/-6 dB, capped safely below
  Nyquist.

Visualization PASS results:

- The response curve is derived from a bounded immutable ApplicationService
  visualization snapshot based on the applied coefficient bank: PASS.
- The UI does not calculate EQ coefficients and does not import the EQ effect:
  PASS.
- Optional spectrum display is Post-EQ only in M9.4. Input, Output, and Both
  analyzer modes remain deferred.
- Spectrum analysis uses a bounded one-slot latest-frame mailbox and worker-side
  FFT; it is visualization-only and does not affect audio or source analysis:
  PASS.
- Diagnostics are available but collapsed by default: PASS.

Audio and DSP PASS results:

- EQ reaches the active audio path: PASS.
- Individual and combined EQ plans operate: PASS.
- Flat EQ remains neutral: PASS.
- Reset EQ to Flat restores neutrality: PASS.
- Local bypass operates: PASS.
- Global bypass remains distinct: PASS.
- No pop observed: PASS.
- No buzz observed: PASS.
- No crackle observed: PASS.
- No bad or growing delay observed: PASS.
- No obvious transition instability observed: PASS.
- Transition telemetry settles truthfully: PASS.
- Added EQ algorithmic latency remains zero frames: PASS.

Expected band-audibility checks:

- Low Shelf +6 dB adds body.
- Low Shelf -6 dB thins low end.
- Low-Mid cut reduces mud/boxiness.
- Mid adjustment changes central/nasal color.
- Presence boost adds forward clarity.
- Presence cut softens harshness.
- High Shelf boost adds brightness.
- High Shelf cut darkens/softens.
- Frequency controls move the affected region.
- Higher Q narrows peak-band effect; lower Q broadens it.

Workflow-truthfulness PASS results:

- Production Pitch Shift no longer appears editable in chains where it is
  absent: PASS.
- Gain, Robot, and Lowpass controls remain available where actually present:
  PASS.
- Suggested Plan is distinguished from Stored Plan: PASS.
- Stored Plan is distinguished from Applied Runtime: PASS.
- Return Audio to Neutral actually neutralizes runtime: PASS.
- Stored transformation remains available after neutralization: PASS.
- Clear Stored Transformation clears lock and trims: PASS.
- Target edits update suggestion only: PASS.
- Strength edits update suggestion only: PASS.
- Explicit re-lock is required to change locked execution: PASS.
- Calibrate & Lock workflow is understandable: PASS.
- Soundboard is disabled in experimental laboratory modes: PASS.
- Parametric EQ remains independent from transformation lock authority: PASS.

Known separate live finding: odd resonance or articulation remains on words
such as "words", "wrong", "why", and "what". The issue occurs with
transformation execution active and EQ bypassed; Parametric EQ is not the
cause. Rounded W onsets, R resonance, and vowel transitions can become
exaggerated. Negative formant movement makes the problem substantially worse.
Luke commonly prefers pitch around -3 to -4 semitones with positive formant
compensation around +1 to +2.5 semitones. The artifact may interact with source
articulation, but the transformation appears to magnify it. Do not conceal it
with static EQ.

Expected M9.3 interaction:

- Lock a stable transformation and enable execution.
- Apply EQ without changing locked pitch/formant values.
- Re-lock without losing EQ values.
- Return to Suggested without losing EQ values.
- Return to Neutral follows the documented EQ session policy.
- Continuous and Off mode switching does not corrupt EQ.

Suggested five-band voice test:

- Low Shelf +2 dB.
- Low-Mid -2 dB at 300 Hz, Q 1.0.
- Mid -1 dB at 1000 Hz, Q 1.2.
- Presence +2 dB at 3000 Hz, Q 1.0.
- High Shelf +1.5 dB.

Expected result: voice remains intelligible, finite, stable, free of metallic
tail/flutter/crackle, and more deliberately shaped. Limiter remains downstream
for peak handling.

Lifecycle and persistence checks:

- Repeated Start/Stop.
- Close while active.
- Relaunch restores defaults.
- No EQ file is created.
- `settings.json` and `presets.json` schemas are unchanged.
- No worker leak and no UI freeze.

M9.4 intentionally does not mark planner `parametric_eq` or
`spectral_tilt_shaping` supported. M9.4 supplies the manual EQ foundation only.
Future spectral-tilt execution must map into the same one-EQ authority.

## Laboratory Workflow Truthfulness Acceptance

Status: PASS. The corrected laboratory workflow was accepted during final
M9.4 live acceptance.

The laboratory UI distinguishes three neutral concepts:

- Neutral Target in Target Planner generates a neutral suggestion only. It does
  not erase a lock or change audio while Adaptive Updating is Off.
- Return Audio to Neutral disables execution and returns runtime pitch,
  formant, compressor, and limiter overlays to baseline while preserving
  calibration, suggestion, locked transformation, and manual trims.
- Clear Stored Transformation disables execution, neutralizes runtime, clears
  the locked transformation, clears manual pitch/formant trims, clears retained
  latest execution state, and leaves authority as `none`.

Accepted Plan Execution presentation:

- Suggested Plan: preview-only Target Planner output.
- Stored Plan: present or absent locked transformation.
- Applied Runtime: the currently audible state and authority.

In Formant Lab, Transformation Execution Lab, Calibrate/Lock Lab, and
Parametric EQ Lab, the Voice tab must not expose an editable production Pitch
Shift control. It should show the actual active chain and explain that pitch
and formant are controlled through Plan Execution / Calibrate & Lock. Gain,
Robot, and Lowpass remain available only because those stages are in the active
lab chain. This behavior passed final M9.4 live acceptance.

In experimental laboratory modes, Soundboard is disabled and playback commands
fail safely with:

```text
Soundboard is disabled in experimental voice laboratories.
```

Normal production mode keeps existing production Pitch Shift and Soundboard
behavior.

Accepted Target Planner notes:

- Neutral target does not clear an existing lock.
- Natural Bright currently executes moderate relative upward pitch center and
  restrained positive formant shift without absolute-F0 forcing.
- Natural Deep currently executes lower pitch center, moderate positive formant
  compensation, compressor, and limiter recommendations.
- Small / Cartoon currently executes larger relative upward pitch plus
  size-coupled positive formant movement as a stylized small-vocal-tract
  reference.
- Large / Cavernous currently executes lower pitch center with restrained
  negative formant movement as a stylized large-vocal-tract reference.
- `higher_brighter` is retained only as a compatibility lookup for Natural
  Bright.
- `lower_weightier` is retained only as a compatibility alias for Natural Deep.
- Unsupported future capabilities are separated under Planned but Not Executed.
- Target or strength changes after lock must show that a new suggestion is
  available and the stored transformation is unchanged until Lock Suggested
  Transformation is pressed.

Parametric EQ acceptance note:

- Live EQ processing and the graph UI were accepted. No pops, buzz, crackle,
  bad/growing delay, or obvious EQ transition instability were observed.
- The nasal/vowel artifact is separate pitch/formant work. It appears with
  transformation active and EQ bypassed, worsens with negative formant
  movement, and must not be hidden with static EQ. Luke commonly prefers pitch
  around -3 to -4 st with positive formant compensation around +1 to +2.5 st.

Known non-blocking post-M9.5 debt:

- Natural Deep values are accepted diagnostic defaults, not finished universal
  character presets.
- More source voices should eventually be tested.
- Natural Bright still requires live acceptance and separate final-character
  development.
- Planner Parametric EQ remains unsupported.
- Spectral-tilt execution remains unsupported.
- De-essing remains unsupported.
- Breathiness synthesis remains unsupported.
- Harmonic enhancement remains unsupported.
- Finished feminine and masculine character profiles remain future work.
- Input/Output/Both spectrum modes remain deferred; Post-EQ is implemented.
- Neural conversion remains an optional future plugin.
- Additional articulation-sensitive phrase testing may continue as tuning
  evidence, but does not block M9.5.

## M9.5 Pitch/Formant Naturalness Acceptance

Status: PASS. Luke completed live Pitch/Formant Naturalness acceptance.

M9.5 decouples depth from vocal-tract size in the diagnostic planner. Natural
Deep lowers pitch and applies moderate positive formant compensation. Large /
Cavernous lowers both pitch and formants only as an explicitly stylized
large-vocal-tract reference. The existing combined Signalsmith pitch/formant
stage, latency, Parametric EQ authority, reset semantics, settings, presets,
and production characters remain unchanged.

Automated and live acceptance verified:

- After M9.6, Neutral, Natural Bright, Natural Deep, Small / Cartoon, and
  Large / Cavernous are exposed in that order.
- All targets produce a fully neutral applied plan at `0%`.
- Natural Deep at full strength requests about `-3.5 st` pitch and applies
  about `+1.5 st` formant compensation.
- Natural Deep never plans negative formant movement; the naturalness guard
  degrades inconsistent natural targets instead of silently accepting them.
- Large / Cavernous is the only built-in target that combines negative pitch
  and negative formant, and it carries a stylized warning.
- Manual trim can deliberately create negative pitch plus negative formant, but
  receives a warning and does not mutate the locked base plan.
- Manual formant trim range is `+/-2.0 st`. The runtime formant safety clamp
  remains unchanged at `+/-2.0 st`.
- Natural Deep can be compared against final formant `0` using manual trim, and
  deliberate negative final formant remains an operator override.
- Naturalness guard blocks negative natural-compensation formant intent
  regardless of pitch sign. Requested negative intent remains inspectable, but
  applied planner formant is clamped to `0`.
- Neutral has no active planner capabilities at any strength.
- Protected production preset selection was corrected so normal production
  Pitch Shift changes remain truthful while running; experimental lab chains
  still use only Experimental Pitch/Formant.
- Target and strength changes update suggestions only while Adaptive Updating
  is Off; locked execution changes only through explicit re-lock or trim.
- Continuous mode remains explicit and Off remains the default.
- Planner `parametric_eq` and `spectral_tilt_shaping` remain unsupported.
- No second pitch/formant processor, Signalsmith buffering change, production
  character replacement, EQ concealment, persistence change, phoneme/speech
  model, de-essing, breathiness, harmonic enhancement, spectral tilt, or neural
  conversion was added.

Natural Deep live PASS:

- Natural Deep at approximately `-3.5 st` pitch and `+1.505 st` formant was
  judged substantially more natural than the prior lower-voice behavior.
- Luke's live assessment was that it "sounds pretty dang good", sounds clearly
  good and usable, and materially improves problematic W/R/vowel phrases.
- Words such as "words", "wrong", "why", and "what" no longer exhibit the
  same unacceptable exaggerated resonance.
- The result no longer primarily resembles someone deliberately forcing their
  throat lower.
- Positive formant compensation is preferred over negative formant movement for
  natural deepening.
- This confirms the central M9.5 product decision: lowering pitch for a
  natural deep voice must not automatically lower formants.

Large / Cavernous live PASS:

- Large / Cavernous at approximately `-4.5 st` pitch and `-1.5 st` formant was
  judged ridiculous and exaggerated, which is the intended behavior.
- It is clearly distinct from Natural Deep.
- It successfully represents a stylized large-vocal-tract effect.
- Negative pitch plus negative formant remains useful as a deliberate creative
  effect.
- It must not be presented as the natural deep-voice default.
- Its vowel and resonance exaggeration is expected rather than considered a
  defect.

Workflow acceptance PASS:

- Source Analysis readiness is published consistently.
- Calibrate Source clearly reflects prerequisites.
- Successful calibration immediately creates a suggestion.
- Lock Suggested Transformation becomes available only when a valid suggestion
  exists.
- Lock command creates a stored transformation.
- Execution applies the stored transformation.
- Exact blocker reasons are visible.
- Workflow banner uses truthful 8-step status.
- No silent calibration or lock failure remains.
- Cross-tab state is service-owned; no tab-owned planner or calibration state
  exists.

Live acceptance classification:

- Natural Deep sounds natural enough for continued product development: PASS.
- Natural Deep improves the old W/R/vowel resonance behavior: PASS.
- Natural Deep is clearly preferable to the prior negative-formant lower voice:
  PASS.
- Natural Deep remains distinct from pitch-only behavior: PASS.
- Large / Cavernous is clearly stylized and exaggerated: PASS.
- Target strength scales predictably: PASS.
- Manual trim can reach formant zero: PASS.
- Manual trim can produce deliberate negative final formant: PASS.
- Final-value warnings behave truthfully: PASS.
- Calibration creates suggestions reliably: PASS.
- Locking works reliably: PASS.
- Execution applies the stored plan: PASS.
- Return Audio to Neutral remains correct: PASS.
- Clear Stored Transformation remains correct: PASS.
- No new crackle, flutter, metallic tail, stream restart, or growing delay was
  reported: PASS.
- M9.4 Parametric EQ remains unaffected: PASS.

## M9.6 Higher / Brighter Naturalness Live Checklist

Status: PROVISIONAL. Automated implementation and regression verification are
complete; live Natural Bright acceptance remains open.

Launch:

```powershell
.\.venv\Scripts\python.exe main.py --parametric-eq-lab
```

Initial state:

- Start Processing.
- Wait for Source Analysis Ready.
- Calibrate Source.
- Confirm a suggestion is available.
- Confirm five targets are visible: Neutral, Natural Bright, Natural Deep,
  Small / Cartoon, Large / Cavernous.
- Use Baseline/Neutral voice.
- Robot Off.
- Lowpass Off.
- Parametric EQ Flat or Bypass.
- Adaptive Updating Off.
- Pitch and formant trims zero.

Natural Bright:

- Select Natural Bright at `100%`.
- Expected approximate base: pitch `+3.5 st`, formant `+1.0 st`.
- Lock Suggested Transformation and enable execution.
- Repeat:
  - she sells seashells
  - this weather is strange
  - really bright white light
  - why would we wait by the window
  - everyone was singing in the evening
  - yellow sweater
  - fresh fish
  - shiny silver shoes
  - we were already there
  - very rarely
- Listen for natural vowel recognition; S, SH, CH, F, and TH clarity; excessive
  sibilance; thin or nasal resonance; chipmunk or helium quality; metallic or
  robotic tail; abrupt pitch instability; and whether the voice sounds
  moderately higher rather than artificially tiny.

Pitch-only comparison:

- Keep Natural Bright locked.
- Set formant trim to approximately `-1.0 st`.
- Expected final: pitch about `+3.5 st`, formant about `0.0 st`.
- Compare against the Natural Bright base `+1.0 st` formant and decide whether
  moderate positive formant movement improves naturalness or makes the voice
  too small/thin.

Formant sweep:

- With pitch about `+3.5 st`, compare final formant `0.0`, `+0.5`, `+1.0`,
  `+1.5`, and `+2.0 st`.
- Identify the setting that sounds brighter without becoming cartoon-like.

Strength progression:

- Test Natural Bright at `25%`, `50%`, `75%`, and `100%`.
- Confirm pitch/formant movement increases predictably, no clamp jump occurs,
  no sudden chipmunk transition occurs, no stale stored plan is applied, and
  explicit re-lock remains required.

Small / Cartoon:

- Select Small / Cartoon at `100%`, explicitly re-lock, and enable execution.
- Expected approximate base: pitch `+6.0 st`, formant `+2.0 st`.
- Confirm the result is clearly exaggerated, clearly distinct from Natural
  Bright, expectedly thin/cartoon-like, and not confused with the natural
  target.

Stability:

- No crackle.
- No flutter.
- No metallic tail.
- No growing delay.
- No stream restart.
- No backend failure.
- No stale target.
- Return Audio to Neutral works.
- Clear Stored Transformation works.
- Parametric EQ remains independent.

M9.6 acceptance gate:

- Natural Bright sounds more natural than the old absolute-F0 behavior.
- Natural Bright is preferable to pitch-only or has a clearly identified better
  formant value.
- Natural Bright does not sound primarily chipmunk-like or helium-like.
- Natural Bright remains clearly distinct from Small / Cartoon.
- Strength scales predictably.
- Sibilants remain usable.
- Vowels remain recognizable.
- Lock/calibration workflow remains reliable.
- No stability regression occurs.

## M9.6 Unified Transformation Workflow Live Checklist

Status: PROVISIONAL. Automated implementation and regression verification are
complete; live unified-workflow acceptance remains open.

Normal workflow:

1. Open `Transform`.
2. Press `Start Listening`.
3. Speak normally until analysis readiness is shown.
4. Press `Calibrate Voice`.
5. Select `Natural Bright`.
6. Adjust `Strength`.
7. Press `Apply Transformation`.
8. Tune pitch and formant in `Manual Adjustment`.
9. Optionally open `Advanced Tone Shaping - Parametric EQ` and adjust, bypass,
   or reset EQ.

Expected page behavior:

- No Source Analysis, Target Planner, Calibrate & Lock, Plan Execution, or
  Parametric EQ tab is required for the normal workflow.
- The primary action always shows the next useful state: Start Listening,
  Analyzing Voice..., Calibrate Voice, Apply Transformation, Resume
  Transformation, Transformation Applied, or Apply Changes.
- The persistent summary above the tabs shows processing, analysis readiness,
  calibration state, selected target, strength, and Applied / Changes Not
  Applied / Stored Audio Neutral / No Stored Transformation.
- Target or strength changes update Preview only and show `Changes Not Applied`
  until Apply Changes succeeds.
- Return Audio to Neutral disables execution and neutralizes runtime while
  retaining the stored transformation and trims.
- Resume Stored Transformation enables the retained stored plan.
- Clear Transformation disables execution, clears the stored plan and trims, and
  leaves analysis/calibration according to accepted policy.
- Diagnostics tabs remain available for Source Analysis, Target Planner, Plan
  Execution, Calibrate & Lock, and Parametric EQ inspection.

Acceptance questions:

- Can a first-time user complete the workflow without knowing the internal
  architecture?
- Is there always one obvious next action?
- Is the currently audible target obvious?
- Are unapplied changes obvious?
- Can the transformation be updated without navigating elsewhere?
- Can the user return to neutral and resume without confusion?
- Can the user clear everything without stale state?
- Can advanced users still inspect subsystem details?

Unified workflow acceptance gate:

- The Transform page is sufficient for the full normal workflow.
- The user can distinguish Preview from Applied Transformation.
- Apply Transformation / Apply Changes is explicit and mistake-resistant.
- Return, Resume, and Clear meanings are not mixed.
- Parametric EQ can be shaped from the Transform page without creating another
  EQ authority.
- No DSP, target-value, latency, persistence, or schema regression occurs.
