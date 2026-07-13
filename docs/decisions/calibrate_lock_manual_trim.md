# Calibrate, Lock, and Manual Trim

Status: Accepted for M9.3 provisional lab implementation.

M9.3 uses live source analysis to produce an operator-controlled starting point,
not as the default authority for continuous character movement. The lab captures
a frozen calibration profile, generates a suggested `TransformationPlan` through
the existing planner, and executes only after the operator explicitly locks that
plan.

## Decision

- Add an isolated `--calibrate-lock-lab` launch mode.
- Keep calibration, suggestion, lock, and manual trim state session-only.
- Use existing M9.0 source analysis, M9.1 planning, and M9.2 execution
  components. Do not add another analyzer, planner, executor, stream, router,
  pitch/formant stage, or persistence schema.
- Make Adaptive Updating Off the default. In this mode the locked plan is the
  execution authority.
- Preserve Continuous as an optional experimental mode that follows the M9.2
  live replanning behavior.
- Apply manual pitch and formant trim as bounded deltas over the locked plan,
  with final runtime values still clamped by the M9.2 executor.

## Consequences

- Ordinary speech variation no longer makes mature locked execution flap between
  collecting and ready while Adaptive Updating is Off.
- Target, strength, and recalibration changes can refresh suggestions and dirty
  indicators without mutating active locked execution.
- Return to Suggested Plan clears trims without clearing the lock.
- Return to Neutral disables execution without deleting session calibration,
  suggestion, lock, or trim state.
- M9.3 remains a lab workflow and does not replace production characters.
