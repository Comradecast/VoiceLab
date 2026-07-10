import numpy as np

from voice_lab.io import AudioIO


SAMPLE_RATE = 48000
BLOCK = 1024
phase = 0


def callback(outdata, frames, time_info, status):
    global phase
    t = (np.arange(frames) + phase) / SAMPLE_RATE
    tone = (0.15 * np.sin(2 * np.pi * 440 * t)).astype("float32")
    phase += frames
    outdata[:, 0] = tone
    outdata[:, 1] = tone


def main():
    audio_io = AudioIO()
    print("Sending 440Hz tone to CABLE Input WASAPI device 18. Ctrl+C to stop.")
    audio_io.open_output_stream(18, callback)
    try:
        while True:
            audio_io.sleep(1000)
    finally:
        audio_io.close()


if __name__ == "__main__":
    main()
