import os
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from .config import SAMPLE_RATE, SOUNDS_DIR

def list_sound_files():
    os.makedirs(SOUNDS_DIR, exist_ok=True)
    return [
        f for f in sorted(os.listdir(SOUNDS_DIR))
        if f.lower().endswith((".wav", ".flac", ".ogg"))
    ]

def load_sound(path):
    data, sr = sf.read(path, dtype="float32", always_2d=False)

    if data.ndim > 1:
        data = data.mean(axis=1)

    if sr != SAMPLE_RATE:
        gcd = np.gcd(sr, SAMPLE_RATE)
        data = resample_poly(data, SAMPLE_RATE // gcd, sr // gcd).astype(np.float32)

    return data.astype(np.float32)
