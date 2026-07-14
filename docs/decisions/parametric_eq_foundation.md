# Parametric EQ Foundation

Status: Accepted for M9.4 provisional lab implementation.

Parametric EQ is the single audio-processing authority for manual voice-shaping
EQ. It precedes spectral-tilt execution so future spectral-tilt, character EQ,
or target-profile EQ intent can merge into one final EQ plan instead of adding
overlapping processors.

## Decision

- Add an isolated `--parametric-eq-lab` launch mode.
- Build the mode on the accepted M9.3 lab path and add one Parametric EQ tab.
- Insert exactly one Parametric EQ stage after Experimental Pitch/Formant and
  before Robot. Limiter remains downstream.
- Use five fixed-role bands: Low Shelf, Low-Mid Peak, Mid Peak, Presence Peak,
  and High Shelf.
- Use RBJ Audio EQ Cookbook biquad formulas implemented in the repository.
- Design coefficients in the service/controller path, outside the audio
  callback.
- Publish one immutable latest coefficient bank to the effect. The callback
  performs bounded scalar generation checks, bounded biquad processing, and a
  bounded dual-bank crossfade transition.
- Keep manual EQ values, local bypass, and EQ enable state session-only.
- Do not write settings, presets, calibration, lock, trim, or EQ files.

## Band Ranges

- Low Shelf: 60-250 Hz, +/-6 dB, fixed slope/Q 1.0.
- Low-Mid Peak: 150-800 Hz, +/-6 dB, Q 0.3-6.0.
- Mid Peak: 500-2500 Hz, +/-6 dB, Q 0.3-6.0.
- Presence Peak: 1500-6000 Hz, +/-6 dB, Q 0.3-6.0.
- High Shelf: 4000-12000 Hz, +/-6 dB, fixed slope/Q 1.0, with applied
  frequency also limited to 45% of sample rate.

## Runtime Policy

- Flat all-zero-gain plans bypass the cascade internally and are neutral.
- Local EQ bypass is distinct from global Bypass Effects and subordinate to it.
- Invalid commands reject nonfinite, boolean, nonnumeric, missing, or unknown
  values before state mutation. Out-of-range finite frequency, gain, and Q
  values are clamped and reported.
- Runtime processing failure local-bypasses EQ and reports failed backend state
  without stopping the audio path.
- Active-to-flat, active-to-local-bypass, flat-to-active, and disable/enable
  changes use the same bounded dry/wet transition path as coefficient changes.
  The current wet bank and dry path crossfade for the configured transition
  duration, then the old path is retired and transition telemetry reports
  inactive.
- Flat-to-flat changes do not retain processor state or an active transition.
- New commands during a transition supersede the previous destination; the
  runtime keeps only one current path and one destination path, so UI updates do
  not accumulate a transition queue.
- Global Bypass Effects remains immediate and top-level. While global bypass is
  active, EQ audio is bypassed by the engine, audible transition progress is not
  claimed, and any bounded EQ transition is reported as pending. Releasing
  global bypass resumes processing the latest requested EQ state and settles the
  transition normally.
- Stop/reset clears active transition processors and runtime failure clears
  transition state into a truthful failed, locally bypassed snapshot.
- Stop/Start retains session EQ values and local enabled/bypass state; relaunch
  returns to flat disabled EQ.

## M9.3 Isolation

M9.3 continues to own calibration, suggestion, locked pitch/formant
transformation, pitch trim, formant trim, Adaptive Off/Continuous, and execution
enable. M9.4 owns only manual EQ values, EQ local enable/bypass, and final
applied EQ plan. EQ changes do not mutate calibration, suggestion, lock, trims,
or adaptive mode.

## Deferred Work

Planner `parametric_eq` remains unsupported in M9.4. Planner
`spectral_tilt_shaping` remains unsupported in M9.4. Future spectral-tilt
execution must map into this same EQ authority rather than adding a separate
audio effect. Live acceptance is pending, so M9.4 remains PROVISIONAL.
