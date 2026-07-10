import numpy as np

from voice_lab.config.config import SAMPLE_RATE
from voice_lab.core import AudioFrame
from voice_lab.effects import EffectChain


class AudioEngine:
    def __init__(self, effect_chain=None):
        self.gain = 1.0
        self.robot = 0.0
        self.lowpass = 4000
        self.pitch = 0.0
        self.effect_chain = effect_chain or EffectChain()

    def set_effects(self, effects):
        if isinstance(effects, EffectChain):
            self.effect_chain = effects
            return
        self.effect_chain = EffectChain(effects)

    def set_effect_chain(self, effect_chain):
        self.effect_chain = effect_chain

    @property
    def effects(self):
        return self.effect_chain.effects

    def set_params(self, gain, robot, lowpass, pitch=0.0):
        self.gain = gain
        self.robot = robot
        self.lowpass = lowpass
        self.pitch = pitch

    def process_voice(self, audio, frames=None):
        """Process microphone audio.

        Passing raw arrays is a deprecated compatibility path. Canonical runtime
        code must pass and receive AudioFrame instances.
        """
        if isinstance(audio, AudioFrame):
            context = audio.context.with_stage("engine") if audio.context else None
            processed = self.effect_chain.process(
                audio.samples,
                audio.frame_count,
                audio.sample_rate,
                context=context,
            )
            processed = np.clip(processed, -0.95, 0.95).astype(np.float32)
            processed_frame = audio.with_samples(
                processed,
                channel_count=1,
                frame_count=audio.frame_count,
                sample_format="float32",
            )
            if context is None:
                return processed_frame
            return AudioFrame(
                samples=processed_frame.samples,
                sample_rate=processed_frame.sample_rate,
                channel_count=processed_frame.channel_count,
                frame_count=processed_frame.frame_count,
                sample_format=processed_frame.sample_format,
                block_index=processed_frame.block_index,
                timestamp=processed_frame.timestamp,
                context=context,
            )

        mono = self.effect_chain.process(audio, frames, SAMPLE_RATE)
        return np.clip(mono, -0.95, 0.95).astype(np.float32)

    def stop(self):
        pass
