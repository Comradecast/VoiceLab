from dataclasses import dataclass, field
from typing import Any

from voice_lab.telemetry.events import TelemetryEvent


@dataclass(frozen=True)
class TelemetrySnapshot:
    latest_status: str = ""
    recent_events: tuple[TelemetryEvent, ...] = field(default_factory=tuple)
    last_command_result: Any = None
    audio_running: bool = False
    route_status: str = "stopped"
    effect_chain_status: Any = None
    plugin_startup_status: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)
