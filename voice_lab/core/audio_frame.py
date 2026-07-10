from dataclasses import dataclass
from typing import Any

import numpy as np

from voice_lab.core.audio_contract import (
    validate_block_index,
    validate_samples,
    validate_timestamp,
)
from voice_lab.core.audio_context import AudioContext


@dataclass(frozen=True)
class AudioFrame:
    samples: np.ndarray
    sample_rate: int
    channel_count: int
    frame_count: int
    sample_format: str
    block_index: int | None = None
    timestamp: Any = None
    context: AudioContext | None = None

    def __post_init__(self):
        validate_samples(
            self.samples,
            self.channel_count,
            self.frame_count,
            self.sample_format,
            "AudioFrame",
        )
        validate_block_index(self.block_index, "AudioFrame")
        validate_timestamp(self.timestamp, "AudioFrame")
        self._validate_context()

    @property
    def mono(self):
        return self.samples

    @property
    def frames(self):
        return self.frame_count

    def _validate_context(self):
        if self.context is None:
            return
        if self.context.sample_rate != self.sample_rate:
            raise ValueError("AudioFrame context sample_rate does not match frame sample_rate")
        if self.context.frame_count != self.frame_count:
            raise ValueError("AudioFrame context frame_count does not match frame frame_count")
        if self.context.sample_format != self.sample_format:
            raise ValueError("AudioFrame context sample_format does not match frame sample_format")
        if self.context.block_index != self.block_index:
            raise ValueError("AudioFrame context block_index does not match frame block_index")
        if self.context.timestamp != self.timestamp:
            raise ValueError("AudioFrame context timestamp does not match frame timestamp")
        if self.channel_count not in (
            self.context.input_channel_count,
            self.context.output_channel_count,
        ):
            raise ValueError("AudioFrame channel_count does not match attached context")

    def with_samples(
        self,
        samples,
        *,
        channel_count=None,
        frame_count=None,
        sample_format=None,
    ):
        return AudioFrame(
            samples=samples,
            sample_rate=self.sample_rate,
            channel_count=channel_count if channel_count is not None else self.channel_count,
            frame_count=frame_count if frame_count is not None else len(samples),
            sample_format=sample_format if sample_format is not None else self.sample_format,
            block_index=self.block_index,
            timestamp=self.timestamp,
            context=self.context,
        )
