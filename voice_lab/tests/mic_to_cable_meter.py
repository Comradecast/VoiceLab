import numpy as np

from voice_lab.io import AudioIO


def callback(indata, outdata, frames, time_info, status):
    level = float(np.sqrt(np.mean(indata[:, 0] ** 2)))
    if level > 0.005:
        print("mic level:", round(level, 4))

    outdata[:, 0] = indata[:, 0]
    outdata[:, 1] = indata[:, 0]


def main():
    audio_io = AudioIO()
    print("Testing mic 23 → cable 18. Speak now. Ctrl+C to stop.")
    audio_io.open_duplex_stream(23, 18, callback)
    try:
        while True:
            audio_io.sleep(1000)
    finally:
        audio_io.close()


if __name__ == "__main__":
    main()
