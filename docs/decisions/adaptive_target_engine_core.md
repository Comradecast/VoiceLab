# M9.1 Adaptive Target Engine Core

## Status

Accepted. Final M9.1 live Target Planner Lab acceptance passed after the
zero-strength planner-neutrality correction.

## Context

M9.0 accepted a target-neutral passive source-analysis lab. It provides a
bounded in-memory source profile with practical pitch, spectral, and weak
resonance descriptors. M9.1 adds the first target-planning layer without
changing production audio.

## Decision

VoiceLab adds an explicit `main.py --target-planner-lab` mode. This mode
launches stopped, enables the M9.0 source analyzer, and shows Source Analysis
plus a planning-only Target Planner UI.

The planner relationship is:

```text
Source Voice Profile + Target Voice Profile + Character Strength =
Immutable Transformation Plan
```

The planner is pure and stateless. It reads scalar source-profile data, a frozen
target profile, and normalized strength, then returns a frozen scalar plan. It
does not depend on `AudioEngine`, `EffectChain`, `Router`, DSP effects,
settings, presets, devices, callbacks, queues, or history.

## Contracts

`TargetVoiceProfile` is a frozen scalar contract containing:

- identity and schema version;
- target median F0 and pitch-span goals;
- pitch-shift and pitch-range safety limits;
- target-intent formant hint with a `+/-2` semitone natural planning maximum;
- spectral band ratios and spectral tilt goal;
- texture goals for future breathiness and harmonic work;
- dynamics recommendations constrained by M8.0 ranges;
- capability and warning metadata.

`TransformationPlan` is a frozen scalar contract containing:

- plan identity and target identity/version;
- state, readiness, source reliability, aggregate confidence, staleness, and
  degraded/unavailable reason;
- pitch, formant, spectral, texture, and dynamics recommendations;
- required future capabilities;
- warnings.

No arrays or mutable collections are exposed as plan fields.

## Planning Rules

Pitch center supports explicit strategies. Absolute-F0 targets use:

```text
12 * log2(target_median_f0 / source_median_f0)
```

Relative-shift targets use the configured semitone offset directly. The result
is scaled by strength and clamped to the target pitch limit.

Pitch range uses `target_span / source_span`, interpolated from neutral by
strength and clamped to target range limits. Missing or near-zero source span
keeps pitch-range scale neutral without invalidating the entire plan.

Formant recommendation is target-intent based and strategy-specific:

```text
neutral: 0
restrained_fixed_shift: fixed_shift_st * strength
natural_compensation: abs(applied_downward_pitch_st) * compensation_ratio
size_coupled_stylization: fixed_shift_st * strength
```

It is clamped to the target maximum and does not use F1/F2/F3 as an automatic
control source. Natural-compensation targets are guarded from negative formant
intent regardless of pitch sign: requested negative intent remains inspectable,
but applied planner formant is clamped to `0` and the plan is degraded.
Negative pitch plus negative planner formant is reserved for an explicit
stylized large-vocal-tract target.

Spectral recommendations use:

```text
10 * log10(target_ratio / source_ratio)
```

Each band is scaled by strength and clamped independently. Missing or zero
source evidence degrades only that control.

Spectral tilt uses target tilt index minus source tilt index. The M9.0 tilt
value remains an energy-ratio index, not a fitted dB-per-octave slope.

De-essing is calculated from the maximum of three deterministic components:

```text
source_component = max(0, (source_sibilance - target_sibilance) / 0.20) * strength
brightness_component = max(0, applied_brightness_db / max_band_adjustment_db)
target_expectation_component = 0.35 * strength when target expects de-essing
```

The result is clamped to `0..1`. At `0%` strength, source sibilance and target
expectation produce no de-essing.

Dynamics are recommendations only. Compressor neutral is `1:1` with `0 dB`
makeup, attack/release values are target data, and limiter values are target
data. M9.1 does not mutate M8.0 live settings.

Capabilities describe processors required to execute the current applied plan,
not every processor that might be required by the selected target at `100%`.
Latent target requirements such as pitch-range mapping, EQ, breathiness,
harmonic enhancement, and de-essing are gated by active character strength.
At `0%` strength the applied plan is fully neutral and the capability tuple is
empty, while requested target intent remains inspectable through requested
values and target metadata.

## Source Evidence Policy

Reliable M9.0 evidence for planning:

- median F0;
- lower and upper F0;
- pitch span;
- voiced duration;
- profile readiness;
- aggregate reliability;
- chest, low-mid, presence, brightness, and sibilance energy ratios;
- spectral tilt energy-ratio index.

Weak descriptors:

- F1;
- F2;
- F3.

Approximate resonance estimates are allowed as warnings/context only. They are
not approved as direct automatic formant-shift controls.

## Isolation

M9.1 does not alter:

- normal launch;
- `--voice-analysis-lab`;
- `--formant-lab`;
- production effect chain order;
- formant-lab effect chain order;
- DSP algorithms;
- routing;
- devices;
- meters;
- soundboard behavior;
- settings schema;
- presets schema;
- built-in characters;
- Signalsmith configuration.

The Target Planner UI communicates through `ApplicationService`. It does not
import planner internals, NumPy, SciPy, audio engine code, router code, or DSP
modules.

## User Interface

The lab states:

```text
Experimental - Planning Only - Audio Is Not Modified
```

It exposes source summary, target controls, Character Strength, calculated
plan, capability/warning output, diagnostic reference loads, and reset.

There is intentionally no Apply, Preview, Save, or Export action.

## Target Neutrality

M9.1 does not classify source or target identity, gender, age, or quality. The
diagnostic references are named by acoustic direction only:

- Diagnostic Neutral;
- Natural Bright Reference;
- Natural Deep Reference;
- Small / Cartoon Reference;
- Large / Cavernous Reference.

They are not production characters and are not feminine, masculine,
deep-masculine, giant, cartoon identity, or identity labels. The previous
`lower_weightier` reference name is retained only as a compatibility alias for
Natural Deep. The legacy `higher_brighter` lookup is retained as a compatibility
alias for canonical Natural Bright semantics under target ID
`diagnostic-higher-brighter`.

## Verification

Focused automated tests cover immutable contracts, validation failures, plan
states, strength behavior, pitch formulas, pitch-range behavior, formant intent
isolation from F1/F2/F3, spectral and tilt formulas, de-essing/texture/dynamics
recommendations, capability output, mode isolation, UI exposure, callback/source
guards, settings/presets compatibility, and audio transparency.

Final live acceptance confirmed Target Planner Lab launch and isolation, Source
Analysis and Target Planner tabs, stopped launch behavior, unchanged normal,
Formant Lab, and Voice Analysis Lab modes, unchanged normal and prototype
effect chains, source collection and ready-plan behavior, Stop/reset behavior,
source-profile rebuild updating plans, no planner or analyzer failure, and
planner isolation from DSP and the audio callback.

Live zero-strength acceptance confirmed that Diagnostic Neutral, Higher /
Brighter, and Lower / Weightier all produce a fully neutral applied plan at
`0%`: zero pitch/formant/spectral/tilt/de-essing/texture movement, neutral
compressor and limiter recommendations, an empty capability tuple, and no
processor-required warnings. M9.5 extends this automated contract to Natural
Deep and Large / Cavernous. Strength interpolation, active capability
requirements, requested/applied separation, clamp/degradation behavior, stale
source behavior, F1/F2/F3 weak-descriptor status, plan confidence, and warning
readability all passed.

Live audio transparency acceptance confirmed no audible pitch, formant, EQ,
latency, metallic tail, flutter, crackle, new block boundary, meter behavior,
soundboard behavior, monitor behavior, Bypass Effects behavior, or UI-freezing
regression.

## Accepted Conclusions

- `TargetVoiceProfile` is the immutable acoustic target contract.
- `TransformationPlan` is the immutable diagnostic plan contract.
- Source profile plus target profile plus character strength is the accepted
  planning architecture.
- Pitch-center planning is accepted.
- M9.6 Natural Bright relative upward pitch planning is accepted
  provisionally: source F0 does not alter the requested semitone movement, and
  the old absolute-F0 upward target is historical audit evidence rather than
  the active natural bright target.
- Pitch-range planning is accepted as a future processor requirement.
- Restrained target-intent formant planning is accepted.
- M9.5 natural formant compensation is accepted after live Natural Deep
  acceptance: lowering pitch for a natural deep voice must not automatically
  lower formants.
- M9.6 Small / Cartoon size-coupled positive stylization is accepted
  provisionally as the upward exaggerated comparison target.
- Spectral band and tilt-index planning are accepted as diagnostic EQ
  requirements.
- De-essing planning is accepted as a future processor requirement.
- Breathiness and harmonic-weight planning are accepted as target-intent
  capability requirements.
- Dynamics recommendations are accepted as plans only and do not modify M8.0.
- Capabilities describe the current applied plan.
- Neutral has no active planner capabilities at any strength.
- `0%` character strength produces a fully neutral applied plan.
- Requested and applied values remain separately inspectable.
- Planner output remains diagnostic and does not alter audio.
- Planner state remains session-only.
- No source, target, or plan persistence is required at this stage.
- The planner performs no identity, gender, age, or speaker classification.
- Natural Bright, Natural Deep, Small / Cartoon, and Large / Cavernous remain
  diagnostic references, not finished product characters.

## Known Non-Blocking Debt

- Diagnostic target values remain provisional.
- The planner does not yet execute DSP.
- Pitch-range mapping, parametric EQ execution, de-essing, breathiness
  synthesis, and harmonic enhancement processors do not yet exist.
- Approximate F1/F2/F3 remain weak descriptors.
- Target profiles are not yet persisted.
- No finished feminine or deep-masculine character exists yet.
- These are expected future milestones, not M9.1 failures.

## Consequences

M9.1 creates the planning contract needed before production adaptive characters
can be implemented. It deliberately stops before any DSP application layer.
Future milestones can decide how a plan maps into actual pitch, formant, EQ,
texture, dynamics, and safety processors.

The next work begins applying the accepted plan to a controlled experimental
audio path. It must preserve the planner as the single source of transformation
intent, support both higher/brighter and lower/weightier directions, avoid a
one-direction-only architecture, begin as a bounded experimental execution lab,
avoid immediately replacing production characters, and preserve normal
VoiceLab behavior.
