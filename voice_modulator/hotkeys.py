import os
from PySide6.QtCore import QObject, Signal
from pynput import keyboard

from .config import SOUNDS_DIR
from .soundboard import list_sound_files

class HotkeyManager(QObject):
    play_sound_signal = Signal(int)
    preset_signal = Signal(str)
    status_signal = Signal(str)

    def __init__(self):
        super().__init__()
        self.listener = None

    def register(self):
        self.unregister()

        def on_press(key):
            try:
                if hasattr(key, "char"):
                    if key.char == "1":
                        self.play_sound_signal.emit(0)
                    elif key.char == "2":
                        self.play_sound_signal.emit(1)
                    elif key.char == "3":
                        self.play_sound_signal.emit(2)
                    elif key.char == "5":
                        self.preset_signal.emit("Clean")
                    elif key.char == "6":
                        self.preset_signal.emit("Robot")
                    elif key.char == "7":
                        self.preset_signal.emit("Radio")
            except Exception as e:
                self.status_signal.emit(f"Hotkey error: {e}")

        try:
            self.listener = keyboard.Listener(on_press=on_press)
            self.listener.start()
            self.status_signal.emit("Hotkeys active: 1/2/3 sounds, 5/6/7 presets")
        except Exception as e:
            self.status_signal.emit(f"Hotkey setup failed: {e}")

    def unregister(self):
        if self.listener:
            try:
                self.listener.stop()
            except Exception:
                pass
            self.listener = None
