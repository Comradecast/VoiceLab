# Signalsmith Pitch Backend

Signalsmith Stretch is the canonical real-time pitch backend for RC1. Pedalboard
remains fallback/diagnostic only.

## Source

- `third_party/signalsmith-stretch`
- `third_party/signalsmith-linear`

Both are MIT-licensed upstream Signalsmith Audio projects.

## Supported RC1 Build Assumptions

- Windows 10 or later.
- 64-bit CPython matching the runtime interpreter used to launch VoiceLab.
- Python 3.13 is the verified RC1 development target.
- Microsoft C++ Build Tools with the MSVC compiler.
- `setuptools`, `wheel`, and `pybind11` installed in the active interpreter or virtual environment.

Runtime startup never compiles this extension. Build it explicitly before
running VoiceLab when native Signalsmith support is required.

## Build

Run from the repository root with the Python interpreter or virtual environment
that will run VoiceLab:

```powershell
.\.venv\Scripts\python.exe -m pip install setuptools wheel pybind11
.\.venv\Scripts\python.exe .\tools\build_signalsmith_backend.py
```

The generated module must be importable as:

```python
import voice_lab.effects._signalsmith_pitch
```

The build script resolves paths from its own location, writes the native module
to `voice_lab/effects/`, removes stale `_signalsmith_pitch*.pyd` files before
building, and fails if the canonical package directory does not contain exactly
one native module afterward.

If the build fails on Windows, verify that the command is running inside the
intended virtual environment and that MSVC C++ Build Tools are available in the
current shell.

## Runtime Behavior

`PitchShiftEffect` attempts to use the native Signalsmith backend first. If the
native module is unavailable and fallback is enabled, it falls back to the
existing Pedalboard compatibility adapter and reports fallback status through
pitch telemetry. Fallback must not be treated as canonical Signalsmith success.

Pitch telemetry distinguishes:

- `active`: native Signalsmith is running.
- `fallback_active`: Pedalboard fallback is running.
- `native_module_missing`: canonical native module is absent.
- `native_module_incompatible`: import failed at the binary/import-loader boundary.
- `native_module_import_failure`: import raised another failure.
- `bypassed`: pitch semitones is zero and no pitch backend is intentionally used.

## Prototype Acceptance

Once built, validate:

- exact 1024-frame mono `float32` output;
- positive and negative semitone shifts;
- repeated-block continuity;
- silence tail behavior;
- `latency_frames()`, `input_latency_frames()`, and `output_latency_frames()`;
- runtime fallback behavior when the module is missing.
