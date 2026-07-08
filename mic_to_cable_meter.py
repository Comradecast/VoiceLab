import sounddevice as sd
import numpy as np

def callback(indata, outdata, frames, time_info, status):
    level = float(np.sqrt(np.mean(indata[:, 0] ** 2)))
    if level > 0.005:
        print("mic level:", round(level, 4))

    outdata[:, 0] = indata[:, 0]
    outdata[:, 1] = indata[:, 0]

print("Testing mic 23 → cable 18. Speak now. Ctrl+C to stop.")
with sd.Stream(
    samplerate=48000,
    blocksize=1024,
    dtype="float32",
    channels=(1, 2),
    device=(23, 18),
    callback=callback,
    latency="low",
):
    while True:
        sd.sleep(1000)
