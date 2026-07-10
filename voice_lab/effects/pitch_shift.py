from dataclasses import dataclass

import numpy as np
from pedalboard import PitchShift

from .base import Effect
from .signalsmith_backend import SignalsmithPitchBackend, signalsmith_status


DEFAULT_PROCESSING_WINDOW_FRAMES = 2048
DEFAULT_MAX_BUFFER_WINDOWS = 2


@dataclass(frozen=True)
class PitchBufferStatus:
    backend: str
    backend_status: str
    backend_available: bool
    backend_reason: str
    fallback_active: bool
    callback_frames: int
    processing_window_frames: int
    configured_block_size: int
    configured_interval_size: int
    buffered_input_frames: int
    buffered_output_frames: int
    estimated_added_ms: float
    processing_window_ms: float
    first_output_delay_ms: float
    max_buffer_frames: int
    priming: bool
    process_call_count: int
    reset_count: int
    silence_flush_count: int
    processor_identity: int
    last_backend_error: str = ""
    input_latency_frames: int = 0
    output_latency_frames: int = 0
    latency_frames: int = 0


class StreamingPitchAdapter:
    """Bounded adapter that turns callback blocks into larger PitchShift windows.

    Pedalboard PitchShift did not produce usable streaming output with
    ``reset=False`` in offline checks. This adapter therefore preserves callback
    continuity by collecting bounded input, processing deterministic 2048-frame
    windows, and feeding exact-size callback output from a bounded FIFO. Startup
    and pitch-change underflow return silence while the first window primes.
    Exact digital silence flushes buffered pitch output and resets the backend
    once, so stale transformed samples are not replayed after voiced input ends.
    """

    def __init__(
        self,
        semitones,
        sample_rate,
        processing_window_frames=DEFAULT_PROCESSING_WINDOW_FRAMES,
        max_buffer_windows=DEFAULT_MAX_BUFFER_WINDOWS,
    ):
        self.processing_window_frames = int(processing_window_frames)
        self.max_buffer_frames = self.processing_window_frames * int(max_buffer_windows)
        self.semitones = float(semitones)
        self.sample_rate = int(sample_rate)
        self._processor = PitchShift(semitones=self.semitones)
        self._input_fifo = np.empty(0, dtype=np.float32)
        self._output_fifo = np.empty(0, dtype=np.float32)
        self._last_callback_frames = 0
        self._saw_non_silent_input = False
        self._silence_flushed = False
        self.process_call_count = 0
        self.reset_count = 0
        self.silence_flush_count = 0

    @property
    def processor_identity(self):
        return id(self._processor)

    def reset(self, semitones=None, sample_rate=None):
        if semitones is not None:
            self.semitones = float(semitones)
        if sample_rate is not None:
            self.sample_rate = int(sample_rate)
        self._processor = PitchShift(semitones=self.semitones)
        self._input_fifo = np.empty(0, dtype=np.float32)
        self._output_fifo = np.empty(0, dtype=np.float32)
        self.reset_count += 1

    def process(self, mono, frames, sample_rate):
        frames = int(frames)
        self._last_callback_frames = frames
        if int(sample_rate) != self.sample_rate:
            self.reset(sample_rate=sample_rate)

        mono = mono.astype(np.float32, copy=False)
        if self._is_exact_silence(mono):
            return self._process_silence(frames)

        self._saw_non_silent_input = True
        self._silence_flushed = False
        self._append_input(mono)
        self._process_ready_windows()
        return self._read_output(frames)

    def status(self):
        callback_frames = self._last_callback_frames
        return PitchBufferStatus(
            backend="pedalboard",
            backend_status="fallback_active",
            backend_available=True,
            backend_reason="Signalsmith native backend unavailable; using Pedalboard compatibility adapter",
            fallback_active=True,
            callback_frames=callback_frames,
            processing_window_frames=self.processing_window_frames,
            configured_block_size=callback_frames,
            configured_interval_size=self.processing_window_frames,
            buffered_input_frames=int(self._input_fifo.shape[0]),
            buffered_output_frames=int(self._output_fifo.shape[0]),
            estimated_added_ms=(
                max(self.processing_window_frames - callback_frames, 0)
                / self.sample_rate
            )
            * 1000.0,
            processing_window_ms=(self.processing_window_frames / self.sample_rate) * 1000.0,
            first_output_delay_ms=(
                max(self.processing_window_frames - callback_frames, 0)
                / self.sample_rate
            )
            * 1000.0,
            max_buffer_frames=self.max_buffer_frames,
            priming=self._output_fifo.shape[0] < callback_frames,
            process_call_count=self.process_call_count,
            reset_count=self.reset_count,
            silence_flush_count=self.silence_flush_count,
            processor_identity=self.processor_identity,
        )

    def _is_exact_silence(self, mono):
        return mono.size == 0 or not np.any(mono)

    def _process_silence(self, frames):
        if self._saw_non_silent_input and not self._silence_flushed:
            self.reset()
            self.silence_flush_count += 1
            self._silence_flushed = True
        return np.zeros(frames, dtype=np.float32)

    def _append_input(self, mono):
        if self._input_fifo.shape[0] + mono.shape[0] > self.max_buffer_frames:
            raise RuntimeError("Pitch input buffer overflow")
        self._input_fifo = np.concatenate((self._input_fifo, mono)).astype(np.float32, copy=False)

    def _process_ready_windows(self):
        while self._input_fifo.shape[0] >= self.processing_window_frames:
            if self._output_fifo.shape[0] + self.processing_window_frames > self.max_buffer_frames:
                raise RuntimeError("Pitch output buffer overflow")
            window = self._input_fifo[: self.processing_window_frames]
            self._input_fifo = self._input_fifo[self.processing_window_frames :]
            processed = self._processor.process(
                window,
                self.sample_rate,
                buffer_size=self.processing_window_frames,
                reset=True,
            ).astype(np.float32, copy=False)
            if processed.shape[0] != self.processing_window_frames:
                raise RuntimeError(
                    "Pitch backend returned "
                    f"{processed.shape[0]} frames for {self.processing_window_frames}-frame window"
                )
            self._output_fifo = np.concatenate((self._output_fifo, processed)).astype(
                np.float32,
                copy=False,
            )
            self.process_call_count += 1

    def _read_output(self, frames):
        if self._output_fifo.shape[0] < frames:
            available = self._output_fifo.shape[0]
            output = np.zeros(frames, dtype=np.float32)
            if available:
                output[:available] = self._output_fifo
                self._output_fifo = np.empty(0, dtype=np.float32)
            return output

        output = self._output_fifo[:frames].astype(np.float32, copy=True)
        self._output_fifo = self._output_fifo[frames:]
        return output

    def close(self):
        self._input_fifo = np.empty(0, dtype=np.float32)
        self._output_fifo = np.empty(0, dtype=np.float32)


class SignalsmithStreamingAdapter:
    def __init__(self, semitones, sample_rate, block_size):
        self.sample_rate = int(sample_rate)
        self.block_size = int(block_size)
        self.semitones = float(semitones)
        self._backend = SignalsmithPitchBackend(self.sample_rate, self.block_size, channels=1)
        self._backend.set_semitones(self.semitones)
        self._last_callback_frames = 0
        self.process_call_count = 0
        self.reset_count = 0
        self.silence_flush_count = 0

    @property
    def processor_identity(self):
        return id(self._backend)

    def set_semitones(self, semitones):
        self.semitones = float(semitones)
        self._backend.set_semitones(self.semitones)

    def reset(self, semitones=None, sample_rate=None):
        if sample_rate is not None and int(sample_rate) != self.sample_rate:
            raise RuntimeError("Signalsmith backend sample-rate changes require effect reconstruction")
        if semitones is not None:
            self.semitones = float(semitones)
        self._backend.reset()
        self._backend.set_semitones(self.semitones)
        self.reset_count += 1

    def process(self, mono, frames, sample_rate):
        frames = int(frames)
        self._last_callback_frames = frames
        if frames != self.block_size:
            raise RuntimeError("Signalsmith backend requires a stable callback block size")
        if int(sample_rate) != self.sample_rate:
            raise RuntimeError("Signalsmith backend requires a stable sample rate")
        mono = mono.astype(np.float32, copy=False)
        if mono.shape != (frames,):
            raise RuntimeError("Signalsmith backend expects mono samples with shape (frames,)")
        output = self._backend.process(mono)
        if output.shape != (frames,):
            raise RuntimeError(
                f"Signalsmith backend returned {output.shape[0]} frames for {frames}-frame block"
            )
        self.process_call_count += 1
        return output.astype(np.float32, copy=False)

    def status(self):
        input_latency = self._backend.input_latency_frames()
        output_latency = self._backend.output_latency_frames()
        latency = self._backend.latency_frames()
        return PitchBufferStatus(
            backend="signalsmith",
            backend_status="active",
            backend_available=True,
            backend_reason="",
            fallback_active=False,
            callback_frames=self._last_callback_frames,
            processing_window_frames=self.block_size,
            configured_block_size=self.block_size,
            configured_interval_size=self.block_size,
            buffered_input_frames=0,
            buffered_output_frames=0,
            estimated_added_ms=(latency / self.sample_rate) * 1000.0,
            processing_window_ms=(self.block_size / self.sample_rate) * 1000.0,
            first_output_delay_ms=(output_latency / self.sample_rate) * 1000.0,
            max_buffer_frames=self.block_size,
            priming=False,
            process_call_count=self.process_call_count,
            reset_count=self.reset_count,
            silence_flush_count=self.silence_flush_count,
            processor_identity=self.processor_identity,
            input_latency_frames=input_latency,
            output_latency_frames=output_latency,
            latency_frames=latency,
        )

    def close(self):
        self._backend.close()


class PitchShiftEffect(Effect):
    name = "Pitch Shift"

    def __init__(
        self,
        get_semitones,
        processing_window_frames=DEFAULT_PROCESSING_WINDOW_FRAMES,
        prefer_signalsmith=True,
        allow_pedalboard_fallback=True,
    ):
        self.get_semitones = get_semitones
        self.processing_window_frames = processing_window_frames
        self.prefer_signalsmith = prefer_signalsmith
        self.allow_pedalboard_fallback = allow_pedalboard_fallback
        self._adapter = None
        self._last_semitones = 0.0
        self._last_status = None
        self._backend_reason = ""

    @property
    def adapter(self):
        return self._adapter

    def process(self, mono, frames, sample_rate):
        semitones = float(self.get_semitones())
        if abs(semitones) < 1e-6:
            if self._adapter is not None and self._last_semitones != 0.0:
                self._adapter.reset(semitones=0.0, sample_rate=sample_rate)
            self._last_semitones = 0.0
            self._last_status = PitchBufferStatus(
                backend="none",
                backend_status="bypassed",
                backend_available=False,
                backend_reason="Pitch semitones is zero; pitch backend intentionally bypassed",
                fallback_active=False,
                callback_frames=int(frames),
                processing_window_frames=0,
                configured_block_size=int(frames),
                configured_interval_size=0,
                buffered_input_frames=0,
                buffered_output_frames=0,
                estimated_added_ms=0.0,
                processing_window_ms=0.0,
                first_output_delay_ms=0.0,
                max_buffer_frames=0,
                priming=False,
                process_call_count=0,
                reset_count=getattr(self._adapter, "reset_count", 0) if self._adapter else 0,
                silence_flush_count=(
                    getattr(self._adapter, "silence_flush_count", 0) if self._adapter else 0
                ),
                processor_identity=0,
            )
            return mono.astype(np.float32, copy=False)

        if self._adapter is None:
            self._adapter = self._make_adapter(semitones, sample_rate, frames)
        elif semitones != self._last_semitones:
            if hasattr(self._adapter, "set_semitones"):
                self._adapter.set_semitones(semitones)
            else:
                self._adapter.reset(semitones=semitones, sample_rate=sample_rate)

        self._last_semitones = semitones
        output = self._adapter.process(mono, frames, sample_rate)
        self._last_status = self._adapter.status()
        return output

    def _make_adapter(self, semitones, sample_rate, frames):
        if self.prefer_signalsmith:
            status = signalsmith_status()
            if status.available:
                try:
                    return SignalsmithStreamingAdapter(semitones, sample_rate, frames)
                except Exception as exc:
                    self._backend_reason = f"Signalsmith backend construction failed: {exc}"
            else:
                self._backend_reason = status.reason
        if not self.allow_pedalboard_fallback:
            raise RuntimeError(self._backend_reason or "No usable pitch backend available")
        adapter = StreamingPitchAdapter(
            semitones=semitones,
            sample_rate=sample_rate,
            processing_window_frames=self.processing_window_frames,
        )
        return adapter

    def telemetry(self):
        if self._last_status is not None:
            return self._last_status
        if self._adapter is not None:
            return self._adapter.status()
        status = signalsmith_status()
        backend = "signalsmith" if status.available else "none"
        backend_status = "available" if status.available else status.status
        return PitchBufferStatus(
            backend=backend,
            backend_status=backend_status,
            backend_available=status.available,
            backend_reason=status.reason if not status.available else "",
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
            last_backend_error=status.reason if not status.available else "",
        )

    def close(self):
        if self._adapter is None:
            return
        close = getattr(self._adapter, "close", None)
        if close is not None:
            close()
        self._adapter = None
