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
