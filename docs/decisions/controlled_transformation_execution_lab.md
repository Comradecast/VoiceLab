# Controlled Transformation Execution Lab

Status: M9.2 PROVISIONAL. Live acceptance is pending.

M9.2 adds `main.py --transformation-execution-lab`, an isolated execution lab
that consumes the accepted M9.1 `TransformationPlan` and executes only the DSP
capabilities that already exist safely in VoiceLab.

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
