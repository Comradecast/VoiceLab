import numpy as np
import sounddevice as sd

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

print("Sending 440Hz tone to CABLE Input WASAPI device 18. Ctrl+C to stop.")
with sd.OutputStream(
    samplerate=SAMPLE_RATE,
    blocksize=BLOCK,
    dtype="float32",
    channels=2,
    device=18,
    callback=callback,
    latency="low",
):
    while True:
        sd.sleep(1000)
