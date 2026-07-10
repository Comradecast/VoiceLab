# VoiceLab Decision Queue

The Decision Queue tracks architecture decisions that are not blocking current work but must not be forgotten.

Each unresolved architecture question gets one page. The queue is not a giant TODO list; it is an owner, status, priority, blocker, and needed-by record for each decision.

## Queue State

Architecture Stable

## Open Decisions

| Decision | Priority | Status | Blocks | Needed By |
| --- | --- | --- | --- | --- |
| [Plugin metadata](decision_queue/plugin-metadata.md) | Medium | Resolved | Nothing | Plugin implementation |
| [Plugin external execution policy](decision_queue/plugin-external-execution-policy.md) | High | Open | External plugin execution | Post-RC1 plugin execution |
| [Streaming pitch backend](decision_queue/streaming-pitch-backend.md) | High | Accepted | M5 pitch quality/latency | M5.4 RC1 hardening |
| [Native pitch build artifacts](decision_queue/native-pitch-build-artifacts.md) | High | Resolved | RC1 release preparation | M5.4 repository reconciliation |
| [Configuration persistence format](decision_queue/configuration-persistence-format.md) | Medium | Open | Nothing | Configuration service implementation |
| [Configuration migration policy](decision_queue/configuration-migration-policy.md) | Low | Open | Nothing | First config version change |
| [Command interface shape](decision_queue/command-interface-shape.md) | High | Open | UI/controller integration | UI to engine integration |
| [Soundboard asset formats](decision_queue/soundboard-asset-formats.md) | Medium | Open | Soundboard implementation | Soundboard source implementation |
| [Telemetry visibility](decision_queue/telemetry-visibility.md) | Medium | Open | Nothing | Telemetry UI and logging implementation |
