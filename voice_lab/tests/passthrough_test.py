from voice_lab.io import AudioIO


def callback(indata, outdata, frames, time_info, status):
    outdata[:, 0] = indata[:, 0]
    outdata[:, 1] = indata[:, 0]


def main():
    audio_io = AudioIO()
    print("Pass-through running: 23 mic → 18 cable. Ctrl+C to stop.")
    audio_io.open_duplex_stream(23, 18, callback)
    try:
        while True:
            audio_io.sleep(1000)
    finally:
        audio_io.close()


if __name__ == "__main__":
    main()
