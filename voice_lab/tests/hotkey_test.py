from pynput import keyboard


def on_press(key):
    print("pressed:", key)


def main():
    print("Press F1/F2/F3/F5/F6/F7. Press ESC to exit.")
    with keyboard.Listener(on_press=on_press) as listener:
        listener.join()


if __name__ == "__main__":
    main()
