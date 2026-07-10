# Streaming Pitch Backend

## Status

Accepted

## Priority

High

## Blocks

M5 pitch quality and latency acceptance.

## Needed By

M5.4 RC1 hardening.

## Context

M5.0/M5.1 validated the existing effect/plugin boundary for a pitch-shift demonstrator, but live testing showed the installed Pedalboard backend cannot satisfy both continuity and latency:

- 8192-frame window: continuity acceptable, latency unacceptable.
- 2048-frame window: latency improved, flutter/choppiness returned.

Pedalboard should therefore be treated as unsuitable for VoiceLab's primary real-time pitch backend unless new evidence disproves this.

## Evaluation Summary

### Signalsmith Stretch

- Streaming model: C++11 block processing with explicit input and output sample counts, reset support, and queryable input/output latency.
- Expected latency: configurable, but spectral; likely lower than the current Pedalboard 8192-frame workaround and measurable via `inputLatency()` / `outputLatency()`.
- Audio quality: intended for polyphonic pitch/time work; expected to be good enough for a demonstrator, with known limits for strong time-stretching.
- Python/Windows integration: requires a small native wrapper, likely pybind11 or C ABI over the header-only library.
- Native build requirements: C++11 compiler; documented MSVC testing.
- License: MIT.
- Packaging: vendoring source plus building one small extension is feasible.
- Fit: best fit for `PitchShiftEffect` because exact block input/output can be hidden behind the existing effect adapter.

Recommendation: preferred open-source prototype target.

### Rubber Band

- Streaming model: C++ real-time mode exists; `RubberBandLiveShifter` is specifically block-by-block pitch shifting with exact same input/output frame count.
- Expected latency: real-time API is designed for shortest available delay, but practical reports still indicate tens of milliseconds or more depending configuration.
- Audio quality: high quality and mature.
- Python/Windows integration: requires native library binding or C API; Windows CI/build support exists.
- Native build requirements: C++ library, dependency/build configuration, license review.
- License: GPL unless commercial license is acquired.
- Packaging: heavier than Signalsmith; GPL/commercial licensing is a major product decision.
- Fit: technically strong, legally and operationally heavier.

Recommendation: second choice if licensing is acceptable or commercial license is purchased.

### SoundTouch

- Streaming model: stream-oriented C++ API for tempo/pitch/rate.
- Expected latency: project documentation reports maximum input/output stream latency around 100 ms.
- Audio quality: acceptable but older time-domain approach; likely less transparent than Rubber Band or Signalsmith for voice transformation.
- Python/Windows integration: C++ library with Windows support; wrappers may exist but should not be assumed production-ready.
- Native build requirements: Visual C++ or gcc-supported build.
- License: LGPL 2.1, with commercial alternative.
- Packaging: easier licensing than GPL Rubber Band, but DLL distribution/notice obligations remain.
- Fit: possible fallback, but latency target is weak for live monitor use.

Recommendation: fallback only.

### PSOLA

- Streaming model: speech-specific pitch-synchronous overlap-add requiring pitch marking/tracking.
- Expected latency: can be low for monophonic speech if pitch tracking is reliable, but robust streaming implementation is substantial.
- Audio quality: potentially strong for voiced speech and formant preservation; weak for unvoiced/noisy sounds and pitch-tracking failures.
- Python/Windows integration: existing Python PSOLA packages are generally offline/research oriented; a real-time production adapter would be custom work.
- Native build requirements: depends on selected implementation; likely custom DSP and pitch tracker.
- License: implementation-specific.
- Packaging: uncertain.
- Fit: product-direction fit for voice-specific transformation, but too much implementation risk for a narrow M5.3 replacement.

Recommendation: defer as a later voice-specialized research path, not the immediate backend.

## Decision

Signalsmith Stretch is the canonical real-time pitch backend for VoiceLab.

Pedalboard is fallback/diagnostic only and must not be treated as the primary real-time backend unless a later explicit decision reopens that choice.

## M5.3 Prototype Status

Prototype source has been added behind the `PitchShiftEffect` boundary:

- `voice_lab.effects.signalsmith_backend.SignalsmithPitchBackend`
- optional native module target `voice_lab.effects._signalsmith_pitch`
- pybind11 wrapper source in `voice_lab/effects/native/signalsmith_pitch_backend.cpp`
- build entry point `tools/build_signalsmith_backend.py`

The native module was built and loaded successfully on Windows with Python 3.13.

Live hardware testing passed:

- metallic/electrical tail is gone;
- flutter/choppiness is gone;
- `+/-4` semitones sounds good and close to the intended product;
- `+/-8` semitones is usable but clearly pitch-modulated;
- `+/-12` semitones is intentionally extreme.

Runtime now reports `signalsmith` through pitch telemetry when the native backend is active. If the native module is unavailable, runtime falls back to the existing Pedalboard compatibility adapter and reports that fallback through pitch telemetry.

## Acceptance For Prototype

- Exact output frame count for every 1024-frame callback.
- Positive and negative semitone shifts.
- Stable repeated-block continuity.
- Near-zero or bounded silence tail.
- Algorithmic latency measured and exposed through existing pitch telemetry.
- No imports or concrete effect knowledge added to `AudioEngine`.
- No changes to frozen contracts or external plugin execution.
