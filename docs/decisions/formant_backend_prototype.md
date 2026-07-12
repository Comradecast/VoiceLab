# M8.1 Real-Time Formant Backend Prototype

Status: PROVISIONAL

## Decision

VoiceLab will evaluate real-time formant shifting through an explicit
`main.py --formant-lab` prototype mode before integrating formants into
production voices, presets, or saved operator settings.

Normal launch continues to use the existing production chain:

1. High-Pass
2. Noise Gate
3. Compressor
4. Pitch Shift
5. Robot
6. Lowpass
7. Gain
8. Limiter

Formant Lab launch replaces only the Pitch Shift stage with Experimental
Pitch/Formant, preserving the same surrounding order.

## Local API Evidence

The local `third_party/signalsmith-stretch/signalsmith-stretch.h` header
exposes:

- `setFormantFactor(Sample multiplier, bool compensatePitch=false)`
- `setFormantSemitones(Sample semitones, bool compensatePitch=false)`
- `setFormantBase(Sample baseFreq=0)`

The local README documents formant compensation with factors above 1 shifting
formants upward. M8.1 therefore maps formant semitones to factor with
`2 ** (semitones / 12)`.

## Implementation Boundary

- The native pybind wrapper exposes `set_formant_semitones` and
  `set_formant_factor`.
- The Python backend wrapper forwards the same controls.
- The experimental effect uses the same Signalsmith streaming instance for
  pitch and formant parameters.
- Formant settings are session-only and are not saved to `settings.json` or
  `presets.json`.
- No built-in character targets, custom voice schema, M8.0 input processors,
  routing, device behavior, meters, soundboard behavior, or production pitch
  fallback behavior are changed.
- The prototype uses Signalsmith's default formant-base behavior, which relies
  on rough internal F0 estimation.

## Automated Evidence

Focused tests cover native/Python API exposure, formant factor validation,
normal-chain isolation, prototype-chain order, service gating, session reset,
finite output, backend telemetry, and deterministic vowel-like probes where
formant-only movement preserves estimated F0 while shifting spectral-envelope
centroids down/up for negative/positive formant semitones.

## Remaining Acceptance

M8.1 is not production-ready and must not be marked PASS until live
hardware/audio acceptance confirms practical operator behavior, acceptable
latency, no metallic tail regression, and no flutter/choppiness regression.
