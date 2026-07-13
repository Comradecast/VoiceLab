from dataclasses import dataclass
from math import isfinite
from time import monotonic

import numpy as np

from voice_lab.effects.base import Effect
from voice_lab.effects.backend_health import PitchFormantBackendHealth
from voice_lab.effects.pitch_shift import PitchBufferStatus, SignalsmithStreamingAdapter
from voice_lab.effects.signalsmith_backend import signalsmith_status


FORMANT_MIN = -12.0
FORMANT_MAX = 12.0


@dataclass(frozen=True)
class FormantLabParameters:
    enabled: bool = True
    bypassed: bool = False
    pitch_semitones: float = 0.0
    formant_semitones: float = 0.0
    formant_factor: float = 1.0

    def asdict(self):
        return {
            "enabled": self.enabled,
            "bypassed": self.bypassed,
            "pitch_semitones": self.pitch_semitones,
            "formant_semitones": self.formant_semitones,
            "formant_factor": self.formant_factor,
        }


@dataclass(frozen=True)
class FormantPrototypeSnapshot:
    available: bool
    active: bool
    bypassed: bool
    pitch_semitones: float
    formant_semitones: float
    formant_factor: float
    backend: str
    latency_frames: int
    estimated_added_ms: float
    runtime_failure: str = ""
    last_stable_pitch: float = 0.0
    last_stable_formant: float = 0.0

    def asdict(self):
        return {
            "available": self.available,
            "active": self.active,
            "bypassed": self.bypassed,
            "pitch_semitones": self.pitch_semitones,
            "formant_semitones": self.formant_semitones,
            "formant_factor": self.formant_factor,
            "backend": self.backend,
            "latency_frames": self.latency_frames,
            "estimated_added_ms": self.estimated_added_ms,
            "runtime_failure": self.runtime_failure,
            "last_stable_pitch": self.last_stable_pitch,
            "last_stable_formant": self.last_stable_formant,
        }


class FormantLabState:
    def __init__(self):
        self._parameters = formant_lab_parameters()

    @property
    def parameters(self):
        return self._parameters

    @property
    def enabled(self):
        return self._parameters.enabled

    @property
    def pitch_semitones(self):
        return self._parameters.pitch_semitones

    @property
    def formant_semitones(self):
        return self._parameters.formant_semitones

    @property
    def bypassed(self):
        return self._parameters.bypassed

    @property
    def formant_factor(self):
        return self._parameters.formant_factor

    def replace(self, parameters):
        if not isinstance(parameters, FormantLabParameters):
            raise TypeError("FormantLabState.replace expects FormantLabParameters")
        self._parameters = parameters

    def reset(self):
        self._parameters = formant_lab_parameters()


class SignalsmithPitchFormantAdapter(SignalsmithStreamingAdapter):
    def __init__(self, pitch_semitones, formant_semitones, sample_rate, block_size):
        super().__init__(pitch_semitones, sample_rate, block_size)
        self.formant_semitones = float(formant_semitones)
        self._backend.set_formant_semitones(self.formant_semitones)

    def set_parameters(self, pitch_semitones, formant_semitones):
        pitch_semitones = float(pitch_semitones)
        formant_semitones = float(formant_semitones)
        if pitch_semitones != self.semitones:
            self.set_semitones(pitch_semitones)
        if formant_semitones != self.formant_semitones:
            self.formant_semitones = formant_semitones
            self._backend.set_formant_semitones(formant_semitones)


class ExperimentalPitchFormantEffect(Effect):
    name = "Experimental Pitch/Formant"

    def __init__(
        self,
        state,
        runtime_parameters_provider=None,
        latency_reporter=None,
        backend_health_reporter=None,
    ):
        self.state = state
        self._runtime_parameters_provider = runtime_parameters_provider
        self._latency_reporter = latency_reporter
        self._backend_health_reporter = backend_health_reporter
        self._adapter = None
        self._health_generation = 0
        self._health = self._initial_backend_health()
        self._snapshot = FormantPrototypeSnapshot(
            available=self._health.backend_available,
            active=False,
            bypassed=False,
            pitch_semitones=0.0,
            formant_semitones=0.0,
            formant_factor=1.0,
            backend=self._health.backend_name,
            latency_frames=0,
            estimated_added_ms=0.0,
        )
        self._runtime_failure = ""
        self._last_stable_pitch = 0.0
        self._last_stable_formant = 0.0
        self._publish_health(self._health)

    def process(self, mono, frames, sample_rate):
        source = np.asarray(mono, dtype=np.float32)
        parameters = self._parameters_for_block(frames, sample_rate)
        pitch = parameters.pitch_semitones
        formant = parameters.formant_semitones
        factor = parameters.formant_factor
        if not parameters.enabled or parameters.bypassed:
            self._snapshot = self._make_snapshot(False, parameters.bypassed, pitch, formant, factor)
            self._transition_health(effect_enabled=bool(parameters.enabled), runtime_bypassed=False, failed=False)
            return source.astype(np.float32, copy=False)
        if not self._health.backend_available:
            self._runtime_failure = self._health.failure_message
            self._snapshot = self._make_snapshot(False, False, pitch, formant, factor)
            self._transition_health(
                effect_enabled=True,
                runtime_bypassed=False,
                failed=False,
                failure_code=self._health.failure_code,
                failure_message=self._health.failure_message,
            )
            return source.astype(np.float32, copy=False)
        try:
            if self._adapter is None:
                self._adapter = SignalsmithPitchFormantAdapter(pitch, formant, sample_rate, frames)
            else:
                self._adapter.set_parameters(pitch, formant)
            output = self._adapter.process(source, frames, sample_rate)
            self._last_stable_pitch = pitch
            self._last_stable_formant = formant
            self._runtime_failure = ""
            self._snapshot = self._make_snapshot(True, False, pitch, formant, factor)
            self._transition_health(
                backend_status="active",
                backend_available=True,
                pitch_available=True,
                formant_available=True,
                effect_enabled=True,
                runtime_bypassed=False,
                failed=False,
                failure_code="",
                failure_message="",
            )
            return output
        except Exception as exc:
            self._runtime_failure = str(exc)
            self._snapshot = self._make_snapshot(False, False, pitch, formant, factor)
            self._transition_health(
                backend_available=False,
                pitch_available=False,
                formant_available=False,
                runtime_bypassed=False,
                failed=True,
                failure_code="pitch_formant_runtime_failure",
                failure_message="Pitch/formant backend failed during processing",
            )
            raise

    def status(self):
        return self._snapshot

    def telemetry(self):
        status = self._adapter.status() if self._adapter is not None else None
        if status is not None:
            return status
        return PitchBufferStatus(
            backend="signalsmith",
            backend_status="available",
            backend_available=True,
            backend_reason="",
            fallback_active=False,
            callback_frames=0,
            processing_window_frames=0,
            configured_block_size=0,
            configured_interval_size=0,
            buffered_input_frames=0,
            buffered_output_frames=0,
            estimated_added_ms=0.0,
            processing_window_ms=0.0,
            first_output_delay_ms=0.0,
            max_buffer_frames=0,
            priming=False,
            process_call_count=0,
            reset_count=0,
            silence_flush_count=0,
            processor_identity=0,
        )

    def reset(self):
        if self._adapter is not None:
            try:
                self._adapter.reset()
            except Exception:
                try:
                    self._adapter.close()
                except Exception:
                    pass
                self._adapter = None
        parameters = self.state.parameters
        self._runtime_failure = ""
        self._health = self._initial_backend_health()
        self._health_generation = self._health.generation
        self._publish_health(self._health)
        self._snapshot = self._make_snapshot(
            False,
            parameters.bypassed,
            parameters.pitch_semitones,
            parameters.formant_semitones,
            parameters.formant_factor,
        )

    def _parameters_for_block(self, frames, sample_rate):
        if self._runtime_parameters_provider is not None:
            parameters = self._runtime_parameters_provider(frames, sample_rate)
            if parameters is not None:
                return parameters
        return self.state.parameters

    def close(self):
        if self._adapter is not None:
            self._adapter.close()
            self._adapter = None

    def backend_health(self):
        return self._health

    def mark_runtime_bypassed(self, exc):
        self._runtime_failure = str(exc)
        self._transition_health(
            backend_available=False,
            pitch_available=False,
            formant_available=False,
            runtime_bypassed=True,
            failed=True,
            failure_code="pitch_formant_runtime_bypassed",
            failure_message="Pitch/formant effect runtime-bypassed after backend failure",
        )

    def _make_snapshot(self, active, bypassed, pitch, formant, factor):
        latency = self._adapter.status() if self._adapter is not None else None
        latency_frames = latency.latency_frames if latency is not None else 0
        estimated_ms = latency.estimated_added_ms if latency is not None else 0.0
        if self._latency_reporter is not None:
            self._latency_reporter(latency_frames)
        return FormantPrototypeSnapshot(
            available=self._health.backend_available,
            active=bool(active),
            bypassed=bool(bypassed),
            pitch_semitones=float(pitch),
            formant_semitones=float(formant),
            formant_factor=float(factor),
            backend="signalsmith",
            latency_frames=int(latency_frames),
            estimated_added_ms=float(estimated_ms),
            runtime_failure=self._runtime_failure,
            last_stable_pitch=self._last_stable_pitch,
            last_stable_formant=self._last_stable_formant,
        )

    def _initial_backend_health(self):
        status = signalsmith_status()
        if status.available:
            return PitchFormantBackendHealth(
                backend_name=status.backend,
                backend_status=status.status,
                backend_available=True,
                pitch_available=True,
                formant_available=True,
                generation=1,
                last_transition_monotonic=monotonic(),
            )
        return PitchFormantBackendHealth(
            backend_name=status.backend,
            backend_status=status.status,
            backend_available=False,
            pitch_available=False,
            formant_available=False,
            failure_code=status.status,
            failure_message=status.reason,
            generation=1,
            last_transition_monotonic=monotonic(),
        )

    def _transition_health(self, **changes):
        candidate = self._health.with_updates(**changes)
        comparable_current = self._health.with_updates(
            generation=0,
            last_transition_monotonic=0.0,
        )
        comparable_candidate = candidate.with_updates(
            generation=0,
            last_transition_monotonic=0.0,
        )
        if comparable_candidate != comparable_current:
            self._health_generation = max(self._health_generation, self._health.generation) + 1
            candidate = candidate.with_updates(
                generation=self._health_generation,
                last_transition_monotonic=monotonic(),
            )
            self._publish_health(candidate)
        self._health = candidate

    def _publish_health(self, health):
        self._health = health
        if self._backend_health_reporter is None:
            return
        self._backend_health_reporter(health)


def validate_formant_semitones(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(float(value)):
        raise ValueError("formant semitones must be finite")
    value = float(value)
    if value < FORMANT_MIN or value > FORMANT_MAX:
        raise ValueError("formant semitones must be between -12 and 12")
    return value


def formant_factor(semitones):
    return 2.0 ** (validate_formant_semitones(semitones) / 12.0)


def formant_lab_parameters(
    *,
    enabled=True,
    bypassed=False,
    pitch_semitones=0.0,
    formant_semitones=0.0,
):
    formant_semitones = validate_formant_semitones(formant_semitones)
    if not isinstance(pitch_semitones, (int, float)) or isinstance(pitch_semitones, bool) or not isfinite(float(pitch_semitones)):
        raise ValueError("pitch semitones must be finite")
    pitch_semitones = float(pitch_semitones)
    return FormantLabParameters(
        enabled=bool(enabled),
        bypassed=bool(bypassed),
        pitch_semitones=pitch_semitones,
        formant_semitones=formant_semitones,
        formant_factor=formant_factor(formant_semitones),
    )
