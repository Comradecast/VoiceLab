from collections import deque

from voice_lab.telemetry.events import make_event
from voice_lab.telemetry.snapshot import TelemetrySnapshot


class TelemetryService:
    def __init__(self, max_events=100):
        self._events = deque(maxlen=max_events)
        self._latest_status = ""
        self._last_command_result = None
        self._audio_running = False
        self._route_status = "stopped"
        self._effect_chain_status = None
        self._plugin_startup_status = None
        self._metadata = {}

    def record_event(self, event_type, severity, message, **metadata):
        event = make_event(event_type, severity, message, **metadata)
        self._events.append(event)
        self._latest_status = message
        return event

    def record_command_result(self, command_name, result, **metadata):
        self._last_command_result = result
        severity = "info" if result.success else "error"
        message = result.message or f"{command_name} {'succeeded' if result.success else 'failed'}"
        return self.record_event(
            event_type=f"command.{command_name}",
            severity=severity,
            message=message,
            success=result.success,
            command=command_name,
            **metadata,
        )

    def set_audio_running(self, running):
        self._audio_running = running

    def set_route_status(self, status):
        self._route_status = status

    def set_effect_chain_status(self, status):
        self._effect_chain_status = status

    def set_plugin_startup_status(self, status):
        self._plugin_startup_status = status

    def set_metadata(self, key, value):
        self._metadata[key] = value

    def snapshot(self):
        return TelemetrySnapshot(
            latest_status=self._latest_status,
            recent_events=tuple(self._events),
            last_command_result=self._last_command_result,
            audio_running=self._audio_running,
            route_status=self._route_status,
            effect_chain_status=self._effect_chain_status,
            plugin_startup_status=self._plugin_startup_status,
            metadata=dict(self._metadata),
        )
