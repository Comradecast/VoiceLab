from .base import Effect
from .chain import EffectChain, EffectChainStatus, EffectFailureStatus

__all__ = [
    "Effect",
    "EffectChain",
    "EffectChainStatus",
    "EffectFailureStatus",
    "GainEffect",
    "LowpassEffect",
    "PitchShiftEffect",
    "RobotEffect",
]


def __getattr__(name):
    if name == "GainEffect":
        from .gain import GainEffect

        return GainEffect
    if name == "LowpassEffect":
        from .lowpass import LowpassEffect

        return LowpassEffect
    if name == "PitchShiftEffect":
        from .pitch_shift import PitchShiftEffect

        return PitchShiftEffect
    if name == "RobotEffect":
        from .robot import RobotEffect

        return RobotEffect
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
