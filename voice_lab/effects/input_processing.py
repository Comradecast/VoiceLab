from math import exp

import numpy as np
from scipy.signal import butter, lfilter, lfilter_zi

from voice_lab.config.input_processing import (
    CompressorSettings,
    HighPassSettings,
    LimiterSettings,
    NoiseGateSettings,
    ProcessorActivity,
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
        self._activity = ProcessorActivity(enabled=self._config.enabled, cutoff_hz=self._config.cutoff_hz)

    def update_config(self, config):
        self._config = config
        self._sample_rate = None
        self._activity = ProcessorActivity(
            enabled=config.enabled,
            active=config.enabled,
            state="ENABLED" if config.enabled else "OFF",
            cutoff_hz=config.cutoff_hz,
        )

    def process(self, mono, frames, sample_rate):
        source = sanitize_audio(mono)
        if not self._config.enabled:
            self._activity = ProcessorActivity(enabled=False, state="OFF", cutoff_hz=self._config.cutoff_hz)
            return source.astype(np.float32, copy=True)
        self._ensure_filter(sample_rate)
        output, self._zi = lfilter(self._b, self._a, source, zi=self._zi)
        self._activity = ProcessorActivity(
            enabled=True,
            active=True,
            state="ENABLED",
            cutoff_hz=self._config.cutoff_hz,
        )
        return output.astype(np.float32)

    def reset(self):
        self._zi = None
        self._sample_rate = None
        self._activity = ProcessorActivity(
            enabled=self._config.enabled,
            active=False,
            state="Ready" if self._config.enabled else "OFF",
            cutoff_hz=self._config.cutoff_hz,
        )

    def activity(self):
        return self._activity

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
        self._activity = ProcessorActivity(enabled=self._config.enabled)

    def update_config(self, config):
        self._config = config
        self._activity = ProcessorActivity(
            enabled=config.enabled,
            active=False,
            state="Ready" if config.enabled else "OFF",
        )

    def process(self, mono, frames, sample_rate):
        source = sanitize_audio(mono)
        if not self._config.enabled:
            self._activity = ProcessorActivity(enabled=False, state="OFF")
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
        reduction = gain_reduction_db(self._gain)
        self._activity = ProcessorActivity(
            enabled=True,
            active=reduction > 0.1,
            state="Reducing" if reduction > 0.1 else "Open",
            gain_reduction_db=reduction,
        )
        return output

    def reset(self):
        self._gain = 1.0
        self._hold_samples_remaining = 0
        self._activity = ProcessorActivity(
            enabled=self._config.enabled,
            active=False,
            state="Ready" if self._config.enabled else "OFF",
        )

    def activity(self):
        return self._activity


class CompressorEffect(Effect):
    name = "Compressor"

    def __init__(self, config=None):
        self._config = config or CompressorSettings()
        self._gain = 1.0
        self._activity = ProcessorActivity(enabled=self._config.enabled)

    def update_config(self, config):
        self._config = config
        self._activity = ProcessorActivity(
            enabled=config.enabled,
            active=False,
            state="Ready" if config.enabled else "OFF",
        )

    def process(self, mono, frames, sample_rate):
        source = sanitize_audio(mono)
        if not self._config.enabled:
            self._activity = ProcessorActivity(enabled=False, state="OFF")
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
        reduction = gain_reduction_db(self._gain)
        self._activity = ProcessorActivity(
            enabled=True,
            active=reduction > 0.1,
            state="Reducing" if reduction > 0.1 else "Open",
            gain_reduction_db=reduction,
        )
        return output

    def reset(self):
        self._gain = 1.0
        self._activity = ProcessorActivity(
            enabled=self._config.enabled,
            active=False,
            state="Ready" if self._config.enabled else "OFF",
        )

    def activity(self):
        return self._activity


class VoiceLimiterEffect(Effect):
    name = "Limiter"

    def __init__(self, config=None):
        self._config = config or LimiterSettings()
        self._gain = 1.0
        self._activity = ProcessorActivity(enabled=self._config.enabled)

    def update_config(self, config):
        self._config = config
        self._activity = ProcessorActivity(
            enabled=config.enabled,
            active=False,
            state="Ready" if config.enabled else "OFF",
        )

    def process(self, mono, frames, sample_rate):
        source = sanitize_audio(mono)
        if not self._config.enabled:
            self._activity = ProcessorActivity(enabled=False, state="OFF")
            return source.astype(np.float32, copy=True)
        ceiling = db_to_amplitude(self._config.ceiling_dbfs)
        release_coeff = _time_coeff(self._config.release_ms, sample_rate)
        output = np.empty_like(source, dtype=np.float32)
        ceiling_hit = False

        for index, sample in enumerate(source):
            level = abs(float(sample))
            target_gain = 1.0 if level <= ceiling or level <= EPSILON else ceiling / level
            ceiling_hit = ceiling_hit or target_gain < 1.0
            if target_gain < self._gain:
                self._gain = target_gain
            else:
                self._gain = target_gain + release_coeff * (self._gain - target_gain)
            limited = sample * min(self._gain, 1.0)
            output[index] = np.clip(limited, -ceiling, ceiling)
        reduction = gain_reduction_db(self._gain)
        self._activity = ProcessorActivity(
            enabled=True,
            active=reduction > 0.1 or ceiling_hit,
            state="Limiting" if reduction > 0.1 or ceiling_hit else "Open",
            gain_reduction_db=reduction,
            ceiling_hit=ceiling_hit,
        )
        return output

    def reset(self):
        self._gain = 1.0
        self._activity = ProcessorActivity(
            enabled=self._config.enabled,
            active=False,
            state="Ready" if self._config.enabled else "OFF",
        )

    def activity(self):
        return self._activity


def _time_coeff(milliseconds, sample_rate):
    seconds = max(float(milliseconds), 0.001) / 1000.0
    return exp(-1.0 / (seconds * float(sample_rate)))


def gain_reduction_db(gain):
    safe_gain = max(float(gain), EPSILON)
    return max(0.0, float(-20.0 * np.log10(safe_gain)))
