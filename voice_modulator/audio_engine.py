import numpy as np
import sounddevice as sd
import queue
from scipy.signal import butter, lfilter

from .config import SAMPLE_RATE, BLOCK_SIZE
from .soundboard import load_sound

class AudioEngine:
    def __init__(self):
        self.stream = None
        self.monitor_stream = None
        self.monitor_queue = queue.Queue(maxsize=8)
        self.sound_queue = []

        self.gain = 1.0
        self.robot = 0.0
        self.lowpass = 4000
        self.monitor_enabled = False
        self.monitor_volume = 0.35
        self.soundboard_volume = 0.70
        self.phase = 0

    def set_params(self, gain, robot, lowpass, monitor_enabled, monitor_volume, soundboard_volume):
        self.gain = gain
        self.robot = robot
        self.lowpass = lowpass
        self.monitor_enabled = monitor_enabled
        self.monitor_volume = monitor_volume
        self.soundboard_volume = soundboard_volume

    def process_voice(self, mono, frames):
        t = (np.arange(frames) + self.phase) / SAMPLE_RATE
        carrier = np.sin(2 * np.pi * 85 * t)
        self.phase += frames

        mono = mono * (1.0 - self.robot) + (mono * carrier) * self.robot

        cutoff = max(300, min(self.lowpass, 8000))
        b, a = butter(2, cutoff / (SAMPLE_RATE / 2), btype="low")
        mono = lfilter(b, a, mono)

        mono *= self.gain
        return np.clip(mono, -0.95, 0.95).astype(np.float32)

    def play_sound(self, path):
        data = load_sound(path)
        self.sound_queue.append({"data": data, "pos": 0})

    def mix_sounds(self, frames):
        if not self.sound_queue:
            return np.zeros(frames, dtype=np.float32)

        mix = np.zeros(frames, dtype=np.float32)
        still_playing = []

        for item in self.sound_queue:
            data = item["data"]
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

    def start(self, input_id, output_id, monitor_id=None):
        self.stop()
        self.monitor_queue = queue.Queue(maxsize=8)

        def main_callback(indata, outdata, frames, time_info, status):
            voice = self.process_voice(indata[:, 0].copy(), frames)
            sounds = self.mix_sounds(frames)
            mixed = np.clip(voice + sounds, -0.95, 0.95).astype(np.float32)

            outdata[:, 0] = mixed
            outdata[:, 1] = mixed

            if self.monitor_enabled and self.monitor_stream:
                stereo = np.column_stack([mixed, mixed]).astype(np.float32)
                stereo *= self.monitor_volume
                try:
                    self.monitor_queue.put_nowait(stereo)
                except queue.Full:
                    pass

        def monitor_callback(outdata, frames, time_info, status):
            try:
                data = self.monitor_queue.get_nowait()
                if len(data) < frames:
                    pad = np.zeros((frames - len(data), 2), dtype=np.float32)
                    data = np.vstack([data, pad])
                outdata[:] = data[:frames]
            except queue.Empty:
                outdata[:] = np.zeros((frames, 2), dtype=np.float32)

        if monitor_id is not None:
            self.monitor_stream = sd.OutputStream(
                samplerate=SAMPLE_RATE,
                blocksize=BLOCK_SIZE,
                dtype="float32",
                channels=2,
                device=monitor_id,
                callback=monitor_callback,
                latency="low",
            )
            self.monitor_stream.start()

        self.stream = sd.Stream(
            samplerate=SAMPLE_RATE,
            blocksize=BLOCK_SIZE,
            dtype="float32",
            channels=(1, 2),
            device=(input_id, output_id),
            callback=main_callback,
            latency="low",
        )
        self.stream.start()

    def stop(self):
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        if self.monitor_stream:
            self.monitor_stream.stop()
            self.monitor_stream.close()
            self.monitor_stream = None
