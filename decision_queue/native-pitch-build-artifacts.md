# Native Pitch Build Artifacts

## Status

Resolved

## Priority

High

## Blocks

RC1 release preparation

## Needed By

M5.4 repository reconciliation

## Question

Should the compiled Signalsmith native module be source-controlled, packaged
separately, or rebuilt during release preparation?

## Decision

Compiled native extension artifacts such as
`voice_lab/effects/_signalsmith_pitch*.pyd` are generated build outputs and must
not be source-controlled.

The native source, vendored Signalsmith headers, build script, documentation,
and tests are source-controlled. Release preparation must build the native module
with the target runtime Python interpreter and include the resulting binary in
the release/package artifact through the release process. Runtime application
startup must not compile the extension automatically.

## Rationale

The generated module is interpreter-, platform-, and architecture-specific. The
source and build script are the stable repository inputs; the compiled binary is
a release artifact.
