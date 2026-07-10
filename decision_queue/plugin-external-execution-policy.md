# Plugin External Execution Policy

Architecture Stable

## Priority

High

## Status

Open

## Blocks

External plugin execution

## Decision Owner

Chief Engineer

## Needed By

Post-RC1 plugin execution

## Question

What policy governs resolving, trusting, isolating, enabling, disabling, and executing external plugin implementations?

## Current Position

External plugin execution is intentionally outside the RC1 architecture.

M4 freezes metadata, discovery, manifest loading, registration, compatibility checking, lifecycle integration, and telemetry. External manifest plugins may be discovered, loaded as metadata, registered as metadata, and reported through telemetry, but they are not executable.

## Decisions Required Before Execution

- factory resolution policy
- trust policy
- sandboxing or process isolation policy
- dependency management policy
- plugin enable/disable policy
- runtime failure containment policy for external implementations
- user-visible warning or consent policy, if any
