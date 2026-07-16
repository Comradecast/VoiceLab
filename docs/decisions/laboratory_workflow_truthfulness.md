# Laboratory Workflow Truthfulness

Status: PASS. The corrected laboratory workflow was accepted during final M9.4
live acceptance.

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

Final M9.5 live acceptance confirmed that Source Analysis readiness is
published consistently, Calibrate Source clearly reflects prerequisites,
successful calibration immediately creates a suggestion, Lock Suggested
Transformation becomes available only when a valid suggestion exists, locking
creates a stored transformation, execution applies that stored transformation,
exact blocker reasons are visible, and no silent calibration or lock failure
remains. Cross-tab workflow state is service-owned; no tab-owned planner or
calibration state exists.

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

M9.6 target presentation uses five visible targets in deterministic order:
Neutral, Natural Bright, Natural Deep, Small / Cartoon, and Large / Cavernous.
Legacy Higher / Brighter lookup resolves to Natural Bright compatibility
semantics and must not create a sixth visible target. Natural Bright is a
diagnostic natural upward/brightening foundation, not a finished feminine voice.
Small / Cartoon is explicitly stylized and must not be confused with the
natural target.

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

Final M9.4 live acceptance confirmed Parametric EQ processing, the graph UI,
Input Processing, Routing, Diagnostics, Source Analysis, and the corrected
workflow. No pops, buzz, crackle, bad/growing delay, or obvious EQ transition
instability were observed. Transition telemetry settled truthfully. The graph
UI, coarse/fine interaction accessibility, whole-EQ A/B workflow, Soundboard
laboratory isolation, and Suggested/Stored/Applied state model were accepted.

## Pitch/Formant Artifact Boundary

M9.5 live acceptance resolved the prior blocking pitch/formant naturalness
question. Natural Deep at approximately `-3.5 st` pitch and `+1.505 st`
formant was judged clearly good and usable, with material improvement on
problematic W/R/vowel phrases such as "words", "wrong", "why", and "what".
Positive formant compensation is the accepted natural-deep policy; lowering
pitch for a natural deep voice must not automatically lower formants.

Large / Cavernous at approximately `-4.5 st` pitch and `-1.5 st` formant was
accepted as intentionally exaggerated. Negative pitch plus negative formant
remains useful as a deliberate stylized large-vocal-tract effect, but must not
be presented as the natural deep-voice default.

Static EQ must not be used to conceal pitch/formant artifacts. Parametric EQ
remains independent, planner `parametric_eq` and `spectral_tilt_shaping` remain
unsupported, and M9.4 Parametric EQ behavior remains unaffected.

No M9.1 formulas, target profiles, Parametric EQ DSP, settings schema, or
preset schema are changed by this correction.

M9.6 changes the active upward target profile after this correction: Natural
Bright no longer uses absolute-F0 forcing, and no static EQ compensation is
used to conceal its artifacts. Parametric EQ remains independent and planner
`parametric_eq` remains unsupported.

## Production Pitch Shift Regression

Protected Deep Voice preset behavior now restores its intended full default
strength. Production Pitch Shift works in normal production mode, remains
absent from experimental pitch/formant lab chains, and no duplicate pitch stage
was introduced.
