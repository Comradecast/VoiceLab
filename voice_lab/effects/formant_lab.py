from dataclasses import dataclass
from math import isfinite

import numpy as np

from voice_lab.effects.base import Effect
from voice_lab.effects.pitch_shift import PitchBufferStatus, SignalsmithStreamingAdapter


FORMANT_MIN = -12.0
FORMANT_MAX = 12.0


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
        self.enabled = True
        self.pitch_semitones = 0.0
        self.formant_semitones = 0.0
        self.bypassed = False

    @property
    def formant_factor(self):
        return formant_factor(self.formant_semitones)

    def reset(self):
        self.enabled = True
        self.pitch_semitones = 0.0
        self.formant_semitones = 0.0
        self.bypassed = False


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

    def __init__(self, state):
        self.state = state
        self._adapter = None
        self._snapshot = FormantPrototypeSnapshot(
            available=True,
            active=False,
            bypassed=False,
            pitch_semitones=0.0,
            formant_semitones=0.0,
            formant_factor=1.0,
            backend="signalsmith",
            latency_frames=0,
            estimated_added_ms=0.0,
        )
        self._runtime_failure = ""
        self._last_stable_pitch = 0.0
        self._last_stable_formant = 0.0

    def process(self, mono, frames, sample_rate):
        source = np.asarray(mono, dtype=np.float32)
        pitch = float(self.state.pitch_semitones)
        formant = validate_formant_semitones(self.state.formant_semitones)
        factor = formant_factor(formant)
        if not self.state.enabled or self.state.bypassed:
            self._snapshot = self._make_snapshot(False, self.state.bypassed, pitch, formant, factor)
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
            return output
        except Exception as exc:
            self._runtime_failure = str(exc)
            self._snapshot = self._make_snapshot(False, False, pitch, formant, factor)
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
            self._adapter.reset()
        self._snapshot = self._make_snapshot(False, self.state.bypassed, self.state.pitch_semitones, self.state.formant_semitones, self.state.formant_factor)

    def close(self):
        if self._adapter is not None:
            self._adapter.close()
            self._adapter = None

    def _make_snapshot(self, active, bypassed, pitch, formant, factor):
        latency = self._adapter.status() if self._adapter is not None else None
        latency_frames = latency.latency_frames if latency is not None else 0
        estimated_ms = latency.estimated_added_ms if latency is not None else 0.0
        return FormantPrototypeSnapshot(
            available=True,
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


def validate_formant_semitones(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(float(value)):
        raise ValueError("formant semitones must be finite")
    value = float(value)
    if value < FORMANT_MIN or value > FORMANT_MAX:
        raise ValueError("formant semitones must be between -12 and 12")
    return value


def formant_factor(semitones):
    return 2.0 ** (validate_formant_semitones(semitones) / 12.0)
