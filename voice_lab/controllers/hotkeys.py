from PySide6.QtCore import QObject, Signal
from pynput import keyboard


class HotkeyManager(QObject):
    status_signal = Signal(str)

    def __init__(self, commands=None):
        super().__init__()
        self.commands = commands
        self.listener = None

    def set_commands(self, commands):
        self.commands = commands

    def register(self):
        self.unregister()

        def on_press(key):
            try:
                if hasattr(key, "char"):
                    if key.char == "1":
                        self._play_sound(0)
                    elif key.char == "2":
                        self._play_sound(1)
                    elif key.char == "3":
                        self._play_sound(2)
                    elif key.char == "5":
                        self._select_preset("Clean")
                    elif key.char == "6":
                        self._select_preset("Robot")
                    elif key.char == "7":
                        self._select_preset("Radio")
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

    def trigger_sound(self, index):
        return self._play_sound(index)

    def trigger_preset(self, name):
        return self._select_preset(name)

    def _play_sound(self, index):
        if self.commands is None:
            return None
        result = self.commands.play_sound_by_index(index)
        if result.message:
            self.status_signal.emit(result.message)
        return result

    def _select_preset(self, name):
        if self.commands is None:
            return None
        return self.commands.select_preset_from_hotkey(name)
