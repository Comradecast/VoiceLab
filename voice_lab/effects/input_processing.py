from math import exp

import numpy as np
from scipy.signal import butter, lfilter, lfilter_zi

from voice_lab.config.input_processing import (
    CompressorSettings,
    HighPassSettings,
    LimiterSettings,
    NoiseGateSettings,
)
from voice_lab.effects.base import Effect


EPSILON = 1.0e-12
GATE_ATTACK_MS = 8.0
GATE_HOLD_MS = 50.0
GATE_RATIO = 2.5
GATE_FLOOR_DB = -36.0


def db_to_amplitude(db_value):
    return float(10.0 ** (float(db_value) / 20.0))


def sanitize_audio(mono):
    return np.nan_to_num(np.asarray(mono, dtype=np.float32), nan=0.0, posinf=1.0, neginf=-1.0)


class HighPassFilterEffect(Effect):
    name = "High-Pass"

    def __init__(self, config=None):
        self._config = config or HighPassSettings()
        self._sample_rate = None
        self._b = None
        self._a = None
        self._zi = None

    def update_config(self, config):
        self._config = config
        self._sample_rate = None

    def process(self, mono, frames, sample_rate):
        source = sanitize_audio(mono)
        if not self._config.enabled:
            return source.astype(np.float32, copy=True)
        self._ensure_filter(sample_rate)
        output, self._zi = lfilter(self._b, self._a, source, zi=self._zi)
        return output.astype(np.float32)

    def reset(self):
        self._zi = None
        self._sample_rate = None

    def _ensure_filter(self, sample_rate):
        if self._sample_rate == sample_rate and self._b is not None and self._zi is not None:
            return
        cutoff = min(float(self._config.cutoff_hz), float(sample_rate) * 0.45)
        self._b, self._a = butter(2, cutoff / (float(sample_rate) / 2.0), btype="highpass")
        self._zi = lfilter_zi(self._b, self._a).astype(np.float64) * 0.0
        self._sample_rate = sample_rate


class NoiseGateEffect(Effect):
    name = "Noise Gate"

    def __init__(self, config=None):
        self._config = config or NoiseGateSettings()
        self._gain = 1.0
        self._hold_samples_remaining = 0

    def update_config(self, config):
        self._config = config

    def process(self, mono, frames, sample_rate):
        source = sanitize_audio(mono)
        if not self._config.enabled:
            return source.astype(np.float32, copy=True)
        threshold = db_to_amplitude(self._config.threshold_dbfs)
        floor_gain = db_to_amplitude(GATE_FLOOR_DB)
        attack_coeff = _time_coeff(GATE_ATTACK_MS, sample_rate)
        release_coeff = _time_coeff(self._config.release_ms, sample_rate)
        hold_samples = int(round((GATE_HOLD_MS / 1000.0) * sample_rate))
        output = np.empty_like(source, dtype=np.float32)

        for index, sample in enumerate(source):
            level = abs(float(sample))
            if level >= threshold:
                target_gain = 1.0
                self._hold_samples_remaining = hold_samples
            elif self._hold_samples_remaining > 0:
                target_gain = 1.0
                self._hold_samples_remaining -= 1
            else:
                if level <= EPSILON:
                    target_gain = floor_gain
                else:
                    expansion = (level / threshold) ** (GATE_RATIO - 1.0)
                    target_gain = max(floor_gain, min(1.0, expansion))
            coeff = attack_coeff if target_gain > self._gain else release_coeff
            self._gain = target_gain + coeff * (self._gain - target_gain)
            output[index] = sample * self._gain
        return output

    def reset(self):
        self._gain = 1.0
        self._hold_samples_remaining = 0


class CompressorEffect(Effect):
    name = "Compressor"

    def __init__(self, config=None):
        self._config = config or CompressorSettings()
        self._gain = 1.0

    def update_config(self, config):
        self._config = config

    def process(self, mono, frames, sample_rate):
        source = sanitize_audio(mono)
        if not self._config.enabled:
            return source.astype(np.float32, copy=True)
        threshold = db_to_amplitude(self._config.threshold_dbfs)
        makeup = db_to_amplitude(self._config.makeup_gain_db)
        attack_coeff = _time_coeff(self._config.attack_ms, sample_rate)
        release_coeff = _time_coeff(self._config.release_ms, sample_rate)
        output = np.empty_like(source, dtype=np.float32)

        for index, sample in enumerate(source):
            level = abs(float(sample))
            if level <= threshold or level <= EPSILON:
                target_gain = 1.0
            else:
                level_db = 20.0 * np.log10(level)
                compressed_db = self._config.threshold_dbfs + (
                    (level_db - self._config.threshold_dbfs) / self._config.ratio
                )
                target_gain = db_to_amplitude(compressed_db - level_db)
            coeff = attack_coeff if target_gain < self._gain else release_coeff
            self._gain = target_gain + coeff * (self._gain - target_gain)
            output[index] = sample * self._gain * makeup
        return output

    def reset(self):
        self._gain = 1.0


class VoiceLimiterEffect(Effect):
    name = "Limiter"

    def __init__(self, config=None):
        self._config = config or LimiterSettings()
        self._gain = 1.0

    def update_config(self, config):
        self._config = config

    def process(self, mono, frames, sample_rate):
        source = sanitize_audio(mono)
        if not self._config.enabled:
            return source.astype(np.float32, copy=True)
        ceiling = db_to_amplitude(self._config.ceiling_dbfs)
        release_coeff = _time_coeff(self._config.release_ms, sample_rate)
        output = np.empty_like(source, dtype=np.float32)

        for index, sample in enumerate(source):
            level = abs(float(sample))
            target_gain = 1.0 if level <= ceiling or level <= EPSILON else ceiling / level
            if target_gain < self._gain:
                self._gain = target_gain
            else:
                self._gain = target_gain + release_coeff * (self._gain - target_gain)
            limited = sample * min(self._gain, 1.0)
            output[index] = np.clip(limited, -ceiling, ceiling)
        return output

    def reset(self):
        self._gain = 1.0


def _time_coeff(milliseconds, sample_rate):
    seconds = max(float(milliseconds), 0.001) / 1000.0
    return exp(-1.0 / (seconds * float(sample_rate)))
