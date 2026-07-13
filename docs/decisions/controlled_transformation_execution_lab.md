# Controlled Transformation Execution Lab

Status: M9.2 PASS. Luke completed practical live Transformation Execution Lab
acceptance.

M9.2 adds `main.py --transformation-execution-lab`, an isolated execution lab
that consumes the accepted M9.1 `TransformationPlan` and executes only the DSP
capabilities that already exist safely in VoiceLab.

M9.2 is accepted as execution infrastructure. Continuous reactive replanning is
not accepted as the final normal character-control experience; it remains an
experimental diagnostic/adaptive behavior.

## Authority Boundary

`TransformationPlanner` remains the only transformation-intent authority. The
executor accepts an immutable `TransformationPlan`, an explicit operator
enabled flag, the current M8.0 baseline input-processing settings, and bypass
state. It validates and maps supported plan values to runtime controls. It does
not read source or target profiles directly, recalculate pitch/formant/EQ
intent, process samples, persist state, control streams, query devices, or call
Qt.

## Supported And Unsupported Capabilities

M9.2 executes only:

- `adaptive_pitch_center`
- `formant_shift`
- `compressor`
- `limiter`

Unsupported capabilities are reported deterministically and are not
approximated:

- `pitch_range_mapping`
- `parametric_eq`
- `spectral_tilt_shaping`
- `breathiness`
- `harmonic_enhancement`
- `de_esser`
- unknown future identifiers

Partial execution is allowed when supported and unsupported requirements appear
together. Unsupported processors do not make the whole plan fail solely because
they are unsupported.

Execution reporting distinguishes planned capabilities, M9.2-supported
capabilities, current backend-executable capabilities, actively executing
capabilities, backend-unavailable capabilities, and unknown capabilities.
Pitch/formant support is reported only when the current combined backend can
execute it.
The execution snapshot also reports requested pitch shift separately from the
applied pitch target and marks pitch saturation when the M9.1 diagnostic target
math hits the target's maximum pitch shift.

## Runtime Design

The execution lab reuses the accepted Formant Lab chain:

High-Pass -> Noise Gate -> Compressor -> Experimental Pitch/Formant -> Robot
-> Lowpass -> Gain -> Limiter -> Mixer.

The executor maps `TransformationPlan.pitch.applied_pitch_shift_st` and
`TransformationPlan.formant.applied_formant_shift_st` exactly. Compressor and
Limiter overrides come from the plan dynamics recommendation only when the plan
requests those capabilities and strength is active.

Runtime state is held as immutable scalar targets plus scalar runtime snapshot
values. The callback reads one complete pitch/formant parameter pair per block
through the existing experimental Signalsmith effect and reads session-only
Compressor/Limiter overlay values through the existing effects. Planner and
executor mapping never run in the audio callback.

The combined pitch/formant effect publishes one immutable scalar backend-health
snapshot. The runtime retains only the latest health snapshot. The audio
callback does not call Qt, ApplicationService, settings, file I/O, or controller
work when publishing health.

If the native backend is unavailable, pitch and formant become backend
unavailable and their executable targets are neutralized. If a runtime backend
failure causes EffectChain to bypass the combined effect, pitch and formant stop
appearing as active execution capabilities, `last_failure` is populated, and
finite audio continues through the existing EffectChain safety behavior.
Compressor and Limiter overlays may continue when valid, so backend loss in the
combined pitch/formant stage degrades only those capabilities. Recovery from a
runtime-bypassed combined effect is Stop, then Start; Start begins execution
disabled and re-evaluates backend health.

## Dynamics And Neutrality

M8.0 settings remain the baseline. Disabled execution, 0% strength, stale
source, invalid plan, controller failure, Stop, and Return to Neutral all remove
planner-induced dynamics overlays and return pitch/formant targets toward zero.
Neutral execution means no planner-induced deviation from the execution-lab
baseline; it does not disable the user's M8.0 safety processing.

## Controller

The controller cadence is 10 Hz. It retains only the latest source snapshot,
latest target profile, latest complete plan, and latest execution target. It
uses latest-state replacement, not an unbounded queue or history. The worker is
started with audio processing and stopped/joined on Stop and close.

## Smoothing And Deadband

Pitch and formant use bounded per-block scalar smoothing inside the runtime
parameter read path. The deadband is 0.01 semitones; sub-deadband target changes
do not republish a new runtime target. Dynamics overlays switch between valid
whole-setting snapshots and fail closed to baseline on invalid values.

## Bypass And Latency

Global Bypass Effects remains the single bypass authority. While bypassed,
execution status reports `bypassed`; removing bypass resumes through the same
runtime smoothing path.

Latency is inherited from the accepted combined Signalsmith pitch/formant stage
used by Formant Lab. M9.2 does not insert another pitch/formant processor or a
second full buffering stage. Previously accepted evidence was about 4800 frames,
approximately 100 ms at 48 kHz.

## Session Scope

No target-profile file, plan file, execution cache, settings schema change,
preset schema change, production voice, recording path, or export path is added.
The lab is session-only and launches disabled.

Application-facing execution snapshots are frozen dataclasses with frozen
nested compressor, limiter, and pitch/formant backend snapshots. UI code must
not receive effect objects, stream objects, workers, NumPy arrays, mutable
dictionaries, or mutable lists from the execution snapshot.

## Live Acceptance

Luke's final live acceptance recorded PASS for mode/lifecycle isolation,
audible pitch execution in the planned direction, the formant execution path,
visible target/current runtime values, finite stable active transformation, and
absence of metallic artifacts, flutter, crackle, or new audible block
boundaries. One combined Signalsmith pitch/formant stage remains in use and no
second full latency stage was introduced.

Neutrality and safety passed: disabled execution and 0% strength remain
neutral, Return to Neutral works, disabling execution restores neutral planner
influence, M8.0 baseline processing remains available, unsupported processors
remain visible and are not approximated, stale/unsafe states fail closed, and
global bypass remains the single bypass authority.

Backend truthfulness passed after the backend-health fix: native Signalsmith
health is shown, pitch/formant availability is reported truthfully,
runtime-bypassed effects are not reported as active, backend-unavailable and
runtime backend failure states are explicit, execution snapshots distinguish
planned/supported/executable/active/unsupported/backend-unavailable
capabilities, and application snapshots are immutable.

Readiness stability passed after the rolling-profile hysteresis fix: the
current voiced/unvoiced reading remains separate from rolling readiness, reset
still clears readiness, and stale/failure/inactive gates remain separate.

Target and clamp reporting passed: requested pitch, applied target pitch,
current smoothed pitch, and saturation/clamping are visible. Higher / Brighter
saturation at high strength is mathematically understood, runtime current value
follows the applied target rather than the unclamped request, and lowering
strength reduces the execution target.

Session and persistence passed: no target-profile file, plan file, or execution
cache is created; `settings.json` and `presets.json` remain unchanged;
execution state is session-only; and normal production characters remain
unchanged.

## Accepted Technical Conclusions

- `TransformationExecutor` is accepted as subordinate to `TransformationPlan`.
- The planner remains the sole transformation-intent authority.
- M9.2 executes only supported capabilities.
- Unsupported capabilities remain visible and are not approximated.
- Adaptive pitch-center execution is accepted.
- Restrained formant execution is accepted.
- Session-only compressor and limiter overlays are accepted.
- Runtime smoothing is accepted for controlled experimental execution.
- Backend-health propagation is accepted.
- Immutable execution snapshots are accepted.
- Readiness hysteresis is accepted.
- One combined Signalsmith pitch/formant stage is accepted.
- Inherited latency remains approximately 4800 frames / 100 ms at 48 kHz.
- M9.2 does not replace production characters.
- M9.2 does not establish continuous reactive replanning as the final user
  experience.

## Product-Control Conclusion

Continuous source-driven replanning can feel as though the selected character
is moving underneath the operator. Therefore continuous replanning remains an
experimental adaptive mode and must not become the default production character
behavior.

The next milestone will introduce calibration, plan locking, and stable manual
trim. Ordinary character use should eventually hold selected values until the
operator changes or recalibrates them. Live source analysis remains useful for
producing a suggested starting plan, but source analysis should not
continuously override deliberate operator control by default.

## Next Milestone Direction

The next milestone is Calibrate, Lock, and Manual Trim.

Conceptual flow:

Source analysis -> capture a calibration profile -> generate a suggested
`TransformationPlan` -> lock the plan -> execute stable fixed values -> allow
manual trims.

Expected controls include Calibrate Source, Lock Suggested Transformation,
Recalibrate, Pitch Trim, Formant Trim, Character Strength, Return to Suggested
Plan, Return to Neutral, and Adaptive Updating default Off.

The next milestone must preserve M9.0 source analysis, M9.1 planning, and M9.2
execution; retain continuous adaptation only as an optional experimental mode;
make locked stable execution the primary lab workflow; avoid production
character replacement; and avoid target or plan persistence unless explicitly
scoped later.

## Optional Neural Conversion Boundary

Neural voice conversion remains a future optional plugin capability. It is not
a required VoiceLab core feature, and it must be loadable, disableable,
replaceable, and absent without breaking VoiceLab. Current development remains
focused on stable DSP character control. No neural dependencies or
implementation are part of M9.2 or the immediate next milestone.

## Known Non-Blocking Debt

Continuous adaptation is not the preferred default UX. No plan-lock workflow or
manual pitch/formant trim exists yet. Pitch-range mapping, parametric EQ,
spectral-tilt shaping, de-essing, breathiness synthesis, and harmonic
enhancement remain unsupported. Diagnostic target values remain provisional,
and no finished feminine or deep-masculine character exists yet. These are
future milestones rather than M9.2 failures.
