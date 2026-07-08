import sounddevice as sd

def callback(indata, outdata, frames, time_info, status):
    outdata[:, 0] = indata[:, 0]
    outdata[:, 1] = indata[:, 0]

print("Pass-through running: 23 mic → 18 cable. Ctrl+C to stop.")
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
