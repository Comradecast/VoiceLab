from dataclasses import dataclass, field
from typing import Any

import numpy as np

from voice_lab.core.audio_contract import validate_samples


@dataclass(frozen=True)
class AuxiliaryAudio:
    samples: np.ndarray
    sample_rate: int
    channel_count: int
    frame_count: int
    sample_format: str
    source_type: str
    source_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.sample_rate <= 0:
            raise ValueError("AuxiliaryAudio sample_rate must be positive")
        validate_samples(
            self.samples,
            self.channel_count,
            self.frame_count,
            self.sample_format,
            "AuxiliaryAudio",
        )
        if not self.source_type:
            raise ValueError("AuxiliaryAudio source_type is required")
