import json, os, queue
import numpy as np
import sounddevice as sd
import soundfile as sf
import keyboard
from scipy.signal import butter, lfilter, resample_poly
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QSlider, QInputDialog, QCheckBox
)

SAMPLE_RATE = 48000
BLOCK_SIZE = 1024
PRESET_PATH = "presets.json"
SOUNDS_DIR = "sounds"

DEFAULT_PRESETS = {
    "Clean": {"gain": 10, "robot": 0, "lowpass": 4000},
    "Muffled": {"gain": 12, "robot": 0, "lowpass": 900},
    "Robot": {"gain": 12, "robot": 100, "lowpass": 4000},
    "Deep-ish": {"gain": 18, "robot": 25, "lowpass": 1800},
    "Radio": {"gain": 16, "robot": 15, "lowpass": 2300}
}

class Engine:
    def __init__(self):
        self.stream = None
        self.monitor_stream = None
        self.monitor_queue = queue.Queue(maxsize=8)
        self.sound_queue = []
        self.gain = 1.0
        self.robot = 0.0
        self.lowpass = 4000
        self.monitor_enabled = False
        self.monitor_volume = 0.4
        self.soundboard_volume = 0.7
        self.phase = 0

    def process_voice(self, mono, frames):
        t = (np.arange(frames) + self.phase) / SAMPLE_RATE
        carrier = np.sin(2 * np.pi * 85 * t)
        self.phase += frames

        mono = mono * (1.0 - self.robot) + (mono * carrier) * self.robot

        cutoff = max(300, min(self.lowpass, 8000))
        b, a = butter(2, cutoff / (SAMPLE_RATE / 2), btype="low")
        mono = lfilter(b, a, mono)

        mono *= self.gain
        return np.clip(mono, -0.95, 0.95).astype(np.float32)

    def load_sound(self, path):
        data, sr = sf.read(path, dtype="float32", always_2d=False)

        if data.ndim > 1:
            data = data.mean(axis=1)

        if sr != SAMPLE_RATE:
            # Simple resample path.
            gcd = np.gcd(sr, SAMPLE_RATE)
            data = resample_poly(data, SAMPLE_RATE // gcd, sr // gcd).astype(np.float32)

        return data.astype(np.float32)

    def play_sound(self, path):
        try:
            data = self.load_sound(path)
            self.sound_queue.append({"data": data, "pos": 0})
        except Exception as e:
            print("Soundboard error:", e)

    def mix_sounds(self, frames):
        if not self.sound_queue:
            return np.zeros(frames, dtype=np.float32)

        mix = np.zeros(frames, dtype=np.float32)
        still_playing = []

        for item in self.sound_queue:
            data = item["data"]
            pos = item["pos"]
            chunk = data[pos:pos + frames]

            if len(chunk) < frames:
                padded = np.zeros(frames, dtype=np.float32)
                padded[:len(chunk)] = chunk
                chunk = padded
            else:
                item["pos"] += frames
                still_playing.append(item)

            mix += chunk * self.soundboard_volume

        self.sound_queue = still_playing
        return np.clip(mix, -0.95, 0.95).astype(np.float32)

    def start(self, input_id, output_id, monitor_id=None):
        self.stop()
        self.monitor_queue = queue.Queue(maxsize=8)

        def main_callback(indata, outdata, frames, time_info, status):
            voice = self.process_voice(indata[:, 0].copy(), frames)
            sounds = self.mix_sounds(frames)

            mixed = np.clip(voice + sounds, -0.95, 0.95).astype(np.float32)

            outdata[:, 0] = mixed
            outdata[:, 1] = mixed

            if self.monitor_enabled and self.monitor_stream:
                stereo = np.column_stack([mixed, mixed]).astype(np.float32)
                stereo *= self.monitor_volume
                try:
                    self.monitor_queue.put_nowait(stereo)
                except queue.Full:
                    pass

        def monitor_callback(outdata, frames, time_info, status):
            try:
                data = self.monitor_queue.get_nowait()
                if len(data) < frames:
                    pad = np.zeros((frames - len(data), 2), dtype=np.float32)
                    data = np.vstack([data, pad])
                outdata[:] = data[:frames]
            except queue.Empty:
                outdata[:] = np.zeros((frames, 2), dtype=np.float32)

        if monitor_id is not None:
            self.monitor_stream = sd.OutputStream(
                samplerate=SAMPLE_RATE,
                blocksize=BLOCK_SIZE,
                dtype="float32",
                channels=2,
                device=monitor_id,
                callback=monitor_callback,
                latency="low",
            )
            self.monitor_stream.start()

        self.stream = sd.Stream(
            samplerate=SAMPLE_RATE,
            blocksize=BLOCK_SIZE,
            dtype="float32",
            channels=(1, 2),
            device=(input_id, output_id),
            callback=main_callback,
            latency="low",
        )
        self.stream.start()

    def stop(self):
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        if self.monitor_stream:
            self.monitor_stream.stop()
            self.monitor_stream.close()
            self.monitor_stream = None

class App(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Voice Modulator - Presets + Monitor + Soundboard")
        self.engine = Engine()
        self.devices = sd.query_devices()
        self.presets = self.load_presets()

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

        layout.addWidget(QLabel("Soundboard — Hotkeys: F1/F2/F3 for first 3 sounds"))
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
        self.register_hotkeys()

    def preselect_devices(self):
        self.set_combo(self.input_box, 23)
        self.set_combo(self.output_box, 18)
        self.set_combo(self.monitor_box, 19)

    def load_presets(self):
        if os.path.exists(PRESET_PATH):
            try:
                with open(PRESET_PATH, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return DEFAULT_PRESETS.copy()

    def write_presets(self):
        with open(PRESET_PATH, "w") as f:
            json.dump(self.presets, f, indent=2)

    def refresh_preset_box(self):
        current = self.preset_box.currentText()
        self.preset_box.blockSignals(True)
        self.preset_box.clear()
        self.preset_box.addItems(sorted(self.presets.keys()))
        if current in self.presets:
            self.preset_box.setCurrentText(current)
        self.preset_box.blockSignals(False)

    def slider(self, layout, name, low, high, value):
        label = QLabel(f"{name}: {value}")
        s = QSlider(Qt.Horizontal)
        s.setRange(low, high)
        s.setValue(value)
        s.valueChanged.connect(lambda v: (label.setText(f"{name}: {v}"), self.update_engine()))
        layout.addWidget(label)
        layout.addWidget(s)
        return s

    def current_params(self):
        return {"gain": self.gain.value(), "robot": self.robot.value(), "lowpass": self.lowpass.value()}

    def apply_selected_preset(self):
        name = self.preset_box.currentText()
        if not name or name not in self.presets:
            return
        p = self.presets[name]
        self.gain.setValue(p.get("gain", 10))
        self.robot.setValue(p.get("robot", 0))
        self.lowpass.setValue(p.get("lowpass", 4000))
        self.update_engine()

    def save_current_as_preset(self):
        name, ok = QInputDialog.getText(self, "Save Preset", "Preset name:")
        name = name.strip()
        if not ok or not name:
            return
        self.presets[name] = self.current_params()
        self.write_presets()
        self.refresh_preset_box()
        self.preset_box.setCurrentText(name)
        self.status.setText(f"Saved preset: {name}")

    def delete_current_preset(self):
        name = self.preset_box.currentText()
        if name in self.presets:
            del self.presets[name]
            self.write_presets()
            self.refresh_preset_box()
            self.status.setText(f"Deleted preset: {name}")

    def refresh_soundboard(self):
        while self.soundboard_layout.count():
            item = self.soundboard_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        files = [
            f for f in sorted(os.listdir(SOUNDS_DIR))
            if f.lower().endswith((".wav", ".flac", ".ogg"))
        ]

        if not files:
            self.status.setText("No sound files found in ./sounds")
            return

        for filename in files[:8]:
            path = os.path.join(SOUNDS_DIR, filename)
            label = os.path.splitext(filename)[0]
            btn = QPushButton(label)
            btn.clicked.connect(lambda checked=False, p=path: self.play_sound(p))
            self.soundboard_layout.addWidget(btn)

    def play_sound(self, path):
        self.update_engine()
        self.engine.play_sound(path)
        self.status.setText(f"Played: {os.path.basename(path)}")

    def update_engine(self):
        self.engine.gain = self.gain.value() / 10.0
        self.engine.robot = self.robot.value() / 100.0
        self.engine.lowpass = self.lowpass.value()
        self.engine.monitor_enabled = self.monitor_check.isChecked()
        self.engine.monitor_volume = self.monitor_volume.value() / 100.0
        self.engine.soundboard_volume = self.soundboard_volume.value() / 100.0

    def start(self):
        self.update_engine()
        monitor_id = self.monitor_box.currentData() if self.monitor_check.isChecked() else None
        self.engine.start(self.input_box.currentData(), self.output_box.currentData(), monitor_id)
        self.status.setText(
            f"Running: mic {self.input_box.currentData()} → cable {self.output_box.currentData()}"
            + (f" + monitor {monitor_id}" if monitor_id is not None else "")
        )

    def stop(self):
        self.engine.stop()
        self.status.setText("Stopped")

    def set_combo(self, box, value):
        for i in range(box.count()):
            if box.itemData(i) == value:
                box.setCurrentIndex(i)
                return

        def register_hotkeys(self):
        try:
            keyboard.clear_all_hotkeys()

            keyboard.add_hotkey("f1", lambda: self.play_sound_by_index(0))
            keyboard.add_hotkey("f2", lambda: self.play_sound_by_index(1))
            keyboard.add_hotkey("f3", lambda: self.play_sound_by_index(2))

            keyboard.add_hotkey("f5", lambda: self.set_preset_by_name("Clean"))
            keyboard.add_hotkey("f6", lambda: self.set_preset_by_name("Robot"))
            keyboard.add_hotkey("f7", lambda: self.set_preset_by_name("Radio"))

            self.status.setText("Hotkeys active: F1/F2/F3 sounds, F5/F6/F7 presets")
        except Exception as e:
            self.status.setText(f"Hotkey setup failed: {e}")

    def sound_files(self):
        return [
            f for f in sorted(os.listdir(SOUNDS_DIR))
            if f.lower().endswith((".wav", ".flac", ".ogg"))
        ]

    def play_sound_by_index(self, index):
        files = self.sound_files()
        if 0 <= index < len(files):
            self.play_sound(os.path.join(SOUNDS_DIR, files[index]))

    def set_preset_by_name(self, name):
        if name in self.presets:
            self.preset_box.setCurrentText(name)
            self.apply_selected_preset()
            self.status.setText(f"Preset hotkey: {name}")

    def closeEvent(self, event):
        try:
            keyboard.clear_all_hotkeys()
        except Exception:
            pass
        self.engine.stop()
        event.accept()

app = QApplication([])
w = App()
w.resize(700, 700)
w.show()
app.exec()

