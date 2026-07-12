from __future__ import annotations

from dataclasses import dataclass
import importlib
import importlib.util

import numpy as np


@dataclass(frozen=True)
class SignalsmithBackendStatus:
    available: bool
    backend: str
    status: str
    reason: str = ""


class SignalsmithPitchBackend:
    """VoiceLab-specific wrapper around the optional native Signalsmith module."""

    def __init__(self, sample_rate: int, block_size: int, channels: int = 1):
        try:
            module = importlib.import_module("voice_lab.effects._signalsmith_pitch")
        except Exception as exc:
            raise RuntimeError(f"Signalsmith native backend unavailable: {exc}") from exc
        self._native = module.SignalsmithPitchBackend(
            int(sample_rate),
            int(block_size),
            int(channels),
        )

    def set_semitones(self, semitones: float) -> None:
        self._native.set_semitones(float(semitones))

    def set_formant_semitones(self, semitones: float) -> None:
        self._native.set_formant_semitones(float(semitones))

    def set_formant_factor(self, factor: float) -> None:
        self._native.set_formant_factor(float(factor))

    def process(self, samples: np.ndarray) -> np.ndarray:
        mono = np.asarray(samples, dtype=np.float32)
        output = self._native.process(mono)
        return np.asarray(output, dtype=np.float32)

    def reset(self) -> None:
        self._native.reset()

    def latency_frames(self) -> int:
        return int(self._native.latency_frames())

    def input_latency_frames(self) -> int:
        return int(self._native.input_latency_frames())

    def output_latency_frames(self) -> int:
        return int(self._native.output_latency_frames())

    def close(self) -> None:
        self._native.close()


def signalsmith_status() -> SignalsmithBackendStatus:
    module_name = "voice_lab.effects._signalsmith_pitch"
    spec = importlib.util.find_spec(module_name)
    if spec is None:
        return SignalsmithBackendStatus(
            available=False,
            backend="signalsmith",
            status="native_module_missing",
            reason=f"{module_name} is not installed in the canonical package location",
        )

    try:
        importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name == module_name:
            status = "native_module_missing"
        else:
            status = "native_module_import_failure"
        return SignalsmithBackendStatus(
            available=False,
            backend="signalsmith",
            status=status,
            reason=str(exc),
        )
    except ImportError as exc:
        return SignalsmithBackendStatus(
            available=False,
            backend="signalsmith",
            status="native_module_incompatible",
            reason=str(exc),
        )
    except Exception as exc:
        return SignalsmithBackendStatus(
            available=False,
            backend="signalsmith",
            status="native_module_import_failure",
            reason=str(exc),
        )
    return SignalsmithBackendStatus(available=True, backend="signalsmith", status="active")
