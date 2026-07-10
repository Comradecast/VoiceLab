import os

import numpy as np
import soundfile as sf


SAMPLE_RATE = 48000


def tone(name, hz, seconds):
    t = np.arange(int(SAMPLE_RATE * seconds)) / SAMPLE_RATE
    y = 0.35 * np.sin(2 * np.pi * hz * t)
    sf.write(f"sounds/{name}.wav", y.astype("float32"), SAMPLE_RATE)


def main():
    os.makedirs("sounds", exist_ok=True)
    tone("beep", 880, 0.25)
    tone("boop", 220, 0.35)
    tone("alert", 440, 0.6)
    print("Created test soundboard clips in ./sounds")


if __name__ == "__main__":
    main()
