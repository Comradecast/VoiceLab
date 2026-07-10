from voice_lab.engine.audio_engine import AudioEngine as _AudioEngine
from voice_lab.controllers.soundboard import load_sound
from voice_lab.io import AudioIO, Router
from voice_lab.mixer import Mixer
from voice_lab.plugins import PluginManager


class AudioEngine(_AudioEngine):
    def __init__(self):
        super().__init__()
        self._plugins = PluginManager()
        self.set_effect_chain(self._plugins.load_default_effect_chain(self))
        self._mixer = Mixer()
        self._audio_io = AudioIO()
        self._router = Router(self._audio_io)

    def start(self, input_id, output_id, monitor_id=None):
        self._mixer.set_params(
            soundboard_volume=getattr(self, "soundboard_volume", 0.70),
            monitor_volume=getattr(self, "monitor_volume", 0.35),
        )
        self._router.start(
            self,
            self._mixer,
            input_id,
            output_id,
            monitor_id,
            monitor_enabled=lambda: getattr(self, "monitor_enabled", False),
        )

    def set_params(self, gain, robot, lowpass, monitor_enabled, monitor_volume, soundboard_volume):
        super().set_params(gain, robot, lowpass)
        self.monitor_enabled = monitor_enabled
        self.monitor_volume = monitor_volume
        self.soundboard_volume = soundboard_volume
        self._mixer.set_params(
            soundboard_volume=soundboard_volume,
            monitor_volume=monitor_volume,
        )

    def play_sound(self, path):
        self._mixer.queue_sound(load_sound(path))

    def stop(self):
        self._router.stop()
        super().stop()
