from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class PitchFormantBackendHealth:
    backend_name: str = "signalsmith"
    backend_status: str = "unknown"
    backend_available: bool = False
    pitch_available: bool = False
    formant_available: bool = False
    effect_enabled: bool = True
    runtime_bypassed: bool = False
    failed: bool = False
    failure_code: str = ""
    failure_message: str = ""
    generation: int = 0
    last_transition_monotonic: float = 0.0
    fallback_active: bool = False
    fallback_capabilities: tuple[str, ...] = ()
    global_bypassed: bool = False
    execution_enabled: bool = False

    def with_updates(self, **changes):
        return replace(self, **changes)

