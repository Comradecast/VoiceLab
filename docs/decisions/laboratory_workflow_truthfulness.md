# Laboratory Workflow Truthfulness

Status: Accepted correction. M9.4 remains PROVISIONAL pending a brief live
workflow retest.

## Decision

Laboratory modes must describe the actual active audio authority instead of
presenting ambiguous plan state or editable no-op controls.

Three neutral concepts are distinct:

- Neutral Target: Target Planner generates a neutral suggestion only. It does
  not apply audio, erase a lock, or replace stored execution while Adaptive
  Updating is Off.
- Return Audio to Neutral: execution is disabled and runtime pitch, formant,
  compressor, and limiter overlays return to baseline. Calibration,
  suggestion, locked transformation, and manual trims are retained according to
  the accepted M9.3 policy.
- Clear Stored Transformation: Adaptive Updating is set Off, execution is
  disabled, runtime is neutralized, the locked transformation is cleared,
  manual pitch/formant trims are cleared, retained latest execution plan/target
  state is cleared, and active execution authority reports `none`. Source
  Analysis, current target/strength, calibration, and suggestion remain
  session-local and available.

Plan presentation is split into:

- Suggested Plan: produced by Target Planner and preview-only until explicitly
  locked or followed by Continuous mode.
- Stored/Locked Plan: captured only by Lock Suggested Transformation and stable
  while Adaptive Updating is Off.
- Applied Runtime: the currently audible execution state, including enabled
  state, current/target smoothed pitch and formant, dynamics overlays, backend
  availability, and authority.

## Mode-Aware Voice Controls

Normal production mode keeps the production Pitch Shift control.

Formant Lab, Transformation Execution Lab, Calibrate/Lock Lab, and Parametric
EQ Lab use Experimental Pitch/Formant instead of production Pitch Shift. The
Voice tab disables the production Pitch Shift slider in these modes and shows:

```text
Production Pitch Shift is not in this lab chain. Pitch and formant are controlled through Plan Execution / Calibrate & Lock.
```

Gain, Robot, and Lowpass remain available only because they are present in the
active lab chains. The Voice tab shows a concise active-chain indicator in lab
modes and includes Parametric EQ only when that stage is actually present.

## Calibrate & Lock Workflow

The visible workflow is:

1. Start processing
2. Wait for Source Analysis Ready
3. Calibrate Source
4. Choose target and strength
5. Lock Suggested Transformation
6. Enable Execution
7. Tune pitch/formant trims
8. Shape with Parametric EQ where available

Calibrate & Lock converts a live source measurement into a stable suggested
transformation. Locking freezes that suggestion so the voice does not
continuously chase live measurements.

When target or strength changes after a lock, the UI reports:

```text
New suggestion available - stored transformation unchanged. Press Lock Suggested Transformation to apply it.
```

## Capability Presentation

Primary execution capability presentation is limited to what can affect audio
now:

- adaptive pitch center
- formant shift
- compressor
- limiter

Future or currently unsupported capabilities are separated under Planned but
Not Executed, including pitch-range mapping, parametric-EQ planner intent,
spectral-tilt shaping, de-essing, breathiness, harmonic enhancement, and other
unsupported requested capabilities.

## Soundboard Laboratory Policy

Soundboard playback remains unchanged in normal production mode.

In Formant Lab, Voice Analysis Lab, Target Planner Lab, Transformation
Execution Lab, Calibrate/Lock Lab, and Parametric EQ Lab, Soundboard is disabled
and playback commands fail safely with:

```text
Soundboard is disabled in experimental voice laboratories.
```

No auxiliary soundboard mix is created in laboratory modes, and no soundboard
configuration or schema is changed.

## Parametric EQ Finding

Live inspection confirmed Parametric EQ processing, the graph UI, Input
Processing, Routing, Diagnostics, and Source Analysis. No pops, buzz, bad
delay, or obvious EQ transition instability were observed. The graph UI was
accepted. M9.4 final PASS remains pending this workflow-truthfulness correction
and brief retest.

## Pitch/Formant Artifact Boundary

The nasal/vowel artifact is outside this correction. It exists with
transformation active and EQ bypassed. Negative formant movement worsens it.
Luke commonly prefers pitch around -3 to -4 st with positive formant
compensation around +1 to +2.5 st. Planner pitch/formant-direction correction
is a later milestone. Static EQ must not be used to conceal this artifact.

No M9.1 formulas, target profiles, Parametric EQ DSP, settings schema, or
preset schema are changed by this correction.
