# M8.1 Real-Time Formant Backend Prototype

Status: PASS

## Decision

VoiceLab evaluated real-time formant shifting through an explicit
`main.py --formant-lab` prototype mode before integrating formants into
production voices, presets, or saved operator settings. M8.1 closes with the
backend accepted as a bounded component for the next adaptive/target-based
character-transformation engine, not as a standalone production character
control.

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
- Runtime updates use an immutable whole-parameter snapshot. Validation
  happens outside the callback, the active snapshot is replaced by one
  reference, and the effect reads one snapshot at the beginning of each process
  block. No callback lock, queue, history, stream restart, device reopen, or
  persistence change was introduced.

## Automated Evidence

Focused tests cover native/Python API exposure, formant factor validation,
normal-chain isolation, prototype-chain order, service gating, session reset,
finite output, backend telemetry, and deterministic vowel-like probes where
formant-only movement preserves estimated F0 while shifting spectral-envelope
centroids down/up for negative/positive formant semitones.

## Final Acceptance

Final M8.1 live smoke passed: normal launch unchanged, both normal and
prototype modes launch stopped, neutral pitch 0 / formant 0 sound is usable,
subtle formant around +/-1 is audible and usable, live parameter changes work,
Prototype A/B Bypass preserves values, Stop/Start recovery works, close while
processing works, prototype and normal relaunch work, no crash occurred, no
severe burst occurred, and latency remains acceptable.

Observed transition artifact: severe clicks or bursts were NONE, but a minor
non-blocking transition artifact was OBSERVED when changing formant rapidly
toward extremes. The output can briefly sound as though prototype bypass is
active before formant processing settles. It was not persistent, did not crash
processing, did not alter settings, did not create growing latency, and remains
known DSP transition debt.

## Product Conclusion

Signalsmith provides genuine independent formant control, formant-only shifts
preserve fundamental pitch substantially, pitch and formant run in one native
processing stage, and formant processing adds no measured latency beyond the
accepted production pitch path.

The plausible natural formant range is approximately +/-0.5 to +/-2 semitones.
Approximately +/-3 begins to sound unnatural, and larger shifts are primarily
experimental or special-effect territory. Pitch and formant alone are
insufficient for accurate intended-character transformation; pitch +3 /
formant +1 still sounded like a man attempting to imitate a woman. Production
integration of raw formant values into existing characters remains deferred.
The next epic must target complete character transformation rather than expose
more isolated offsets.
