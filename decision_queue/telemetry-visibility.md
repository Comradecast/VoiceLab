# Telemetry Visibility

Architecture Stable

## Priority

Medium

## Status

Accepted for M6.1 primary operator visibility.

## Blocks

Nothing

## Decision Owner

Chief Engineer

## Needed By

Telemetry UI and logging implementation

## Question

What telemetry events are user-visible versus log-only?

## Decision

Telemetry remains passive observation. Runtime truth stays with the owning
subsystems, telemetry collects snapshots/events, and the application layer may
derive a read-only operator-status projection for the UI. The UI must not mutate
telemetry or control runtime behavior from telemetry.

M6.1 defines three visibility levels:

### Primary operator UI

Persistent, compact state that helps an operator understand the current app
without opening a terminal:

- processing state;
- route state;
- pitch state and backend in plain language;
- visible fallback/backend warning;
- current pitch amount;
- estimated pitch DSP latency when meaningful;
- latest actionable warning or error;
- latest command/status message separately from warning/error state.

### Diagnostic detail

Read-only technical detail that may be shown in a compact secondary area or
future diagnostics surface:

- active pitch backend;
- backend status;
- fallback active flag;
- current semitones;
- estimated pitch DSP latency;
- configured block size;
- configured interval size;
- input/output latency frames;
- latest backend error;
- plugin startup summary.

### Event/log-only or retained telemetry

Verbose event history and implementation diagnostics remain in telemetry or a
future logging path rather than permanent primary UI:

- plugin discovery and manifest event streams;
- detailed event metadata;
- buffered frame counts;
- priming state;
- reset counts;
- processing call counts;
- processor identity;
- traceback-style internals.

M6.1 does not implement a persistent logging system.

## Refresh Policy

The UI may poll a narrow `ApplicationService` read method at low frequency
using the Qt UI thread. Refresh must not perform device discovery, plugin
discovery, disk I/O, configuration writes, effect construction, engine
reconstruction, or audio control. Refresh failures must remain UI-local and
must not affect audio processing.

## Error and Fallback Semantics

- Zero semitones is an intentional pitch bypass, not a warning or error.
- Signalsmith available before active pitch processing is readiness, not
  failure.
- Signalsmith active is the canonical pitch path.
- Pedalboard processing is a visible fallback warning.
- No usable backend while nonzero pitch is requested is an error.
- Effect runtime failure/bypass is shown as an actionable warning/error while
  detailed failure metadata remains telemetry.
- Audio stopped implies routes stopped.
- Monitor disabled is not monitor failure.
