import numpy as np

from voice_lab.config.config import SAMPLE_RATE
from voice_lab.core import AudioContext, AudioFrame, AuxiliaryAudio
from voice_lab.mixer.buses import OutputBuses


class Mixer:
    def __init__(self):
        self.sound_queue = []
        self.soundboard_volume = 0.70
        self.monitor_volume = 0.35

    def set_params(self, soundboard_volume, monitor_volume):
        self.soundboard_volume = soundboard_volume
        self.monitor_volume = monitor_volume

    def queue_auxiliary(self, source):
        if not isinstance(source, AuxiliaryAudio):
            raise TypeError("Mixer.queue_auxiliary expects AuxiliaryAudio")
        self.sound_queue.append({"source": source, "pos": 0})

    def queue_sound(self, data):
        """Deprecated compatibility path for legacy raw sound arrays."""
        if isinstance(data, AuxiliaryAudio):
            self.queue_auxiliary(data)
            return

        samples = np.asarray(data, dtype=np.float32)
        self.queue_auxiliary(
            AuxiliaryAudio(
                samples=samples,
                sample_rate=SAMPLE_RATE,
                channel_count=1,
                frame_count=len(samples),
                sample_format="float32",
                source_type="legacy_sound",
            )
        )

    def mix_sounds(self, frames):
        if not self.sound_queue:
            return np.zeros(frames, dtype=np.float32)

        mix = np.zeros(frames, dtype=np.float32)
        still_playing = []

        for item in self.sound_queue:
            data = item["source"].samples
            pos = item["pos"]
            chunk = data[pos:pos + frames]
            item["pos"] = pos + frames

            if len(chunk) < frames:
                padded = np.zeros(frames, dtype=np.float32)
                padded[:len(chunk)] = chunk
                chunk = padded
            else:
                still_playing.append(item)

            mix += chunk * self.soundboard_volume

        self.sound_queue = still_playing
        return np.clip(mix, -0.95, 0.95).astype(np.float32)

    def mix(self, processed_mic, frames=None):
        """Mix microphone and auxiliary audio.

        Passing raw microphone arrays is a deprecated compatibility path.
        Canonical runtime code must pass an AudioFrame.
        """
        source_frame = processed_mic if isinstance(processed_mic, AudioFrame) else None
        if isinstance(processed_mic, AudioFrame):
            frames = processed_mic.frame_count
            processed_mic = processed_mic.samples
        sounds = self.mix_sounds(frames)
        main_bus = np.clip(processed_mic + sounds, -0.95, 0.95).astype(np.float32)
        monitor_bus = np.column_stack([main_bus, main_bus]).astype(np.float32)
        monitor_bus *= self.monitor_volume
        return OutputBuses(
            main_bus=self._make_bus_frame(source_frame, main_bus, channel_count=1, stage="main_bus"),
            monitor_bus=self._make_bus_frame(
                source_frame,
                monitor_bus,
                channel_count=2,
                stage="monitor_bus",
            ),
        )

    def _make_bus_frame(self, source_frame, samples, channel_count, stage):
        if source_frame is not None:
            context = source_frame.context
            if context is not None:
                context = context.with_updates(
                    processing_stage=stage,
                    output_channel_count=channel_count,
                    frame_count=source_frame.frame_count,
                    block_size=source_frame.frame_count,
                )
            return AudioFrame(
                samples=samples,
                sample_rate=source_frame.sample_rate,
                channel_count=channel_count,
                frame_count=source_frame.frame_count,
                sample_format="float32",
                block_index=source_frame.block_index,
                timestamp=source_frame.timestamp,
                context=context,
            )

        context = AudioContext(
            sample_rate=SAMPLE_RATE,
            block_size=len(samples),
            frame_count=len(samples),
            sample_format="float32",
            input_channel_count=1,
            output_channel_count=channel_count,
            processing_stage=stage,
        )
        return AudioFrame(
            samples=samples,
            sample_rate=context.sample_rate,
            channel_count=channel_count,
            frame_count=context.frame_count,
            sample_format=context.sample_format,
            context=context,
        )
