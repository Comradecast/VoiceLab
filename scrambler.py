import argparse, math, time
import numpy as np
import sounddevice as sd
from scipy.signal import butter, lfilter

SAMPLE_RATE = 48000
BLOCK_SIZE = 1024

def soft_clip(x):
    return np.tanh(2.2 * x) / np.tanh(2.2)

b, a = butter(4, [180 / (SAMPLE_RATE / 2), 3400 / (SAMPLE_RATE / 2)], btype="band")

phase = 0
started = time.time()

def callback(indata, outdata, frames, time_info, status):
    global phase
    mono = indata[:, 0].copy()

    rms = np.sqrt(np.mean(mono * mono) + 1e-9)
    if rms < 0.008:
        mono *= 0.05

    t = (np.arange(len(mono)) + phase) / SAMPLE_RATE
    wobble = 1.0 + 0.08 * math.sin((time.time() - started) * 2.1)
    carrier = np.sin(2 * np.pi * 90 * wobble * t)
    mono = mono * carrier
    phase += len(mono)

    mono = lfilter(b, a, mono)
    mono *= 3.5
    mono = soft_clip(mono)
    mono += np.random.normal(0, 0.002, size=mono.shape)
    mono = np.clip(mono, -0.95, 0.95).astype(np.float32)

    outdata[:, 0] = mono
    if outdata.shape[1] > 1:
        outdata[:, 1] = mono

print("Running voice scrambler. Ctrl+C to stop.")
with sd.Stream(
    samplerate=SAMPLE_RATE,
    blocksize=BLOCK_SIZE,
    dtype="float32",
    channels=(1, 2),
    device=(23, 18),
    callback=callback,
    latency="low",
):
    while True:
        sd.sleep(1000)
