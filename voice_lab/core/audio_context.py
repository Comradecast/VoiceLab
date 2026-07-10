from dataclasses import dataclass, field
from typing import Any

from voice_lab.core.audio_contract import (
    validate_block_index,
    validate_processing_stage,
    validate_sample_format,
    validate_timestamp,
)


@dataclass(frozen=True)
class AudioContext:
    sample_rate: int
    block_size: int
    frame_count: int
    sample_format: str
    input_channel_count: int
    output_channel_count: int
    block_index: int | None = None
    timestamp: Any = None
    processing_stage: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.sample_rate <= 0:
            raise ValueError("AudioContext sample_rate must be positive")
        if self.block_size < 0:
            raise ValueError("AudioContext block_size must be non-negative")
        if self.frame_count < 0:
            raise ValueError("AudioContext frame_count must be non-negative")
        if self.input_channel_count < 0:
            raise ValueError("AudioContext input_channel_count must be non-negative")
        if self.output_channel_count < 0:
            raise ValueError("AudioContext output_channel_count must be non-negative")
        validate_sample_format(self.sample_format)
        validate_block_index(self.block_index, "AudioContext")
        validate_timestamp(self.timestamp, "AudioContext")
        validate_processing_stage(self.processing_stage, "AudioContext")

    def with_stage(self, processing_stage):
        return self.with_updates(processing_stage=processing_stage)

    def with_updates(
        self,
        *,
        block_size=None,
        frame_count=None,
        sample_format=None,
        input_channel_count=None,
        output_channel_count=None,
        block_index=None,
        timestamp=None,
        processing_stage=None,
        metadata=None,
    ):
        return AudioContext(
            sample_rate=self.sample_rate,
            block_size=block_size if block_size is not None else self.block_size,
            frame_count=frame_count if frame_count is not None else self.frame_count,
            sample_format=sample_format if sample_format is not None else self.sample_format,
            input_channel_count=(
                input_channel_count if input_channel_count is not None else self.input_channel_count
            ),
            output_channel_count=(
                output_channel_count if output_channel_count is not None else self.output_channel_count
            ),
            block_index=block_index if block_index is not None else self.block_index,
            timestamp=timestamp if timestamp is not None else self.timestamp,
            processing_stage=(
                processing_stage if processing_stage is not None else self.processing_stage
            ),
            metadata=dict(metadata if metadata is not None else self.metadata),
        )
