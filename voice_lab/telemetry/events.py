from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class TelemetryEvent:
    timestamp: datetime
    event_type: str
    severity: str
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)


def make_event(event_type, severity, message, **metadata):
    return TelemetryEvent(
        timestamp=datetime.now(timezone.utc),
        event_type=event_type,
        severity=severity,
        message=message,
        metadata=metadata,
    )
