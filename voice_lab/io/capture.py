import numpy as np

from voice_lab.config.config import SAMPLE_RATE
from voice_lab.core import AudioContext, AudioFrame


InputBlock = AudioFrame


class Capture:
    def __init__(self):
        self._block_index = 0

    def capture_block(self, raw_input, frames):
        self._validate(raw_input, frames)
        mono = raw_input[:, 0].copy()
        context = AudioContext(
            sample_rate=SAMPLE_RATE,
            block_size=frames,
            frame_count=frames,
            sample_format="float32",
            input_channel_count=1,
            output_channel_count=2,
            block_index=self._block_index,
            processing_stage="capture",
        )
        frame = AudioFrame(
            samples=mono.astype(np.float32, copy=False),
            sample_rate=context.sample_rate,
            channel_count=1,
            frame_count=context.frame_count,
            sample_format=context.sample_format,
            block_index=context.block_index,
            timestamp=context.timestamp,
            context=context,
        )
        self._block_index += 1
        return frame

    def _validate(self, raw_input, frames):
        if raw_input is None:
            raise ValueError("Missing input audio block")
        if raw_input.ndim != 2:
            raise ValueError("Input audio block must be two-dimensional")
        if raw_input.shape[0] < frames:
            raise ValueError("Input audio block has fewer frames than requested")
        if raw_input.shape[1] < 1:
            raise ValueError("Input audio block must contain at least one channel")
