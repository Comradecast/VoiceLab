# Calibrate, Lock, and Manual Trim

Status: Accepted. M9.3 completed live acceptance and is PASS.

M9.3 uses live source analysis to produce an operator-controlled starting point,
not as the default authority for continuous character movement. The lab captures
a frozen calibration profile, generates a suggested `TransformationPlan` through
the existing planner, and executes only after the operator explicitly locks that
plan.

Luke completed practical live Calibrate/Lock Lab acceptance. The accepted
primary workflow is:

Live source analysis -> capture frozen calibration -> generate suggested
transformation -> explicitly lock the suggestion -> enable execution -> apply
stable manual pitch/formant trims.

## Decision

- Add an isolated `--calibrate-lock-lab` launch mode.
- Keep calibration, suggestion, lock, and manual trim state session-only.
- Keep adaptive mode session-only. Do not create calibration, suggestion, lock,
  trim, or execution-cache files, and do not change settings or preset schemas.
- Validate the complete source snapshot before changing calibration, suggestion,
  lock, trim, adaptation, execution-enabled, or runtime target state.
- Store only finite numeric evidence or explicit unavailable values such as
  `None` in successful calibration snapshots. Required pitch evidence must be
  finite, positive where applicable, ordered as lower <= median <= upper, and
  within the accepted M9.0 F0 range. Optional descriptors are rejected when
  present but nonfinite.
- Use existing M9.0 source analysis, M9.1 planning, and M9.2 execution
  components. Do not add another analyzer, planner, executor, stream, router,
  pitch/formant stage, or persistence schema.
- Make Adaptive Updating Off the default. In this mode the locked plan is the
  execution authority.
- Preserve Continuous as optional explicit experimental behavior that follows
  the M9.2 live replanning behavior. Slow adaptation remains deferred.
- Apply manual pitch and formant trim as bounded deltas over the locked plan.
  Manual pitch trim is `+/-4.0` st and manual formant trim is `+/-2.0` st.
  Final runtime values still respect the M9.2 executor safety clamps.
- M9.5 adds a warning when manual trim creates negative pitch plus negative
  final applied formant, because that combination is stylized and can
  exaggerate vowels or nasal resonance. The warning is based on base plan plus
  applied trim after final clamp, and does not mutate the locked base plan or
  trim.

## Consequences

- Ordinary speech variation no longer makes mature locked execution flap between
  collecting and ready while Adaptive Updating is Off.
- Invalid calibration attempts preserve the prior calibration, suggestion, lock,
  trims, adaptation mode, execution-enabled state, and runtime target.
- Target, strength, and recalibration changes can refresh suggestions and dirty
  indicators without mutating active locked execution.
- Return to Suggested Plan clears trims without clearing the lock.
- Return to Neutral disables execution without deleting session calibration,
  suggestion, lock, or trim state.
- The workflow-truthfulness correction renames this operator action in the UI
  to Return Audio to Neutral and adds Clear Stored Transformation for the
  separate case where the operator wants to discard the locked transformation
  and manual trims. Return Audio to Neutral keeps the stored transformation;
  Clear Stored Transformation removes the lock, clears trims, disables
  execution, clears retained latest execution state, and leaves authority
  `none`.
- M9.3 remains a lab workflow and does not replace production characters.
- Manual trim remains an explicit operator override. It may intentionally move
  outside Natural Deep's positive formant compensation, but the UI must label
  negative pitch plus negative formant as stylized rather than natural.

## Accepted Authority Model

- Live analysis owns current measurements.
- Calibration owns frozen source evidence.
- The planner owns suggested transformation intent.
- Explicit Lock owns stable transformation selection.
- Manual trim owns deliberate pitch/formant offsets.
- The executor remains subordinate to the locked or adaptive
  `TransformationPlan`.
- Runtime owns smoothing and effective effect values.
- UI does not manipulate effects directly.

While Adaptive Updating is Off, live source changes, target edits, strength
edits, recalibration, and suggestion changes do not alter audio. Only explicit
re-lock or manual trim changes the selected transformation.

## M9.5 Workflow Acceptance

Final M9.5 live acceptance confirmed the corrected workflow remains reliable:

- Source Analysis readiness is published consistently.
- Calibrate Source clearly reflects prerequisites.
- Successful calibration immediately creates a suggestion.
- Lock Suggested Transformation becomes available only when a valid suggestion
  exists.
- Lock command creates a stored transformation.
- Execution applies the stored transformation.
- Exact blocker reasons are visible.
- The workflow banner uses truthful 8-step status.
- No silent calibration or lock failure remains.
- Cross-tab state is service-owned.
- No tab-owned planner or calibration state exists.

M9.5 also confirmed the manual trim and runtime-limit distinction: manual
formant trim is an additive operator authority with a `+/-2.0 st` range, while
the runtime formant safety limit remains `+/-2.0 st`. Manual trim can reach
formant zero and can deliberately produce negative final formant; those final
values remain bounded and are truthfully warned without mutating the locked
base plan.

M9.6 confirms the same policy for Natural Bright. A locked Natural Bright base
near `+3.5 st` pitch and `+1.0 st` formant can be compared with manual formant
trim at final formant `0.0`, `+0.5`, `+1.0`, `+1.5`, and `+2.0 st`. The
planner base remains immutable, trims are not rewritten automatically, final
runtime clamps remain authoritative, and no trim state is persisted.

## Live Acceptance Notes

Luke operated the Calibrate/Lock Lab for approximately 30 minutes with no
crackle, flutter, metallic tail, growing delay, sudden unexplained target
jumps, UI freeze, analyzer failure, or controller failure. Locked stable
behavior remained usable and more predictable than continuous reactive
replanning.

Known non-blocking debt remains for provisional diagnostic targets, unfinished
production character work, unsupported pitch-range mapping, parametric EQ,
spectral-tilt execution, de-essing, breathiness synthesis, harmonic
enhancement, backend availability being visible through Plan Execution rather
than duplicated fully in Calibrate & Lock, and optional future neural conversion
plugin work. These are not M9.3 failures.
