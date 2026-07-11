from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class OperatorStatus:
    processing: str
    route: str
    pitch: str
    latency: str
    command_status: str
    actionable_status: str
    start_enabled: bool
    stop_enabled: bool
    diagnostics: MappingProxyType


def build_operator_status(snapshot, processing_state, active_route=None):
    active_route = dict(active_route or {})
    pitch_status = _pitch_status(snapshot)
    active_start_failure = _as_mapping(snapshot.metadata.get("active_start_failure", {}))
    actionable = _latest_actionable(snapshot, pitch_status["actionable"], active_start_failure)
    diagnostics = dict(pitch_status["diagnostics"])
    diagnostics.update(
        {
            "processing_state": processing_state,
            "route_status": snapshot.route_status,
            "audio_running": snapshot.audio_running,
            "active_start_failure_category": active_start_failure.get("category", ""),
            "active_start_failure_role": active_start_failure.get("role", ""),
            "active_start_failure_recoverable": active_start_failure.get("recoverable", ""),
        }
    )
    return OperatorStatus(
        processing=_processing_text(processing_state, snapshot),
        route=_route_text(snapshot, active_route),
        pitch=pitch_status["text"],
        latency=pitch_status["latency"],
        command_status=_command_status(snapshot),
        actionable_status=actionable,
        start_enabled=processing_state in {"stopped", "failed"},
        stop_enabled=processing_state == "running",
        diagnostics=MappingProxyType(diagnostics),
    )


def _processing_text(processing_state, snapshot):
    if processing_state == "starting":
        return "Starting"
    if processing_state == "running" or snapshot.audio_running:
        return "Running"
    if processing_state == "stopping":
        return "Stopping"
    if processing_state == "failed":
        return "Error"
    return "Stopped"


def _route_text(snapshot, active_route):
    if snapshot.route_status == "error":
        return "Route error"
    if not snapshot.audio_running:
        return "Routes stopped"
    if active_route.get("virtual_mic_active") and active_route.get("monitor_active"):
        return "Virtual mic and monitor active"
    if active_route.get("virtual_mic_active"):
        return "Virtual mic active"
    return "Route error"


def _pitch_status(snapshot):
    pitch_status = _as_mapping(snapshot.metadata.get("pitch_buffer_status", {}))
    current_params = _as_mapping(snapshot.metadata.get("current_effect_params", {}))
    semitones = _number(
        snapshot.metadata.get("current_pitch_semitones"),
        current_params.get("pitch", 0.0),
    )
    backend = str(pitch_status.get("backend", "none") or "none")
    backend_status = str(pitch_status.get("backend_status", "") or "")
    fallback_active = bool(pitch_status.get("fallback_active", False))
    last_backend_error = str(
        pitch_status.get("last_backend_error")
        or pitch_status.get("backend_reason")
        or ""
    )
    diagnostics = {
        "pitch_backend": backend,
        "pitch_backend_status": backend_status,
        "pitch_fallback_active": fallback_active,
        "pitch_semitones": semitones,
        "pitch_last_backend_error": last_backend_error,
        "pitch_configured_block_size": pitch_status.get("configured_block_size", 0),
        "pitch_configured_interval_size": pitch_status.get("configured_interval_size", 0),
        "pitch_input_latency_frames": pitch_status.get("input_latency_frames", 0),
        "pitch_output_latency_frames": pitch_status.get("output_latency_frames", 0),
        "pitch_latency_frames": pitch_status.get("latency_frames", 0),
    }

    effect_failure = _pitch_effect_failure(snapshot)
    if effect_failure:
        return {
            "text": "Pitch: Unavailable",
            "latency": "Estimated pitch DSP latency: Not active",
            "actionable": effect_failure,
            "diagnostics": diagnostics,
        }

    if abs(semitones) < 1e-6:
        return {
            "text": "Pitch: Off",
            "latency": "Estimated pitch DSP latency: Not active",
            "actionable": "",
            "diagnostics": diagnostics,
        }

    semitone_text = _semitone_text(semitones)
    latency_text = _latency_text(pitch_status)

    if fallback_active or backend == "pedalboard":
        return {
            "text": f"Pitch: Pedalboard fallback ({semitone_text})",
            "latency": latency_text,
            "actionable": "Signalsmith unavailable; Pedalboard fallback active",
            "diagnostics": diagnostics,
        }

    if backend == "signalsmith" and backend_status in {"active", "available"}:
        state = "Signalsmith" if backend_status == "active" else "Signalsmith ready"
        return {
            "text": f"Pitch: {state} ({semitone_text})",
            "latency": latency_text,
            "actionable": "",
            "diagnostics": diagnostics,
        }

    return {
        "text": "Pitch: Unavailable",
        "latency": "Estimated pitch DSP latency: Not active",
        "actionable": "No usable pitch backend",
        "diagnostics": diagnostics,
    }


def _latest_actionable(snapshot, pitch_actionable, active_start_failure=None):
    active_start_failure = active_start_failure or {}
    if active_start_failure.get("operator_message"):
        return active_start_failure["operator_message"]
    return pitch_actionable


def _command_status(snapshot):
    result = snapshot.last_command_result
    if result is not None and getattr(result, "message", ""):
        return result.message
    return snapshot.latest_status or ""


def _latency_text(pitch_status):
    value = _number(pitch_status.get("estimated_added_ms"), 0.0)
    if value <= 0:
        return "Estimated pitch DSP latency: Not active"
    return f"Estimated pitch DSP latency: {value:.1f} ms"


def _pitch_effect_failure(snapshot):
    status = snapshot.effect_chain_status
    failures = getattr(status, "failures", ()) or ()
    for failure in failures:
        if getattr(failure, "effect_name", "") == "Pitch Shift":
            message = getattr(failure, "message", "")
            return f"Pitch effect bypassed: {message}" if message else "Pitch effect bypassed"
    failed = getattr(status, "failed_effects", ()) or ()
    if "Pitch Shift" in failed:
        return "Pitch effect bypassed"
    return ""


def _semitone_text(semitones):
    value = int(semitones) if float(semitones).is_integer() else semitones
    prefix = "+" if semitones > 0 else ""
    return f"{prefix}{value} semitones"


def _number(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _as_mapping(value):
    return value if isinstance(value, dict) else {}
