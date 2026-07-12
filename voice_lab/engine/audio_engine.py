import numpy as np

from voice_lab.config.config import SAMPLE_RATE
from voice_lab.config.input_processing import (
    DEFAULT_INPUT_PROCESSING_ACTIVITY,
    DEFAULT_INPUT_PROCESSING_SETTINGS,
    InputProcessingActivity,
    bypassed_input_processing_activity,
)
from voice_lab.core import AudioFrame
from voice_lab.effects import EffectChain
from voice_lab.effects.formant_lab import FormantLabState


class AudioEngine:
    def __init__(self, effect_chain=None):
        self.gain = 1.0
        self.robot = 0.0
        self.lowpass = 4000
        self.pitch = 0.0
        self.input_processing = DEFAULT_INPUT_PROCESSING_SETTINGS
        self.formant_lab = FormantLabState()
        self.effect_chain = effect_chain or EffectChain()
        self.effects_bypassed = False

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

    def set_effects_bypassed(self, enabled):
        self.effects_bypassed = bool(enabled)

    def set_formant_lab(self, parameters):
        self.formant_lab.replace(parameters)

    def reset_formant_lab(self):
        self.formant_lab.reset()

    def formant_lab_status(self):
        for effect in self.effect_chain.effects:
            if getattr(effect, "name", "") != "Experimental Pitch/Formant":
                continue
            status = getattr(effect, "status", None)
            if status is not None:
                return status()
        return None

    def set_input_processing(self, settings):
        self.input_processing = settings
        for effect in self.effect_chain.effects:
            updater = getattr(effect, "update_config", None)
            if updater is None:
                continue
            if getattr(effect, "name", "") == "High-Pass":
                updater(settings.high_pass)
                self.effect_chain.set_enabled("High-Pass", settings.high_pass.enabled)
            elif getattr(effect, "name", "") == "Noise Gate":
                updater(settings.noise_gate)
                self.effect_chain.set_enabled("Noise Gate", settings.noise_gate.enabled)
            elif getattr(effect, "name", "") == "Compressor":
                updater(settings.compressor)
                self.effect_chain.set_enabled("Compressor", settings.compressor.enabled)
            elif getattr(effect, "name", "") == "Limiter":
                updater(settings.limiter)
                self.effect_chain.set_enabled("Limiter", settings.limiter.enabled)

    def input_processing_activity(self):
        if self.effects_bypassed:
            return bypassed_input_processing_activity(self.input_processing)
        activity = {}
        for effect in self.effect_chain.effects:
            reader = getattr(effect, "activity", None)
            if reader is None:
                continue
            name = getattr(effect, "name", "")
            if name == "High-Pass":
                activity["high_pass"] = reader()
            elif name == "Noise Gate":
                activity["noise_gate"] = reader()
            elif name == "Compressor":
                activity["compressor"] = reader()
            elif name == "Limiter":
                activity["limiter"] = reader()
        if not activity:
            return DEFAULT_INPUT_PROCESSING_ACTIVITY
        return InputProcessingActivity(
            high_pass=activity.get("high_pass", DEFAULT_INPUT_PROCESSING_ACTIVITY.high_pass),
            noise_gate=activity.get("noise_gate", DEFAULT_INPUT_PROCESSING_ACTIVITY.noise_gate),
            compressor=activity.get("compressor", DEFAULT_INPUT_PROCESSING_ACTIVITY.compressor),
            limiter=activity.get("limiter", DEFAULT_INPUT_PROCESSING_ACTIVITY.limiter),
        )

    def process_voice(self, audio, frames=None):
        """Process microphone audio.

        Passing raw arrays is a deprecated compatibility path. Canonical runtime
        code must pass and receive AudioFrame instances.
        """
        if isinstance(audio, AudioFrame):
            if self.effects_bypassed:
                return audio.with_samples(
                    audio.samples.astype(np.float32, copy=False),
                    channel_count=audio.channel_count,
                    frame_count=audio.frame_count,
                    sample_format="float32",
                )
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

        if self.effects_bypassed:
            return np.asarray(audio, dtype=np.float32)

        mono = self.effect_chain.process(audio, frames, SAMPLE_RATE)
        return np.clip(mono, -0.95, 0.95).astype(np.float32)

    def stop(self):
        reset = getattr(self.effect_chain, "reset", None)
        if reset is not None:
            reset()
        close = getattr(self.effect_chain, "close", None)
        if close is not None:
            close()
