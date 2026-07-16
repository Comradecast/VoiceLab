# Unified Transformation Workflow

Status: PROVISIONAL. Implemented for M9.6 UX correction; live unified-workflow
acceptance is pending.

## Problem

The previous M9.6 laboratory surface exposed subsystem boundaries as the normal
workflow. A user had to move between Source Analysis, Target Planner, Calibrate
& Lock, Plan Execution, and Parametric EQ to complete one transformation. The
architecture was truthful, but the product flow required too much tab memory and
made stale preview versus audible runtime state too easy to confuse.

## Decision

VoiceLab now exposes a primary `Transform` page for laboratory transformation
work. The page keeps the normal task in one place:

1. Start Listening.
2. Wait for analysis readiness.
3. Calibrate Voice.
4. Select a target.
5. Choose strength.
6. Apply Transformation.
7. Adjust pitch/formant trims.
8. Optionally shape Parametric EQ.
9. Return audio to neutral, resume, or clear.

Subsystem tabs remain available for diagnostics. They read the same
ApplicationService state and are no longer required for the normal workflow.

## Atomic Apply

`ApplicationService.apply_suggested_transformation()` is the single explicit
primary apply command. It requires a valid current suggestion, locks exactly that
suggestion, enables execution, refreshes the runtime target, and returns one
coherent command result. Target and strength changes still update Preview only;
no hidden auto-apply was added.

If apply fails after lock construction begins, the prior lock, lock generation,
adaptive mode, and execution-enabled state are restored before the failure is
reported.

## State-Driven Action

The Transform page exposes one primary action whose label follows service state:

- stopped: Start Listening;
- running but source unready: Analyzing Voice...;
- ready but not calibrated: Calibrate Voice;
- calibrated with valid suggestion and no stored plan: Apply Transformation;
- stored plan retained but audio neutral: Resume Transformation;
- stored plan executing and preview unchanged: Transformation Applied;
- stored plan executing or retained and preview changed: Apply Changes.

The page also shows the current blocker when the next action is unavailable.

## Dirty State

Target, strength, calibration, or planner-input changes update Preview only. The
audible stored transformation remains unchanged until Apply Transformation or
Apply Changes succeeds. Dirty state is shown as `Changes Not Applied` in the
persistent summary and on the Transform page. Compatibility aliases resolve to
the same canonical target and must not create a false dirty state.

## Persistent Status

A compact transformation summary is visible above the tabs and derives from
ApplicationService snapshots. It includes processing state, analysis readiness,
calibration state, current target, strength, and whether audio is Applied,
Changes Not Applied, Stored/Audio Neutral, or has No Stored Transformation.

## Progressive Disclosure

The normal Transform page uses product wording: Preview, Applied
Transformation, Changes Not Applied, Manual Adjustment, and Advanced Tone
Shaping. Canonical target IDs, generation counters, authority, strategy IDs, and
capability tuples remain in Advanced Details and subsystem diagnostics.

## Parametric EQ

Parametric EQ appears on the Transform page as an optional Advanced Tone Shaping
section. It reuses the existing ParametricEqController and existing service
commands. No second EQ owner, duplicate EQ controller, duplicate EQ effect,
latency change, or planner-driven EQ compensation was added.

## Core Voice Shaping

Live M9.6 unified-workflow testing found that the primary workflow still forced
ordinary shaping edits back to the Voice and Input Processing tabs. Transform
now includes `Core Voice Shaping` between Manual Adjustment and Advanced Tone
Shaping.

Output Character exposes the existing Gain, Robot, and Lowpass authorities from
the active voice chain. Input Cleanup exposes the existing Input Processing
High-Pass enabled state and cutoff. These controls call the same service
commands and synchronize with the original pages through service-owned state.

`Open Full Input Processing` remains the route to Noise Gate, Compressor,
Limiter, and detailed input cleanup. Global Bypass Effects remains distinct
from individual effect values; Transform reports when bypass makes shaping
inaudible without clearing or toggling those values.

No Gain, Robot, Lowpass, High-Pass, Parametric EQ, or Pitch/Formant processor
was duplicated.

## Boundaries

This decision does not change DSP behavior, Signalsmith buffering, Signalsmith
latency, target values, planner formulas, target persistence, settings schema,
presets schema, production characters, or Continuous mode defaults.

M9.6 remains PROVISIONAL until Luke completes live Natural Bright and unified
workflow acceptance.
