from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field

import numpy as np


ANALYSIS_CADENCE_HZ = 20.0
PROFILE_WINDOW_SECONDS = 12.0
MAX_PROFILE_READINGS = int(ANALYSIS_CADENCE_HZ * PROFILE_WINDOW_SECONDS)
MIN_PROFILE_VOICED_SECONDS = 2.0
MIN_READY_RETAINED_VOICED_SECONDS = 1.0
STALE_SNAPSHOT_SECONDS = 1.5
F0_MIN_HZ = 60.0
F0_MAX_HZ = 500.0
F0_CONFIDENCE_THRESHOLD = 0.42
PROFILE_CONFIDENCE_THRESHOLD = 0.50
MIN_RMS_DBFS = -55.0
DEFAULT_SAMPLE_RATE = 48000
DEFAULT_WINDOW_SECONDS = 0.096


@dataclass(frozen=True)
class VoiceAnalysisReading:
    valid: bool = False
    voiced: bool = False
    captured_at: float | None = None
    f0_hz: float | None = None
    f0_confidence: float = 0.0
    rms_dbfs: float = -120.0
    peak_dbfs: float = -120.0
    spectral_tilt_db: float | None = None
    spectral_valid: bool = False
    chest_energy_ratio: float = 0.0
    low_mid_energy_ratio: float = 0.0
    presence_energy_ratio: float = 0.0
    brightness_energy_ratio: float = 0.0
    sibilance_energy_ratio: float = 0.0
    likely_sibilant: bool = False
    f1_hz: float | None = None
    f2_hz: float | None = None
    f3_hz: float | None = None
    resonance_confidence: float = 0.0
    resonance_valid: bool = False
    reliability: str = "analyzer unavailable"

    def asdict(self):
        return asdict(self)


@dataclass(frozen=True)
class VoiceSourceProfile:
    ready: bool = False
    reliability: str = "collecting"
    voiced_frame_count: int = 0
    voiced_duration_seconds: float = 0.0
    voiced_frame_ratio: float = 0.0
    median_f0_hz: float | None = None
    lower_f0_hz: float | None = None
    upper_f0_hz: float | None = None
    pitch_span_hz: float | None = None
    pitch_span_semitones: float | None = None
    median_spectral_tilt_db: float | None = None
    chest_energy_ratio: float = 0.0
    low_mid_energy_ratio: float = 0.0
    presence_energy_ratio: float = 0.0
    brightness_energy_ratio: float = 0.0
    sibilance_energy_ratio: float = 0.0
    f1_hz: float | None = None
    f2_hz: float | None = None
    f3_hz: float | None = None
    resonance_confidence: float = 0.0

    def asdict(self):
        return asdict(self)


@dataclass(frozen=True)
class VoiceAnalysisStatus:
    active: bool = False
    worker_running: bool = False
    latest_snapshot_age_seconds: float | None = None
    analyzed_frame_count: int = 0
    dropped_frame_count: int = 0
    skipped_frame_count: int = 0
    invalid_frame_count: int = 0
    last_failure: str = ""
    source_sample_rate: int = DEFAULT_SAMPLE_RATE
    analysis_cadence_hz: float = ANALYSIS_CADENCE_HZ
    analysis_window_size: int = int(DEFAULT_SAMPLE_RATE * DEFAULT_WINDOW_SECONDS)
    retained_reading_count: int = 0
    max_retained_readings: int = MAX_PROFILE_READINGS

    def asdict(self):
        return asdict(self)


@dataclass(frozen=True)
class VoiceAnalysisSnapshot:
    current: VoiceAnalysisReading = field(default_factory=VoiceAnalysisReading)
    profile: VoiceSourceProfile = field(default_factory=VoiceSourceProfile)
    status: VoiceAnalysisStatus = field(default_factory=VoiceAnalysisStatus)

    def asdict(self):
        return {
            "current": self.current.asdict(),
            "profile": self.profile.asdict(),
            "status": self.status.asdict(),
        }


@dataclass(frozen=True)
class _AnalysisInput:
    samples: np.ndarray
    sample_rate: int
    frame_count: int
    captured_at: float


class SourceAnalysisTap:
    """Cadence-capped one-slot mailbox for raw capture frames."""

    def __init__(self, cadence_hz=ANALYSIS_CADENCE_HZ, clock=time.monotonic):
        self._clock = clock
        self._min_interval = 1.0 / float(cadence_hz) if cadence_hz else 0.0
        self._latest = None
        self._last_publish_at = None
        self._active = False
        self.dropped_frame_count = 0
        self.skipped_frame_count = 0

    def start(self):
        self._active = True
        self._latest = None
        self._last_publish_at = None
        self.dropped_frame_count = 0
        self.skipped_frame_count = 0

    def stop(self):
        self._active = False
        self._latest = None

    def publish(self, frame):
        if not self._active:
            return False
        now = self._clock()
        if self._last_publish_at is not None and now - self._last_publish_at < self._min_interval:
            self.skipped_frame_count += 1
            return False
        self._last_publish_at = now
        samples = np.asarray(getattr(frame, "samples", frame), dtype=np.float32)
        if samples.ndim == 2:
            samples = samples[:, 0]
        payload = _AnalysisInput(
            samples=samples.copy(),
            sample_rate=int(getattr(frame, "sample_rate", DEFAULT_SAMPLE_RATE)),
            frame_count=int(getattr(frame, "frame_count", samples.shape[0])),
            captured_at=now,
        )
        if self._latest is not None:
            self.dropped_frame_count += 1
        self._latest = payload
        return True

    def take_latest(self):
        latest = self._latest
        self._latest = None
        return latest


class SourceVoiceAnalyzer:
    def __init__(
        self,
        cadence_hz=ANALYSIS_CADENCE_HZ,
        clock=time.monotonic,
        sleep_seconds=0.01,
    ):
        self.clock = clock
        self.sleep_seconds = sleep_seconds
        self.tap = SourceAnalysisTap(cadence_hz=cadence_hz, clock=clock)
        self._stop_event = threading.Event()
        self._thread = None
        self._readings = deque(maxlen=MAX_PROFILE_READINGS)
        self._rolling_samples = np.zeros(0, dtype=np.float32)
        self._status = VoiceAnalysisStatus()
        self._snapshot = VoiceAnalysisSnapshot(status=self._status)
        self._analyzed = 0
        self._invalid = 0
        self._last_failure = ""
        self._source_sample_rate = DEFAULT_SAMPLE_RATE
        self._window_size = int(DEFAULT_SAMPLE_RATE * DEFAULT_WINDOW_SECONDS)
        self._profile_ready_latched = False

    def start(self):
        self.stop()
        self.reset()
        self._stop_event.clear()
        self.tap.start()
        self._thread = threading.Thread(target=self._run, name="VoiceLabSourceAnalysis", daemon=True)
        self._thread.start()
        self._refresh_snapshot(active=True)

    def stop(self):
        self.tap.stop()
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)
        self._thread = None
        self._rolling_samples = np.zeros(0, dtype=np.float32)
        self._refresh_snapshot(active=False)

    def close(self):
        self.stop()

    def reset(self):
        self._readings.clear()
        self._rolling_samples = np.zeros(0, dtype=np.float32)
        self._analyzed = 0
        self._invalid = 0
        self._last_failure = ""
        self._profile_ready_latched = False
        self._refresh_snapshot(active=self.active)

    @property
    def active(self):
        return self._thread is not None and self._thread.is_alive() and not self._stop_event.is_set()

    def snapshot(self):
        snapshot = self._snapshot
        status = snapshot.status
        age = None
        if snapshot.current.captured_at is not None:
            age = max(0.0, self.clock() - snapshot.current.captured_at)
        reliability = snapshot.current.reliability
        if status.active and age is not None and age > STALE_SNAPSHOT_SECONDS:
            reliability = "stale"
        return VoiceAnalysisSnapshot(
            current=VoiceAnalysisReading(
                **{**snapshot.current.asdict(), "reliability": reliability}
            ),
            profile=snapshot.profile,
            status=VoiceAnalysisStatus(
                **{
                    **status.asdict(),
                    "active": self.active,
                    "worker_running": self.active,
                    "latest_snapshot_age_seconds": age,
                    "dropped_frame_count": self.tap.dropped_frame_count,
                    "skipped_frame_count": self.tap.skipped_frame_count,
                }
            ),
        )

    def _run(self):
        while not self._stop_event.is_set():
            payload = self.tap.take_latest()
            if payload is None:
                time.sleep(self.sleep_seconds)
                continue
            try:
                self._analyze_payload(payload)
            except Exception as exc:
                self._last_failure = str(exc)
                self._invalid += 1
                self._refresh_snapshot(active=True, reliability="analyzer failure")

    def _analyze_payload(self, payload):
        self._source_sample_rate = payload.sample_rate
        self._window_size = max(256, int(round(payload.sample_rate * DEFAULT_WINDOW_SECONDS)))
        samples = _sanitize_samples(payload.samples)
        max_size = self._window_size
        self._rolling_samples = np.concatenate((self._rolling_samples, samples))[-max_size:]
        if self._rolling_samples.shape[0] < min(max_size, samples.shape[0]):
            return
        reading = analyze_source_voice(
            self._rolling_samples,
            payload.sample_rate,
            captured_at=payload.captured_at,
        )
        self._analyzed += 1
        if not reading.valid:
            self._invalid += 1
        self._readings.append(reading)
        self._refresh_snapshot(active=True, current=reading)

    def _refresh_snapshot(self, active, current=None, reliability=None):
        if current is None:
            current = self._snapshot.current
            if not active:
                current = VoiceAnalysisReading(reliability="analyzer unavailable")
        if reliability is not None:
            current = VoiceAnalysisReading(**{**current.asdict(), "reliability": reliability})
        profile = _build_profile(tuple(self._readings), ready_latched=self._profile_ready_latched)
        self._profile_ready_latched = bool(active and profile.ready)
        worker_running = self._thread is not None and self._thread.is_alive() and active
        status = VoiceAnalysisStatus(
            active=bool(active),
            worker_running=bool(worker_running),
            latest_snapshot_age_seconds=None,
            analyzed_frame_count=self._analyzed,
            dropped_frame_count=self.tap.dropped_frame_count,
            skipped_frame_count=self.tap.skipped_frame_count,
            invalid_frame_count=self._invalid,
            last_failure=self._last_failure,
            source_sample_rate=self._source_sample_rate,
            analysis_cadence_hz=ANALYSIS_CADENCE_HZ,
            analysis_window_size=self._window_size,
            retained_reading_count=len(self._readings),
            max_retained_readings=MAX_PROFILE_READINGS,
        )
        self._snapshot = VoiceAnalysisSnapshot(current=current, profile=profile, status=status)


def analyze_source_voice(samples, sample_rate=DEFAULT_SAMPLE_RATE, captured_at=None):
    data = _sanitize_samples(samples)
    if data.size == 0:
        return VoiceAnalysisReading(captured_at=captured_at, reliability="insufficient level")
    rms = float(np.sqrt(np.mean(np.square(data, dtype=np.float64))))
    peak = float(np.max(np.abs(data)))
    rms_dbfs = _amplitude_to_dbfs(rms)
    peak_dbfs = _amplitude_to_dbfs(peak)
    if rms_dbfs < MIN_RMS_DBFS:
        return VoiceAnalysisReading(
            valid=False,
            captured_at=captured_at,
            rms_dbfs=rms_dbfs,
            peak_dbfs=peak_dbfs,
            reliability="insufficient level",
        )

    f0_hz, f0_confidence = _estimate_f0(data, sample_rate)
    bands = _spectral_features(data, sample_rate)
    voiced = f0_hz is not None and f0_confidence >= F0_CONFIDENCE_THRESHOLD
    resonance = _resonance_features(data, sample_rate, voiced)
    likely_sibilant = (
        not voiced
        and bands["sibilance_energy_ratio"] > 0.22
        and rms_dbfs > -45.0
    )
    reliability = "ready" if voiced else "insufficient voiced speech"
    return VoiceAnalysisReading(
        valid=True,
        voiced=voiced,
        captured_at=captured_at,
        f0_hz=f0_hz if voiced else None,
        f0_confidence=f0_confidence,
        rms_dbfs=rms_dbfs,
        peak_dbfs=peak_dbfs,
        spectral_tilt_db=bands["spectral_tilt_db"],
        spectral_valid=bands["spectral_valid"],
        chest_energy_ratio=bands["chest_energy_ratio"],
        low_mid_energy_ratio=bands["low_mid_energy_ratio"],
        presence_energy_ratio=bands["presence_energy_ratio"],
        brightness_energy_ratio=bands["brightness_energy_ratio"],
        sibilance_energy_ratio=bands["sibilance_energy_ratio"],
        likely_sibilant=likely_sibilant,
        f1_hz=resonance["f1_hz"],
        f2_hz=resonance["f2_hz"],
        f3_hz=resonance["f3_hz"],
        resonance_confidence=resonance["confidence"],
        resonance_valid=resonance["valid"],
        reliability=reliability,
    )


def _build_profile(readings, ready_latched=False):
    voiced = [
        r
        for r in readings
        if r.valid and r.voiced and r.f0_hz is not None and r.f0_confidence >= PROFILE_CONFIDENCE_THRESHOLD
    ]
    voiced_duration = len(voiced) / ANALYSIS_CADENCE_HZ
    voiced_ratio = len(voiced) / len(readings) if readings else 0.0
    if not readings:
        return VoiceSourceProfile(reliability="collecting")
    if not voiced:
        return VoiceSourceProfile(
            reliability="insufficient voiced speech",
            voiced_frame_ratio=voiced_ratio,
        )

    f0_values = np.array([r.f0_hz for r in voiced], dtype=np.float64)
    lower = float(np.percentile(f0_values, 10))
    upper = float(np.percentile(f0_values, 90))
    span_hz = max(0.0, upper - lower)
    span_st = 12.0 * math.log2(upper / lower) if lower > 0.0 and upper > 0.0 else None
    ready = voiced_duration >= MIN_PROFILE_VOICED_SECONDS or (
        ready_latched and voiced_duration >= MIN_READY_RETAINED_VOICED_SECONDS
    )
    spectral_voiced = [r for r in voiced if r.spectral_valid]
    resonance_voiced = [r for r in voiced if r.resonance_valid]
    reliability = "ready" if ready else "collecting"
    return VoiceSourceProfile(
        ready=ready,
        reliability=reliability,
        voiced_frame_count=len(voiced),
        voiced_duration_seconds=voiced_duration,
        voiced_frame_ratio=voiced_ratio,
        median_f0_hz=float(np.median(f0_values)),
        lower_f0_hz=lower,
        upper_f0_hz=upper,
        pitch_span_hz=span_hz,
        pitch_span_semitones=span_st,
        median_spectral_tilt_db=_median_attr(spectral_voiced, "spectral_tilt_db"),
        chest_energy_ratio=_median_attr(spectral_voiced, "chest_energy_ratio") or 0.0,
        low_mid_energy_ratio=_median_attr(spectral_voiced, "low_mid_energy_ratio") or 0.0,
        presence_energy_ratio=_median_attr(spectral_voiced, "presence_energy_ratio") or 0.0,
        brightness_energy_ratio=_median_attr(spectral_voiced, "brightness_energy_ratio") or 0.0,
        sibilance_energy_ratio=_median_attr(spectral_voiced, "sibilance_energy_ratio") or 0.0,
        f1_hz=_median_attr(resonance_voiced, "f1_hz"),
        f2_hz=_median_attr(resonance_voiced, "f2_hz"),
        f3_hz=_median_attr(resonance_voiced, "f3_hz"),
        resonance_confidence=_median_attr(resonance_voiced, "resonance_confidence") or 0.0,
    )


def _estimate_f0(samples, sample_rate):
    data = np.asarray(samples, dtype=np.float64)
    data = data - float(np.mean(data))
    if _single_out_of_range_tone(data, sample_rate):
        return None, 0.0
    if data.size < 3:
        return None, 0.0
    window = np.hanning(data.size)
    data = data * window
    energy = float(np.dot(data, data))
    if energy <= 1e-12:
        return None, 0.0
    corr = np.correlate(data, data, mode="full")[data.size - 1 :]
    normalization = corr[0] if corr[0] > 0.0 else energy
    low_lag = max(1, int(math.floor(sample_rate / F0_MAX_HZ)))
    high_lag = min(corr.shape[0] - 1, int(math.ceil(sample_rate / F0_MIN_HZ)))
    if high_lag <= low_lag:
        return None, 0.0
    search = corr[low_lag : high_lag + 1]
    peaks = np.where((search[1:-1] > search[:-2]) & (search[1:-1] >= search[2:]))[0] + 1
    if peaks.size == 0:
        return None, 0.0
    peak_values = search[peaks]
    lag = low_lag + int(peaks[int(np.argmax(peak_values))])
    confidence = float(max(0.0, min(1.0, corr[lag] / normalization)))
    candidate = float(sample_rate / lag)
    if lag <= 0 or confidence < F0_CONFIDENCE_THRESHOLD:
        return None, confidence
    return candidate, confidence


def _spectral_features(samples, sample_rate):
    data = np.asarray(samples, dtype=np.float64)
    if data.size == 0:
        return _empty_spectral_features()
    windowed = data * np.hanning(data.size)
    nfft = 1 << max(8, int(data.size - 1).bit_length())
    spectrum = np.fft.rfft(windowed, n=nfft)
    power = np.square(np.abs(spectrum))
    freqs = np.fft.rfftfreq(nfft, 1.0 / float(sample_rate))
    total = _band_energy(freqs, power, 80.0, 10000.0)
    if total <= 1e-18:
        return _empty_spectral_features()
    low = _band_energy(freqs, power, 80.0, 900.0)
    high = _band_energy(freqs, power, 2000.0, 8000.0)
    return {
        "spectral_valid": True,
        "spectral_tilt_db": float(10.0 * math.log10((high + 1e-18) / (low + 1e-18))),
        "chest_energy_ratio": _ratio(freqs, power, total, 80.0, 300.0),
        "low_mid_energy_ratio": _ratio(freqs, power, total, 300.0, 900.0),
        "presence_energy_ratio": _ratio(freqs, power, total, 2000.0, 5000.0),
        "brightness_energy_ratio": _ratio(freqs, power, total, 5000.0, 8000.0),
        "sibilance_energy_ratio": _ratio(freqs, power, total, 5000.0, 10000.0),
    }


def _resonance_features(samples, sample_rate, voiced):
    if not voiced:
        return {"valid": False, "confidence": 0.0, "f1_hz": None, "f2_hz": None, "f3_hz": None}
    data = np.asarray(samples, dtype=np.float64) * np.hanning(len(samples))
    nfft = 1 << max(9, int(len(data) - 1).bit_length())
    magnitude = np.abs(np.fft.rfft(data, n=nfft))
    freqs = np.fft.rfftfreq(nfft, 1.0 / float(sample_rate))
    smooth_bins = max(3, int(round(80.0 / (sample_rate / nfft))))
    kernel = np.ones(smooth_bins, dtype=np.float64) / smooth_bins
    envelope = np.convolve(magnitude, kernel, mode="same")
    f1, c1 = _peak_frequency(freqs, envelope, 250.0, 900.0)
    f2, c2 = _peak_frequency(freqs, envelope, 900.0, 2500.0)
    f3, c3 = _peak_frequency(freqs, envelope, 2500.0, 3500.0)
    confidence = float(np.median([c for c in (c1, c2, c3) if c is not None] or [0.0]))
    valid = f1 is not None and f2 is not None and confidence >= 0.008
    return {
        "valid": valid,
        "confidence": confidence if valid else 0.0,
        "f1_hz": f1 if valid else None,
        "f2_hz": f2 if valid else None,
        "f3_hz": f3 if valid else None,
    }


def _peak_frequency(freqs, envelope, low, high):
    nyquist = freqs[-1] if freqs.size else 0.0
    high = min(high, nyquist)
    mask = (freqs >= low) & (freqs <= high)
    if not np.any(mask):
        return None, None
    local = envelope[mask]
    if local.size == 0 or float(np.max(local)) <= 1e-12:
        return None, None
    idx = int(np.argmax(local))
    confidence = float(np.max(local) / (np.sum(local) + 1e-18))
    return float(freqs[mask][idx]), confidence


def _single_out_of_range_tone(samples, sample_rate):
    nfft = 1 << max(9, int(len(samples) - 1).bit_length())
    spectrum = np.fft.rfft(samples * np.hanning(len(samples)), n=nfft)
    power = np.square(np.abs(spectrum))
    freqs = np.fft.rfftfreq(nfft, 1.0 / float(sample_rate))
    voiced_region = (freqs >= F0_MIN_HZ) & (freqs <= min(float(freqs[-1]), 8000.0))
    if not np.any(voiced_region):
        return False
    total = float(np.sum(power[voiced_region]))
    if total <= 1e-18:
        return False
    local_power = power[voiced_region]
    local_freqs = freqs[voiced_region]
    dominant_index = int(np.argmax(local_power))
    dominant_freq = float(local_freqs[dominant_index])
    if dominant_freq <= F0_MAX_HZ:
        return False
    dominant_ratio = float(local_power[dominant_index] / total)
    return dominant_ratio > 0.45


def _band_energy(freqs, power, low, high):
    if freqs.size == 0:
        return 0.0
    high = min(high, float(freqs[-1]))
    if high <= low:
        return 0.0
    mask = (freqs >= low) & (freqs < high)
    if not np.any(mask):
        return 0.0
    return float(np.sum(power[mask]))


def _ratio(freqs, power, total, low, high):
    if total <= 0.0:
        return 0.0
    return float(max(0.0, min(1.0, _band_energy(freqs, power, low, high) / total)))


def _empty_spectral_features():
    return {
        "spectral_valid": False,
        "spectral_tilt_db": None,
        "chest_energy_ratio": 0.0,
        "low_mid_energy_ratio": 0.0,
        "presence_energy_ratio": 0.0,
        "brightness_energy_ratio": 0.0,
        "sibilance_energy_ratio": 0.0,
    }


def _sanitize_samples(samples):
    array = np.asarray(samples, dtype=np.float32)
    if array.ndim == 2:
        array = array[:, 0]
    return np.nan_to_num(array, nan=0.0, posinf=1.0, neginf=-1.0).astype(np.float32, copy=True)


def _amplitude_to_dbfs(value):
    if not math.isfinite(value) or value <= 0.0:
        return -120.0
    return max(-120.0, min(0.0, 20.0 * math.log10(float(value))))


def _median_attr(items, attr):
    values = [getattr(item, attr) for item in items if getattr(item, attr) is not None]
    if not values:
        return None
    return float(np.median(np.asarray(values, dtype=np.float64)))
