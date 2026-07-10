# VoiceLab RC1 Runbook

## Supported Environment

- Windows 10 or later.
- 64-bit CPython matching the runtime interpreter used to launch VoiceLab.
- Python 3.13 is the verified RC1 development target.
- Microsoft C++ Build Tools with the MSVC compiler.
- External virtual microphone dependency: VB-CABLE or an equivalent
  user-installed virtual audio device.

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

- Recommended normal pitch range is around `+/-4` semitones.
- `+/-8` semitones is usable but clearly processed.
- `+/-12` semitones is intentionally extreme.
- Some sung notes, bends, or transitions may sound flattened. This is deferred
  product-quality debt and is not an RC1 blocker.
- Soundboard playback may still appear to trigger in two stages; this remains
  deferred unless it blocks lifecycle shutdown.

## Troubleshooting

- If Signalsmith is missing, rebuild with the active virtual environment and
  verify `pybind11` and MSVC Build Tools are installed.
- If rebuild fails with a locked `.pyd`, close VoiceLab and confirm no
  `main.py` process is still running.
- If device startup fails, verify microphone, virtual mic, and monitor device
  IDs are available in the UI device lists.
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

Current documented result for this engineering session: not performed. This
checklist is the required manual RC1 smoke pass before release tagging.

- Microphone capture works.
- Virtual mic output receives processed audio.
- Monitor output works when enabled.
- Monitor disabled mode runs cleanly.
- Gain changes are audible.
- Lowpass changes are audible.
- Robot effect is audible when enabled.
- Signalsmith pitch at `+4` semitones works.
- Signalsmith pitch at `-4` semitones works.
- Preset switching works while running.
- Soundboard playback works.
- Audio stop/start works.
- Application close releases audio devices.
- Application relaunch works after close.
- Backend telemetry reports `signalsmith`.
- No lingering VoiceLab `main.py` process remains after close.
- Native rebuild succeeds after close.

Retain current subjective acceptance from M5.3:

- metallic tail eliminated;
- flutter/choppiness eliminated;
- latency acceptable;
- `+/-4` is the recommended normal range;
- `+/-8` is usable but obviously processed;
- `+/-12` is intentionally extreme.
