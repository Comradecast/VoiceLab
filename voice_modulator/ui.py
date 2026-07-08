import os
import sounddevice as sd

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QSlider, QInputDialog, QCheckBox
)

from .audio_engine import AudioEngine
from .config import DEFAULT_INPUT_ID, DEFAULT_OUTPUT_ID, DEFAULT_MONITOR_ID, SOUNDS_DIR
from .presets import load_presets, save_presets
from .soundboard import list_sound_files
from .hotkeys import HotkeyManager

class App(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Voice Modulator")
        self.engine = AudioEngine()
        self.devices = sd.query_devices()
        self.presets = load_presets()
        self.hotkeys = HotkeyManager()

        self.hotkeys.play_sound_signal.connect(self.play_sound_by_index)
        self.hotkeys.preset_signal.connect(self.set_preset_by_name)
        self.hotkeys.status_signal.connect(self.set_status)

        os.makedirs(SOUNDS_DIR, exist_ok=True)

        layout = QVBoxLayout(self)

        self.input_box = QComboBox()
        self.output_box = QComboBox()
        self.monitor_box = QComboBox()

        for i, d in enumerate(self.devices):
            if d["max_input_channels"] > 0:
                self.input_box.addItem(f'{i}: {d["name"]}', i)
            if d["max_output_channels"] > 0:
                self.output_box.addItem(f'{i}: {d["name"]}', i)
                self.monitor_box.addItem(f'{i}: {d["name"]}', i)

        layout.addWidget(QLabel("Input device"))
        layout.addWidget(self.input_box)
        layout.addWidget(QLabel("Output to virtual mic"))
        layout.addWidget(self.output_box)

        self.monitor_check = QCheckBox("Monitor myself through speakers/headphones")
        layout.addWidget(self.monitor_check)
        layout.addWidget(QLabel("Monitor device"))
        layout.addWidget(self.monitor_box)

        self.monitor_volume = self.slider(layout, "Monitor volume", 0, 100, 35)
        self.soundboard_volume = self.slider(layout, "Soundboard volume", 0, 100, 70)

        layout.addWidget(QLabel("Preset"))
        self.preset_box = QComboBox()
        self.refresh_preset_box()
        self.preset_box.currentTextChanged.connect(self.apply_selected_preset)
        layout.addWidget(self.preset_box)

        preset_btns = QHBoxLayout()
        save_preset = QPushButton("Save Current as Preset")
        delete_preset = QPushButton("Delete Preset")
        save_preset.clicked.connect(self.save_current_as_preset)
        delete_preset.clicked.connect(self.delete_current_preset)
        preset_btns.addWidget(save_preset)
        preset_btns.addWidget(delete_preset)
        layout.addLayout(preset_btns)

        self.gain = self.slider(layout, "Gain", 0, 50, 10)
        self.robot = self.slider(layout, "Robot amount", 0, 100, 0)
        self.lowpass = self.slider(layout, "Lowpass Hz", 300, 8000, 4000)

        layout.addWidget(QLabel("Soundboard — F1/F2/F3 for first 3 sounds"))
        self.soundboard_layout = QHBoxLayout()
        layout.addLayout(self.soundboard_layout)

        refresh_sounds = QPushButton("Refresh Sounds")
        refresh_sounds.clicked.connect(self.refresh_soundboard)
        layout.addWidget(refresh_sounds)

        btns = QHBoxLayout()
        start = QPushButton("Start")
        stop = QPushButton("Stop")
        start.clicked.connect(self.start)
        stop.clicked.connect(self.stop)
        btns.addWidget(start)
        btns.addWidget(stop)
        layout.addLayout(btns)

        self.status = QLabel("Stopped")
        layout.addWidget(self.status)

        self.preselect_devices()
        self.apply_selected_preset()
        self.refresh_soundboard()
        self.hotkeys.register()

    def play_sound_by_index(self, index):
        files = list_sound_files()
        if 0 <= index < len(files):
            self.play_sound(os.path.join(SOUNDS_DIR, files[index]))
        else:
            self.set_status(f"No sound at hotkey index {index}")

    def preselect_devices(self):
        self.set_combo(self.input_box, DEFAULT_INPUT_ID)
        self.set_combo(self.output_box, DEFAULT_OUTPUT_ID)
        self.set_combo(self.monitor_box, DEFAULT_MONITOR_ID)

    def slider(self, layout, name, low, high, value):
        label = QLabel(f"{name}: {value}")
        s = QSlider(Qt.Horizontal)
        s.setRange(low, high)
        s.setValue(value)
        s.valueChanged.connect(lambda v: (label.setText(f"{name}: {v}"), self.update_engine()))
        layout.addWidget(label)
        layout.addWidget(s)
        return s

    def refresh_preset_box(self):
        current = self.preset_box.currentText()
        self.preset_box.blockSignals(True)
        self.preset_box.clear()
        self.preset_box.addItems(sorted(self.presets.keys()))
        if current in self.presets:
            self.preset_box.setCurrentText(current)
        self.preset_box.blockSignals(False)

    def current_params(self):
        return {
            "gain": self.gain.value(),
            "robot": self.robot.value(),
            "lowpass": self.lowpass.value()
        }

    def apply_selected_preset(self):
        name = self.preset_box.currentText()
        if not name or name not in self.presets:
            return
        p = self.presets[name]
        self.gain.setValue(p.get("gain", 10))
        self.robot.setValue(p.get("robot", 0))
        self.lowpass.setValue(p.get("lowpass", 4000))
        self.update_engine()

    def set_preset_by_name(self, name):
        if name in self.presets:
            self.preset_box.setCurrentText(name)
            self.apply_selected_preset()
            self.set_status(f"Preset hotkey: {name}")
        else:
            self.set_status(f"Preset not found: {name}")

    def save_current_as_preset(self):
        name, ok = QInputDialog.getText(self, "Save Preset", "Preset name:")
        name = name.strip()
        if not ok or not name:
            return
        self.presets[name] = self.current_params()
        save_presets(self.presets)
        self.refresh_preset_box()
        self.preset_box.setCurrentText(name)
        self.set_status(f"Saved preset: {name}")

    def delete_current_preset(self):
        name = self.preset_box.currentText()
        if name in self.presets:
            del self.presets[name]
            save_presets(self.presets)
            self.refresh_preset_box()
            self.set_status(f"Deleted preset: {name}")

    def refresh_soundboard(self):
        while self.soundboard_layout.count():
            item = self.soundboard_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        files = list_sound_files()
        if not files:
            self.set_status("No sound files found in ./sounds")
            return

        for filename in files[:8]:
            path = os.path.join(SOUNDS_DIR, filename)
            label = os.path.splitext(filename)[0]
            btn = QPushButton(label)
            btn.clicked.connect(lambda checked=False, p=path: self.play_sound(p))
            self.soundboard_layout.addWidget(btn)

    def play_sound(self, path):
        try:
            self.update_engine()
            self.engine.play_sound(path)
            self.set_status(f"Played: {os.path.basename(path)}")
        except Exception as e:
            self.set_status(f"Sound error: {e}")

    def update_engine(self):
        self.engine.set_params(
            gain=self.gain.value() / 10.0,
            robot=self.robot.value() / 100.0,
            lowpass=self.lowpass.value(),
            monitor_enabled=self.monitor_check.isChecked(),
            monitor_volume=self.monitor_volume.value() / 100.0,
            soundboard_volume=self.soundboard_volume.value() / 100.0
        )

    def start(self):
        self.update_engine()
        monitor_id = self.monitor_box.currentData() if self.monitor_check.isChecked() else None
        self.engine.start(self.input_box.currentData(), self.output_box.currentData(), monitor_id)
        self.set_status(
            f"Running: mic {self.input_box.currentData()} → cable {self.output_box.currentData()}"
            + (f" + monitor {monitor_id}" if monitor_id is not None else "")
        )

    def stop(self):
        self.engine.stop()
        self.set_status("Stopped")

    def set_combo(self, box, value):
        for i in range(box.count()):
            if box.itemData(i) == value:
                box.setCurrentIndex(i)
                return

    def set_status(self, text):
        self.status.setText(text)

    def closeEvent(self, event):
        self.hotkeys.unregister()
        self.engine.stop()
        event.accept()
