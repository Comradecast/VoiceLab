import sounddevice as sd

from voice_lab.config.config import BLOCK_SIZE, SAMPLE_RATE
from voice_lab.core import AudioFrame


class AudioIO:
    def __init__(self):
        self.stream = None
        self.monitor_stream = None

    def query_devices(self):
        return sd.query_devices()

    def sleep(self, milliseconds):
        sd.sleep(milliseconds)

    def open_output_stream(self, output_id, callback):
        self.monitor_stream = sd.OutputStream(
            samplerate=SAMPLE_RATE,
            blocksize=BLOCK_SIZE,
            dtype="float32",
            channels=2,
            device=output_id,
            callback=callback,
            latency="low",
        )
        self.monitor_stream.start()

    def open_duplex_stream(self, input_id, output_id, callback):
        self.stream = sd.Stream(
            samplerate=SAMPLE_RATE,
            blocksize=BLOCK_SIZE,
            dtype="float32",
            channels=(1, 2),
            device=(input_id, output_id),
            callback=callback,
            latency="low",
        )
        self.stream.start()

    def close(self):
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        if self.monitor_stream:
            self.monitor_stream.stop()
            self.monitor_stream.close()
            self.monitor_stream = None

    def write_frame(self, outdata, frame):
        """Write one output block to a hardware buffer.

        Passing raw arrays is a deprecated compatibility path. Canonical router
        code must pass AudioFrame-backed buses.
        """
        samples = self._frame_samples(frame)
        frames = min(len(samples), len(outdata))
        outdata[:] = 0
        if samples.ndim == 1:
            outdata[:frames, 0] = samples[:frames]
            if outdata.shape[1] > 1:
                outdata[:frames, 1] = samples[:frames]
            return
        channels = min(samples.shape[1], outdata.shape[1])
        outdata[:frames, :channels] = samples[:frames, :channels]

    def _frame_samples(self, frame):
        if isinstance(frame, AudioFrame):
            return frame.samples
        return frame
