import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)


class App(QWidget):
    def __init__(self, service, on_close=None):
        super().__init__()
        self.setWindowTitle("VoiceLab")
        self.service = service
        self.on_close = on_close
        self.devices = self.service.devices()

        self.service.status_changed.connect(self.set_status)
        self.service.preset_selected.connect(self.set_preset_from_service)

        os.makedirs("sounds", exist_ok=True)

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
        self.pitch = self.slider(layout, "Pitch", -12, 12, 0)
        self.robot = self.slider(layout, "Robot amount", 0, 100, 0)
        self.lowpass = self.slider(layout, "Lowpass Hz", 300, 8000, 4000)

        layout.addWidget(QLabel("Soundboard — F1/F2/F3 for first 3 sounds"))
        self.soundboard_layout = QHBoxLayout()
        layout.addLayout(self.soundboard_layout)

        refresh_sounds = QPushButton("Refresh Sounds")
        refresh_sounds.clicked.connect(self.refresh_soundboard)
        layout.addWidget(refresh_sounds)

        btns = QHBoxLayout()
        self.start_button = QPushButton("Start Processing")
        self.stop_button = QPushButton("Stop Processing")
        self.start_button.clicked.connect(self.start)
        self.stop_button.clicked.connect(self.stop)
        btns.addWidget(self.start_button)
        btns.addWidget(self.stop_button)
        layout.addLayout(btns)

        self.status = QLabel("Stopped")
        layout.addWidget(self.status)
        self.processing_status = QLabel("Processing: Stopped")
        self.route_status = QLabel("Routes stopped")
        self.pitch_status = QLabel("Pitch: Off")
        self.latency_status = QLabel("Estimated pitch DSP latency: Not active")
        self.command_status = QLabel("")
        self.warning_status = QLabel("Warnings: None")
        self.diagnostic_status = QLabel("")
        for label in (
            self.processing_status,
            self.route_status,
            self.pitch_status,
            self.latency_status,
            self.command_status,
            self.warning_status,
            self.diagnostic_status,
        ):
            label.setWordWrap(True)
            layout.addWidget(label)

        self.preselect_devices()
        self.apply_selected_preset()
        self.refresh_soundboard()
        self.status_timer = QTimer(self)
        self.status_timer.setInterval(500)
        self.status_timer.timeout.connect(self.refresh_operator_status)
        self.status_timer.start()
        self.refresh_operator_status()

    def play_sound_by_index(self, index):
        result = self.service.play_sound_by_index(index)
        self.display_result(result)

    def preselect_devices(self):
        self.set_combo(self.input_box, self.service.default_input_id())
        self.set_combo(self.output_box, self.service.default_output_id())
        self.set_combo(self.monitor_box, self.service.default_monitor_id())

    def slider(self, layout, name, low, high, value):
        label = QLabel(f"{name}: {value}")
        s = QSlider(Qt.Horizontal)
        s.setRange(low, high)
        s.setValue(value)
        s.valueChanged.connect(lambda v: (label.setText(f"{name}: {v}"), self.apply_current_parameters()))
        layout.addWidget(label)
        layout.addWidget(s)
        return s

    def refresh_preset_box(self):
        current = self.preset_box.currentText()
        self.preset_box.blockSignals(True)
        self.preset_box.clear()
        names = self.service.preset_names()
        self.preset_box.addItems(names)
        if current in names:
            self.preset_box.setCurrentText(current)
        self.preset_box.blockSignals(False)

    def current_params(self):
        return {
            "gain": self.gain.value(),
            "pitch": self.pitch.value(),
            "robot": self.robot.value(),
            "lowpass": self.lowpass.value(),
        }

    def apply_selected_preset(self):
        name = self.preset_box.currentText()
        if not name:
            return
        result = self.service.select_preset(name)
        if not result.success:
            self.display_result(result)
            return
        self.set_preset_controls(result.metadata["params"])

    def set_preset_by_name(self, name):
        result = self.service.select_preset(name)
        if result.success:
            self.preset_box.setCurrentText(name)
            self.set_preset_controls(result.metadata["params"])
            self.set_status(f"Preset hotkey: {name}")
        else:
            self.display_result(result)

    def set_preset_from_service(self, name, params):
        self.preset_box.setCurrentText(name)
        self.set_preset_controls(params)

    def set_preset_controls(self, params):
        self.gain.setValue(params.get("gain", 10))
        self.pitch.setValue(params.get("pitch", 0))
        self.robot.setValue(params.get("robot", 0))
        self.lowpass.setValue(params.get("lowpass", 4000))
        self.apply_current_parameters()

    def save_current_as_preset(self):
        name, ok = QInputDialog.getText(self, "Save Preset", "Preset name:")
        name = name.strip()
        if not ok or not name:
            return
        result = self.service.save_preset(name, self.current_params())
        if not result.success:
            self.display_result(result)
            return
        self.refresh_preset_box()
        self.preset_box.setCurrentText(name)
        self.display_result(result)

    def delete_current_preset(self):
        name = self.preset_box.currentText()
        result = self.service.delete_preset(name)
        self.refresh_preset_box()
        self.display_result(result)

    def refresh_soundboard(self):
        while self.soundboard_layout.count():
            item = self.soundboard_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        files = self.service.sound_files()
        if not files:
            self.set_status("No sound files found in ./sounds")
            return

        for filename in files[:8]:
            label = os.path.splitext(filename)[0]
            btn = QPushButton(label)
            btn.clicked.connect(lambda checked=False, f=filename: self.play_sound(f))
            self.soundboard_layout.addWidget(btn)

    def play_sound(self, filename):
        self.apply_current_parameters()
        result = self.service.play_sound_file(filename)
        self.display_result(result)

    def apply_current_parameters(self):
        return self.service.apply_effect_parameters(
            gain=self.gain.value() / 10.0,
            robot=self.robot.value() / 100.0,
            lowpass=self.lowpass.value(),
            pitch=self.pitch.value(),
            monitor_enabled=self.monitor_check.isChecked(),
            monitor_volume=self.monitor_volume.value() / 100.0,
            soundboard_volume=self.soundboard_volume.value() / 100.0,
        )

    def start(self):
        self.apply_current_parameters()
        monitor_id = self.monitor_box.currentData() if self.monitor_check.isChecked() else None
        result = self.service.start_audio(
            self.input_box.currentData(),
            self.output_box.currentData(),
            monitor_id,
        )
        self.display_result(result)

    def stop(self):
        result = self.service.stop_audio()
        self.display_result(result)

    def set_combo(self, box, value):
        for i in range(box.count()):
            if box.itemData(i) == value:
                box.setCurrentIndex(i)
                return

    def set_status(self, text):
        self.status.setText(text)

    def display_result(self, result):
        if result.message:
            self.set_status(result.message)
        self.refresh_operator_status()

    def refresh_operator_status(self):
        try:
            status = self.service.operator_status()
        except Exception as exc:
            self.processing_status.setText("Processing: Status unavailable")
            self.warning_status.setText(f"Warnings: Status refresh failed: {exc}")
            return
        self.processing_status.setText(f"Processing: {status.processing}")
        self.route_status.setText(status.route)
        self.pitch_status.setText(status.pitch)
        self.latency_status.setText(status.latency)
        self.command_status.setText(
            f"Status: {status.command_status}" if status.command_status else "Status: Ready"
        )
        self.warning_status.setText(
            f"Warnings: {status.actionable_status}"
            if status.actionable_status
            else "Warnings: None"
        )
        self.start_button.setEnabled(status.start_enabled)
        self.stop_button.setEnabled(status.stop_enabled)
        details = []
        for key in (
            "pitch_backend",
            "pitch_backend_status",
            "pitch_fallback_active",
            "pitch_configured_block_size",
            "pitch_configured_interval_size",
            "pitch_latency_frames",
        ):
            details.append(f"{key}: {status.diagnostics.get(key)}")
        self.diagnostic_status.setText("Diagnostics: " + "; ".join(details))

    def closeEvent(self, event):
        if hasattr(self, "status_timer"):
            self.status_timer.stop()
        if self.on_close is not None:
            self.on_close()
        event.accept()
