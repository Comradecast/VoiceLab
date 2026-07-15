# Pitch/Formant Naturalness

Status: Provisional. M9.5 automated implementation and regression verification
are complete; practical live acceptance is still required before PASS.

## Decision

Decouple perceived depth from vocal-tract-size stylization in the diagnostic
target planner.

- Natural Deep lowers pitch with moderate positive formant compensation.
- Large / Cavernous lowers pitch and formants only as an explicit stylized
  large-vocal-tract reference.
- Higher / Brighter remains an absolute-F0 reference with restrained positive
  formant movement.
- Neutral remains fully neutral at all strengths.
- `lower_weightier` remains only as a compatibility alias for Natural Deep.

## Rules

- Pitch and formant plans expose strategy metadata.
- Natural-compensation targets must not apply negative planner formant movement
  regardless of pitch sign. Negative requested natural-compensation intent
  remains inspectable, but applied planner formant is clamped to `0`.
- Negative pitch plus negative formant must be labelled stylized.
- Manual trim may intentionally create the stylized combination, but only as an
  operator override with a warning.
- Manual formant trim authority is `+/-2.0` st. This allows Natural Deep's
  approximately `+1.505` st base formant to be compared against final formant
  `0` and a modest negative final formant. Runtime formant safety remains the
  existing `+/-2.0` st clamp.
- Neutral has no active planner capabilities at any strength.
- Target edits, strength edits, and recalibration update suggestions only while
  Adaptive Updating is Off. Stored execution changes only through explicit
  re-lock or trim.

## Non-Changes

M9.5 does not add a second pitch/formant processor, change Signalsmith
buffering, change latency, add EQ concealment, add persistence, alter settings
or preset schemas, replace production characters, change Continuous defaults,
silently mutate stored plans, or enable planner `parametric_eq` /
`spectral_tilt_shaping`.

M9.5 also does not implement phoneme modelling, speech modelling, neural
conversion, de-essing, breathiness synthesis, harmonic enhancement, spectral
tilt execution, pitch-range execution, or identity/gender classification.

## Live Acceptance Debt

Luke's practical target around pitch `-3` to `-4` st with positive formant
compensation around `+1` to `+2.5` st is treated as live-evidence debt, not a
runtime-limit change. The runtime formant limit remains the existing `+/-2` st
until a later accepted milestone changes it.

The pre-live corrective patch also restores protected production preset
selection so normal production Pitch Shift changes remain truthful while
running. Experimental pitch/formant labs still do not expose production Pitch
Shift.
