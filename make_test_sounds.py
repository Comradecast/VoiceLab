import numpy as np
import soundfile as sf
import os

os.makedirs("sounds", exist_ok=True)
sr = 48000

def tone(name, hz, seconds):
    t = np.arange(int(sr * seconds)) / sr
    y = 0.35 * np.sin(2 * np.pi * hz * t)
    sf.write(f"sounds/{name}.wav", y.astype("float32"), sr)

tone("beep", 880, 0.25)
tone("boop", 220, 0.35)
tone("alert", 440, 0.6)
print("Created test soundboard clips in ./sounds")
