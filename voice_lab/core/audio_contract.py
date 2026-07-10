import numbers

import numpy as np


SUPPORTED_SAMPLE_FORMATS = {
    "float32": np.dtype(np.float32),
}

PROCESSING_STAGES = {
    "",
    "capture",
    "engine",
    "main_bus",
    "monitor_bus",
}


def validate_sample_format(sample_format):
    if sample_format not in SUPPORTED_SAMPLE_FORMATS:
        raise ValueError(f"Unsupported sample_format: {sample_format}")


def validate_samples(samples, channel_count, frame_count, sample_format, owner):
    if samples is None:
        raise ValueError(f"{owner} samples are required")
    if not isinstance(samples, np.ndarray):
        raise ValueError(f"{owner} samples must be a numpy.ndarray")
    if channel_count < 1:
        raise ValueError(f"{owner} channel_count must be at least 1")
    if frame_count < 0:
        raise ValueError(f"{owner} frame_count must be non-negative")

    validate_sample_format(sample_format)
    expected_dtype = SUPPORTED_SAMPLE_FORMATS[sample_format]
    if samples.dtype != expected_dtype:
        raise ValueError(
            f"{owner} sample_format {sample_format} does not match dtype {samples.dtype}"
        )

    if samples.ndim == 1:
        if channel_count != 1:
            raise ValueError(f"{owner} mono samples require channel_count=1")
        actual_frames = samples.shape[0]
    elif samples.ndim == 2:
        actual_frames = samples.shape[0]
        actual_channels = samples.shape[1]
        if channel_count != actual_channels:
            raise ValueError(
                f"{owner} channel_count {channel_count} does not match sample shape {actual_channels}"
            )
    else:
        raise ValueError(f"{owner} samples must be shape (frames,) or (frames, channels)")

    if frame_count != actual_frames:
        raise ValueError(
            f"{owner} frame_count {frame_count} does not match sample frames {actual_frames}"
        )


def validate_block_index(block_index, owner):
    if block_index is None:
        return
    if not isinstance(block_index, int) or isinstance(block_index, bool):
        raise ValueError(f"{owner} block_index must be an integer")
    if block_index < 0:
        raise ValueError(f"{owner} block_index must be non-negative")


def validate_timestamp(timestamp, owner):
    if timestamp is None:
        return
    if not isinstance(timestamp, numbers.Real) or isinstance(timestamp, bool):
        raise ValueError(f"{owner} timestamp must be a monotonic seconds value")
    if timestamp < 0:
        raise ValueError(f"{owner} timestamp must be non-negative")


def validate_processing_stage(processing_stage, owner):
    if processing_stage not in PROCESSING_STAGES:
        allowed = ", ".join(repr(stage) for stage in sorted(PROCESSING_STAGES))
        raise ValueError(f"{owner} processing_stage must be one of: {allowed}")
