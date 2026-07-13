# M9.1 Adaptive Target Engine Core

## Status

Provisional after implementation and automated verification. Live hardware
acceptance remains pending.

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

Pitch center:

```text
12 * log2(target_median_f0 / source_median_f0)
```

The result is scaled by strength and clamped to the target pitch limit.

Pitch range uses `target_span / source_span`, interpolated from neutral by
strength and clamped to target range limits. Missing or near-zero source span
keeps pitch-range scale neutral without invalidating the entire plan.

Formant recommendation is target-intent based:

```text
target.nominal_formant_shift_st * strength
```

It is clamped to the target maximum and does not use F1/F2/F3 as an automatic
control source.

Spectral recommendations use:

```text
10 * log10(target_ratio / source_ratio)
```

Each band is scaled by strength and clamped independently. Missing or zero
source evidence degrades only that control.

Spectral tilt uses target tilt index minus source tilt index. The M9.0 tilt
value remains an energy-ratio index, not a fitted dB-per-octave slope.

Dynamics are recommendations only. Compressor neutral is `1:1` with `0 dB`
makeup, attack/release values are target data, and limiter values are target
data. M9.1 does not mutate M8.0 live settings.

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
- Higher / Brighter Reference;
- Lower / Weightier Reference.

They are not production characters and are not feminine, masculine,
deep-masculine, giant, or identity labels.

## Verification

Focused automated tests cover immutable contracts, validation failures, plan
states, strength behavior, pitch formulas, pitch-range behavior, formant intent
isolation from F1/F2/F3, spectral and tilt formulas, de-essing/texture/dynamics
recommendations, capability output, mode isolation, UI exposure, callback/source
guards, settings/presets compatibility, and audio transparency.

## Consequences

M9.1 creates the planning contract needed before production adaptive characters
can be implemented. It deliberately stops before any DSP application layer.
Future milestones can decide how a plan maps into actual pitch, formant, EQ,
texture, dynamics, and safety processors.
