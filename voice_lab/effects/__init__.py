from .base import Effect
from .chain import EffectChain, EffectChainStatus, EffectFailureStatus

__all__ = [
    "Effect",
    "EffectChain",
    "EffectChainStatus",
    "EffectFailureStatus",
    "CompressorEffect",
    "ExperimentalPitchFormantEffect",
    "GainEffect",
    "HighPassFilterEffect",
    "LowpassEffect",
    "NoiseGateEffect",
    "PitchShiftEffect",
    "RobotEffect",
    "VoiceLimiterEffect",
]


def __getattr__(name):
    if name == "GainEffect":
        from .gain import GainEffect

        return GainEffect
    if name == "ExperimentalPitchFormantEffect":
        from .formant_lab import ExperimentalPitchFormantEffect

        return ExperimentalPitchFormantEffect
    if name == "HighPassFilterEffect":
        from .input_processing import HighPassFilterEffect

        return HighPassFilterEffect
    if name == "NoiseGateEffect":
        from .input_processing import NoiseGateEffect

        return NoiseGateEffect
    if name == "CompressorEffect":
        from .input_processing import CompressorEffect

        return CompressorEffect
    if name == "LowpassEffect":
        from .lowpass import LowpassEffect

        return LowpassEffect
    if name == "PitchShiftEffect":
        from .pitch_shift import PitchShiftEffect

        return PitchShiftEffect
    if name == "RobotEffect":
        from .robot import RobotEffect

        return RobotEffect
    if name == "VoiceLimiterEffect":
        from .input_processing import VoiceLimiterEffect

        return VoiceLimiterEffect
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
