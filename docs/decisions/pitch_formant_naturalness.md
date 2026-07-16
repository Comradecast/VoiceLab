# Pitch/Formant Naturalness

Status: Accepted. M9.5 automated verification and live Pitch/Formant
Naturalness acceptance are complete; M9.5 is PASS.

## Decision

Decouple perceived depth from vocal-tract-size stylization in the diagnostic
target planner.

- Natural Deep lowers pitch with moderate positive formant compensation.
- Large / Cavernous lowers pitch and formants only as an explicit stylized
  large-vocal-tract reference.
- M9.6 replaced the prior absolute-F0 Higher / Brighter behavior with Natural
  Bright: relative upward pitch with restrained positive formant movement.
- Small / Cartoon raises pitch and formants only as an explicit stylized
  small-vocal-tract reference.
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

## Live Acceptance

Natural Deep at approximately `-3.5 st` pitch and `+1.505 st` formant was
accepted as substantially more natural than the prior lower-voice behavior.
Luke judged it clearly good and usable, said it "sounds pretty dang good", and
confirmed that problematic W/R/vowel phrases such as "words", "wrong", "why",
and "what" no longer exhibit the same unacceptable exaggerated resonance. The
result no longer primarily sounds like someone deliberately forcing their
throat lower.

This accepts positive formant compensation as the natural-deep policy: lowering
pitch for a natural deep voice must not automatically lower formants.

Large / Cavernous at approximately `-4.5 st` pitch and `-1.5 st` formant was
accepted as intentionally ridiculous and exaggerated. It is distinct from
Natural Deep, successfully represents a stylized large-vocal-tract effect, and
remains useful as a deliberate creative effect. Its vowel and resonance
exaggeration is expected rather than a defect, and it must not be presented as
the natural deep-voice default.

Live acceptance also confirmed predictable target-strength scaling, manual
trim to formant zero, deliberate negative final formant through manual trim
with truthful warning, correct Return Audio to Neutral behavior, correct Clear
Stored Transformation behavior, no reported crackle/flutter/metallic
tail/stream restart/growing delay, and no M9.4 Parametric EQ regression.

M9.6 live acceptance confirmed Natural Bright at approximately `+3.5 st` pitch
and `+1.0 st` formant as the current diagnostic natural-upward default. It
operates as intended, is acceptable for continued product development, does
not primarily present as the old extreme absolute-F0 transformation, does not
require planner clamp saturation, keeps source F0 from changing the relative
semitone target, scales predictably with strength, and preserves usable vowels
and consonants. No target-value retuning was requested.

The accepted upward product decision is that natural upward transformation
should use moderate relative pitch movement with restrained positive formant
movement rather than forcing every source toward one absolute F0. Natural
Bright remains a diagnostic natural-upward foundation, not a finished feminine
character.

Small / Cartoon at approximately `+6.0 st` pitch and `+2.0 st` formant was
accepted as clearly distinct from Natural Bright. Its exaggerated thin/cartoon
character is intentional, it remains an explicit creative effect, and it must
not be presented as the natural upward default.

## Non-Changes

M9.5 does not add a second pitch/formant processor, change Signalsmith
buffering, change latency, add EQ concealment, add persistence, alter settings
or preset schemas, replace production characters, change Continuous defaults,
silently mutate stored plans, or enable planner `parametric_eq` /
`spectral_tilt_shaping`.

M9.5 also does not implement phoneme modelling, speech modelling, neural
conversion, de-essing, breathiness synthesis, harmonic enhancement, spectral
tilt execution, pitch-range execution, or identity/gender classification.

## Compatibility and Truthfulness

`lower_weightier` remains a lookup compatibility alias for Natural Deep. It
resolves to canonical Natural Deep semantics, does not appear as a fifth
visible target, and stored plans use the canonical target identity.

Neutral produces zero pitch and zero formant at every strength. Neutral
dynamics remain neutral, Neutral active capabilities remain empty, and
unsupported planner capabilities do not escape as applied capabilities.

Planner `parametric_eq` and `spectral_tilt_shaping` remain unsupported.

The pre-live corrective patch also restores protected production preset
selection so normal production Pitch Shift changes remain truthful while
running. Experimental pitch/formant labs still do not expose production Pitch
Shift, and no duplicate pitch stage was introduced.

M9.6 keeps canonical target ID `diagnostic-higher-brighter` as Natural Bright
and retains legacy `higher_brighter` lookup compatibility. It adds
`diagnostic-small-cartoon` as a separate visible stylized target. Natural Deep
and Large / Cavernous values are unchanged.

The accepted visible order is Neutral, Natural Bright, Natural Deep, Small /
Cartoon, and Large / Cavernous. Accepted target values are Neutral `0 / 0`,
Natural Bright `+3.5 / +1.0`, Natural Deep `-3.5 / +1.505`, Small / Cartoon
`+6.0 / +2.0`, and Large / Cavernous `-4.5 / -1.5`.

## Known Non-Blocking Debt

Natural Bright is not a finished feminine character, and Natural Deep values
are accepted diagnostic defaults rather than a universal finished masculine
character. More source voices should eventually be tested. Finished feminine
and masculine character profiles, de-essing, breathiness, harmonic
enhancement, spectral-tilt execution, planner-driven Parametric EQ, and
optional neural voice conversion remain future work. Additional
articulation-sensitive phrase testing may continue as tuning evidence, but
does not block M9.5 or M9.6.
