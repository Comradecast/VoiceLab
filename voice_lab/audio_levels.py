from dataclasses import dataclass
from math import isfinite, log10, sqrt
from time import monotonic

import numpy as np


DBFS_FLOOR = -60.0
DBFS_CEILING = 0.0
OVERLOAD_THRESHOLD_DBFS = -1.0
SIGNAL_PRESENT_THRESHOLD_DBFS = -55.0
DEFAULT_PUBLICATION_HZ = 25.0


@dataclass(frozen=True)
class LevelReading:
    rms_dbfs: float
    peak_dbfs: float
    overloaded: bool
    signal_present: bool

    def asdict(self):
        return {
            "rms_dbfs": self.rms_dbfs,
            "peak_dbfs": self.peak_dbfs,
            "overloaded": self.overloaded,
            "signal_present": self.signal_present,
        }


@dataclass(frozen=True)
class AudioLevelSnapshot:
    processing_state: str
    input: LevelReading | None
    processed: LevelReading | None
    output: LevelReading | None
    monitor: LevelReading | None
    sequence: int
    captured_at: float | None

    def asdict(self):
        return {
            "processing_state": self.processing_state,
            "input": self.input.asdict() if self.input else None,
            "processed": self.processed.asdict() if self.processed else None,
            "output": self.output.asdict() if self.output else None,
            "monitor": self.monitor.asdict() if self.monitor else None,
            "sequence": self.sequence,
            "captured_at": self.captured_at,
        }


def stopped_audio_level_snapshot(processing_state="stopped"):
    return AudioLevelSnapshot(
        processing_state=str(processing_state),
        input=None,
        processed=None,
        output=None,
        monitor=None,
        sequence=0,
        captured_at=None,
    )


def calculate_level_reading(samples):
    array = np.asarray(samples)
    if array.size == 0:
        return _reading(DBFS_FLOOR, DBFS_FLOOR, overloaded=False)

    safe = np.nan_to_num(array, nan=0.0, posinf=1.0, neginf=-1.0).astype(np.float64, copy=False)
    absolute = np.abs(safe)
    peak = float(np.max(absolute)) if absolute.size else 0.0
    rms = float(sqrt(float(np.mean(safe * safe)))) if safe.size else 0.0
    peak_dbfs = _amplitude_to_dbfs(peak)
    rms_dbfs = _amplitude_to_dbfs(rms)
    return _reading(
        rms_dbfs,
        peak_dbfs,
        overloaded=peak_dbfs >= OVERLOAD_THRESHOLD_DBFS,
    )


class AudioLevelMonitor:
    def __init__(self, publication_hz=DEFAULT_PUBLICATION_HZ, clock=monotonic):
        self._clock = clock
        self._min_interval = 1.0 / float(publication_hz) if publication_hz else 0.0
        self._latest = stopped_audio_level_snapshot()
        self._sequence = 0
        self._last_publish_at = None

    def snapshot(self, processing_state=None):
        latest = self._latest
        if processing_state is None or latest.processing_state == processing_state:
            return latest
        return AudioLevelSnapshot(
            processing_state=str(processing_state),
            input=latest.input,
            processed=latest.processed,
            output=latest.output,
            monitor=latest.monitor,
            sequence=latest.sequence,
            captured_at=latest.captured_at,
        )

    def reset(self, processing_state="stopped"):
        self._sequence += 1
        self._last_publish_at = None
        self._latest = AudioLevelSnapshot(
            processing_state=str(processing_state),
            input=None,
            processed=None,
            output=None,
            monitor=None,
            sequence=self._sequence,
            captured_at=None,
        )
        return self._latest

    def publish(self, *, input_frame=None, processed_frame=None, output_frame=None, monitor_frame=None):
        now = self._clock()
        if self._last_publish_at is not None and now - self._last_publish_at < self._min_interval:
            return self._latest
        self._last_publish_at = now
        self._sequence += 1
        self._latest = AudioLevelSnapshot(
            processing_state="running",
            input=_frame_reading(input_frame),
            processed=_frame_reading(processed_frame),
            output=_frame_reading(output_frame),
            monitor=_frame_reading(monitor_frame),
            sequence=self._sequence,
            captured_at=now,
        )
        return self._latest


def _frame_reading(frame):
    if frame is None:
        return None
    samples = getattr(frame, "samples", frame)
    try:
        return calculate_level_reading(samples)
    except Exception:
        return None


def _amplitude_to_dbfs(value):
    if not isfinite(value) or value <= 0.0:
        return DBFS_FLOOR
    return _clamp_dbfs(20.0 * log10(value))


def _reading(rms_dbfs, peak_dbfs, *, overloaded):
    rms_dbfs = _clamp_dbfs(rms_dbfs)
    peak_dbfs = _clamp_dbfs(peak_dbfs)
    return LevelReading(
        rms_dbfs=rms_dbfs,
        peak_dbfs=peak_dbfs,
        overloaded=bool(overloaded),
        signal_present=rms_dbfs >= SIGNAL_PRESENT_THRESHOLD_DBFS,
    )


def _clamp_dbfs(value):
    if not isfinite(value):
        return DBFS_FLOOR
    return max(DBFS_FLOOR, min(DBFS_CEILING, float(value)))
