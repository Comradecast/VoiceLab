import os
from time import monotonic

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from voice_lab.ui.level_display import LevelDisplayModel


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

        root_layout = QVBoxLayout(self)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        layout = QVBoxLayout(content)
        scroll_area.setWidget(content)
        root_layout.addWidget(scroll_area)
        self.restored_preferences = self.service.operator_preferences() if hasattr(self.service, "operator_preferences") else {}
        self._updating_voice_controls = False
        self._updating_input_processing = False
        self._last_voice_selection = None

        layout.addWidget(QLabel("Voice Character"))
        self.character_box = QComboBox()
        self._populate_character_box()
        self.character_box.currentIndexChanged.connect(lambda _index: self.select_voice_character())
        layout.addWidget(self.character_box)
        self.character_description = QLabel("")
        self.character_description.setWordWrap(True)
        layout.addWidget(self.character_description)
        self.character_strength_label = QLabel("Character Strength: 100%")
        self.character_strength = QSlider(Qt.Horizontal)
        self.character_strength.setRange(0, 100)
        self.character_strength.setValue(100)
        self.character_strength.valueChanged.connect(self.set_character_strength)
        layout.addWidget(self.character_strength_label)
        layout.addWidget(self.character_strength)
        self.active_voice_status = QLabel("Active voice: Natural")
        self.active_voice_status.setWordWrap(True)
        layout.addWidget(self.active_voice_status)

        live_audio_label = QLabel("Live Audio")
        layout.addWidget(live_audio_label)
        self.level_display_models = {
            "input": LevelDisplayModel(),
            "processed": LevelDisplayModel(),
            "output": LevelDisplayModel(),
        }
        self.level_widgets = {}
        for key, title in (
            ("input", "Microphone Input"),
            ("processed", "Processed Voice"),
            ("output", "Output"),
        ):
            self.level_widgets[key] = self._create_level_meter(layout, title)
        self.level_summary = QLabel("Input signal: Stopped | Overload: None")
        self.level_summary.setWordWrap(True)
        layout.addWidget(self.level_summary)

        voice_btns = QHBoxLayout()
        self.bypass_check = QCheckBox("Bypass Effects")
        self.bypass_check.stateChanged.connect(lambda _state: self.set_effects_bypassed())
        self.reset_voice_button = QPushButton("Reset Voice")
        self.reset_voice_button.clicked.connect(self.reset_voice)
        voice_btns.addWidget(self.bypass_check)
        voice_btns.addWidget(self.reset_voice_button)
        layout.addLayout(voice_btns)

        self.input_box = QComboBox()
        self.output_box = QComboBox()
        self.monitor_box = QComboBox()

        self.populate_device_boxes(
            self.devices,
            self.restored_preferences.get(
                "selections",
                {
                    "input": self.service.default_input_id(),
                    "virtual_output": self.service.default_output_id(),
                    "monitor_output": self.service.default_monitor_id(),
                },
            ),
        )
        self.input_box.currentIndexChanged.connect(
            lambda _index: self.record_device_selection("input", self.input_box.currentData())
        )
        self.output_box.currentIndexChanged.connect(
            lambda _index: self.record_device_selection("virtual_output", self.output_box.currentData())
        )
        self.monitor_box.currentIndexChanged.connect(
            lambda _index: self.record_device_selection("monitor_output", self.monitor_box.currentData())
        )

        layout.addWidget(QLabel("Input device"))
        layout.addWidget(self.input_box)
        layout.addWidget(QLabel("Output to virtual mic"))
        layout.addWidget(self.output_box)

        self.monitor_check = QCheckBox("Enable monitor output")
        self.monitor_check.setChecked(bool(self.restored_preferences.get("monitor_enabled", False)))
        self.monitor_check.stateChanged.connect(lambda _state: self.apply_current_parameters())
        layout.addWidget(self.monitor_check)
        layout.addWidget(QLabel("Monitor output device"))
        layout.addWidget(self.monitor_box)
        self.refresh_devices_button = QPushButton("Refresh Devices")
        self.refresh_devices_button.clicked.connect(self.refresh_devices)
        layout.addWidget(self.refresh_devices_button)

        self.monitor_volume = self.slider(
            layout,
            "Monitor volume",
            0,
            100,
            int(round(float(self.restored_preferences.get("monitor_volume", 0.35)) * 100)),
        )
        self.soundboard_volume = self.slider(
            layout,
            "Soundboard volume",
            0,
            100,
            int(round(float(self.restored_preferences.get("soundboard_volume", 0.70)) * 100)),
        )

        self.input_processing_toggle = QCheckBox("Input Processing")
        self.input_processing_toggle.stateChanged.connect(lambda _state: self.set_input_processing_visible())
        layout.addWidget(self.input_processing_toggle)
        self.input_processing_widgets = []
        self._build_input_processing_controls(layout)

        self.advanced_toggle = QCheckBox("Show Advanced Controls")
        self.advanced_toggle.stateChanged.connect(lambda _state: self.set_advanced_visible())
        layout.addWidget(self.advanced_toggle)
        self.advanced_widgets = []

        saved_voice_label = QLabel("Saved Custom Voice")
        self.advanced_widgets.append(saved_voice_label)
        layout.addWidget(saved_voice_label)
        self.preset_box = QComboBox()
        self.refresh_preset_box()
        restored_preset = self.restored_preferences.get("selected_preset")
        if restored_preset:
            self.preset_box.setCurrentText(restored_preset)
        self.preset_box.currentTextChanged.connect(lambda _name: self._apply_selected_preset(persist=True))
        self.advanced_widgets.append(self.preset_box)
        layout.addWidget(self.preset_box)

        preset_btns = QHBoxLayout()
        self.save_preset_button = QPushButton("Save Current as Custom Voice")
        self.rename_preset_button = QPushButton("Rename Custom Voice")
        self.duplicate_preset_button = QPushButton("Duplicate Custom Voice")
        self.delete_preset_button = QPushButton("Delete Custom Voice")
        self.save_preset_button.clicked.connect(self.save_current_as_preset)
        self.rename_preset_button.clicked.connect(self.rename_current_preset)
        self.duplicate_preset_button.clicked.connect(self.duplicate_current_preset)
        self.delete_preset_button.clicked.connect(self.delete_current_preset)
        preset_btns.addWidget(self.save_preset_button)
        preset_btns.addWidget(self.rename_preset_button)
        preset_btns.addWidget(self.duplicate_preset_button)
        preset_btns.addWidget(self.delete_preset_button)
        self.advanced_widgets.extend(
            (
                self.save_preset_button,
                self.rename_preset_button,
                self.duplicate_preset_button,
                self.delete_preset_button,
            )
        )
        layout.addLayout(preset_btns)

        self.gain = self.slider(layout, "Gain", 0, 50, 10)
        self.pitch = self.slider(layout, "Pitch", -12, 12, 0)
        self.robot = self.slider(layout, "Robot amount", 0, 100, 0)
        self.lowpass = self.slider(layout, "Lowpass Hz", 300, 8000, 4000)
        self.advanced_widgets.extend(
            (
                self.gain._voice_lab_label,
                self.gain,
                self.pitch._voice_lab_label,
                self.pitch,
                self.robot._voice_lab_label,
                self.robot,
                self.lowpass._voice_lab_label,
                self.lowpass,
            )
        )

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

        self.advanced_widgets.append(self.diagnostic_status)
        self.sync_voice_controls_from_service()
        self.sync_input_processing_from_service()
        self.set_input_processing_visible()
        self.set_advanced_visible()
        self.refresh_custom_voice_actions()
        self.refresh_soundboard()
        self.status_timer = QTimer(self)
        self.status_timer.setInterval(500)
        self.status_timer.timeout.connect(self.refresh_operator_status)
        self.status_timer.start()
        self.meter_timer = QTimer(self)
        self.meter_timer.setInterval(50)
        self.meter_timer.timeout.connect(self.refresh_audio_levels)
        self.meter_timer.start()
        self.refresh_operator_status()
        self.refresh_audio_levels()

    def play_sound_by_index(self, index):
        result = self.service.play_sound_by_index(index)
        self.display_result(result)

    def _create_level_meter(self, layout, title):
        title_label = QLabel(title)
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(0)
        bar.setTextVisible(False)
        value_label = QLabel("< -60 dB | Stopped")
        value_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(bar)
        layout.addWidget(value_label)
        return {"title": title_label, "bar": bar, "value": value_label}

    def _populate_character_box(self):
        self.character_box.blockSignals(True)
        self.character_box.clear()
        self._characters_by_id = {}
        if hasattr(self.service, "voice_selector_entries"):
            for entry in self.service.voice_selector_entries():
                if entry["kind"] == "section":
                    self.character_box.addItem(entry["label"], ("section", None))
                    item = self.character_box.model().item(self.character_box.count() - 1)
                    if item is not None:
                        item.setEnabled(False)
                    continue
                self.character_box.addItem(entry["label"], (entry["kind"], entry["value"]))
                if entry["kind"] == "built_in":
                    self._characters_by_id[entry["value"]] = entry
            self._select_first_selectable_voice()
        elif hasattr(self.service, "voice_characters"):
            for character in self.service.voice_characters():
                self._characters_by_id[character["id"]] = character
                self.character_box.addItem(character["display_name"], ("built_in", character["id"]))
        else:
            self.character_box.addItem("Natural", ("built_in", "natural"))
            self._characters_by_id["natural"] = {
                "id": "natural",
                "display_name": "Natural",
                "description": "",
                "strength_enabled": False,
            }
        self.character_box.blockSignals(False)
        self._last_voice_selection = self.character_box.currentData()

    def select_voice_character(self):
        if self._updating_voice_controls or not hasattr(self.service, "select_voice_character"):
            return
        data = self.character_box.currentData()
        if not data or data[0] == "section":
            self.sync_voice_controls_from_service()
            return
        if not self.confirm_discard_unsaved_changes("Select another voice?"):
            self.sync_voice_controls_from_service()
            return
        kind, value = data
        if hasattr(self.service, "select_voice"):
            result = self.service.select_voice(kind, value, strength=self.character_strength.value())
        elif kind == "built_in":
            result = self.service.select_voice_character(value, strength=self.character_strength.value())
        else:
            result = self.service.select_preset(value)
        self.display_result(result)
        if result.success:
            self.set_preset_controls(result.metadata["params"], persist_settings=False, mark_custom=False)
            self.sync_voice_controls_from_service()

    def set_character_strength(self, value):
        self.character_strength_label.setText(f"Character Strength: {value}%")
        if self._updating_voice_controls or not hasattr(self.service, "set_character_strength"):
            return
        result = self.service.set_character_strength(value)
        self.display_result(result)
        if result.success:
            self.set_preset_controls(result.metadata["params"], persist_settings=False, mark_custom=False)
            self.sync_voice_controls_from_service()

    def set_effects_bypassed(self):
        if self._updating_voice_controls or not hasattr(self.service, "set_effects_bypassed"):
            return
        result = self.service.set_effects_bypassed(self.bypass_check.isChecked())
        self.display_result(result)
        self.sync_voice_controls_from_service()

    def reset_voice(self):
        if not hasattr(self.service, "reset_voice"):
            return
        if not self.confirm_discard_unsaved_changes("Reset Voice?"):
            return
        result = self.service.reset_voice()
        self.display_result(result)
        if result.success:
            self.set_preset_controls(result.metadata["params"], persist_settings=False, mark_custom=False)
        self.sync_voice_controls_from_service()

    def sync_voice_controls_from_service(self):
        if not hasattr(self.service, "active_voice_state"):
            return
        state = self.service.active_voice_state()
        self._updating_voice_controls = True
        try:
            if state.get("kind") == "custom" and state.get("custom_preset"):
                self.set_combo(self.character_box, ("custom", state.get("custom_preset")))
            elif state.get("kind") != "unsaved":
                self.set_combo(self.character_box, ("built_in", state.get("character_id")))
            self._last_voice_selection = self.character_box.currentData()
            character = self._characters_by_id.get(state.get("character_id"), {})
            self.character_description.setText(character.get("description", ""))
            strength = int(round(float(state.get("strength", 100))))
            self.character_strength.setValue(strength)
            self.character_strength_label.setText(f"Character Strength: {strength}%")
            strength_enabled = bool(character.get("strength_enabled", True))
            self.character_strength.setEnabled(strength_enabled)
            self.bypass_check.setChecked(bool(state.get("effects_bypassed", False)))
            self.active_voice_status.setText(state.get("text", "Active voice: Natural"))
            params = state.get("parameters", {})
            if params:
                preset_params = {
                    "gain": int(round(float(params.get("gain", 1.0)) * 10)),
                    "robot": int(round(float(params.get("robot", 0.0)) * 100)),
                    "lowpass": int(params.get("lowpass", 4000)),
                    "pitch": int(round(float(params.get("pitch", 0.0)))),
                }
                self.set_preset_controls(preset_params, persist_settings=False, mark_custom=False)
        finally:
            self._updating_voice_controls = False
        self.refresh_custom_voice_actions()

    def set_advanced_visible(self):
        visible = self.advanced_toggle.isChecked()
        for widget in getattr(self, "advanced_widgets", ()):
            widget.setVisible(visible)

    def preselect_devices(self):
        self.set_combo(self.input_box, self.service.default_input_id())
        self.set_combo(self.output_box, self.service.default_output_id())
        self.set_combo(self.monitor_box, self.service.default_monitor_id())

    def populate_device_boxes(self, devices, selections, select_first_available=False):
        for box in (self.input_box, self.output_box, self.monitor_box):
            box.blockSignals(True)
            box.clear()
        self.input_box.addItem("Select an input device", None)
        self.output_box.addItem("Select a virtual microphone output", None)
        self.monitor_box.addItem("Select a monitor output", None)
        for device in devices:
            label = f"{device.index}: {device.name}"
            if device.input_capable:
                self.input_box.addItem(label, device.index)
            if device.output_capable:
                self.output_box.addItem(label, device.index)
                self.monitor_box.addItem(label, device.index)
        input_matched = self.set_combo(self.input_box, selections.get("input"))
        output_matched = self.set_combo(self.output_box, selections.get("virtual_output"))
        monitor_matched = self.set_combo(self.monitor_box, selections.get("monitor_output"))
        if select_first_available:
            self._select_first_available(self.input_box, input_matched)
            self._select_first_available(self.output_box, output_matched)
            self._select_first_available(self.monitor_box, monitor_matched)
        for box in (self.input_box, self.output_box, self.monitor_box):
            box.blockSignals(False)

    def slider(self, layout, name, low, high, value):
        label = QLabel(f"{name}: {value}")
        s = QSlider(Qt.Horizontal)
        s.setRange(low, high)
        s.setValue(value)
        s._voice_lab_label = label
        s._voice_lab_label_name = name
        s.valueChanged.connect(lambda v: (label.setText(f"{name}: {v}"), self.apply_current_parameters()))
        layout.addWidget(label)
        layout.addWidget(s)
        return s

    def _build_input_processing_controls(self, layout):
        self.input_processing_controls = {}
        self._add_input_processing_group(
            layout,
            "high_pass",
            "High-Pass Filter",
            (("cutoff_hz", "Cutoff", 40, 200, "Hz", 1.0),),
        )
        self._add_input_processing_group(
            layout,
            "noise_gate",
            "Noise Gate",
            (
                ("threshold_dbfs", "Threshold", -70, -20, "dBFS", 1.0),
                ("release_ms", "Release", 40, 1000, "ms", 1.0),
            ),
        )
        self._add_input_processing_group(
            layout,
            "compressor",
            "Compressor",
            (
                ("threshold_dbfs", "Threshold", -40, 0, "dBFS", 1.0),
                ("ratio", "Ratio", 10, 100, ":1", 10.0),
                ("attack_ms", "Attack", 1, 100, "ms", 1.0),
                ("release_ms", "Release", 20, 1000, "ms", 1.0),
                ("makeup_gain_db", "Makeup Gain", 0, 12, "dB", 1.0),
            ),
        )
        self._add_input_processing_group(
            layout,
            "limiter",
            "Limiter",
            (
                ("ceiling_dbfs", "Ceiling", -120, -5, "dBFS", 10.0),
                ("release_ms", "Release", 20, 500, "ms", 1.0),
            ),
        )
        self.reset_input_processing_button = QPushButton("Reset Input Processing")
        self.reset_input_processing_button.clicked.connect(self.reset_input_processing)
        self.input_processing_widgets.append(self.reset_input_processing_button)
        layout.addWidget(self.reset_input_processing_button)

    def _add_input_processing_group(self, layout, processor, title, params):
        title_label = QLabel(title)
        enabled = QCheckBox("Enabled")
        enabled.stateChanged.connect(lambda _state, p=processor: self.update_input_processing(p))
        self.input_processing_widgets.extend((title_label, enabled))
        layout.addWidget(title_label)
        layout.addWidget(enabled)
        controls = {"enabled": enabled, "params": {}}
        for key, label_text, low, high, unit, scale in params:
            slider = self.input_processing_slider(layout, processor, key, label_text, low, high, unit, scale)
            controls["params"][key] = slider
        self.input_processing_controls[processor] = controls

    def input_processing_slider(self, layout, processor, key, name, low, high, unit, scale):
        label = QLabel("")
        slider = QSlider(Qt.Horizontal)
        slider.setRange(low, high)
        slider._voice_lab_label = label
        slider._voice_lab_processor = processor
        slider._voice_lab_param = key
        slider._voice_lab_label_name = name
        slider._voice_lab_unit = unit
        slider._voice_lab_scale = scale
        slider.valueChanged.connect(
            lambda value, s=slider: (
                self._set_input_processing_slider_label(s),
                self.update_input_processing(s._voice_lab_processor),
            )
        )
        layout.addWidget(label)
        layout.addWidget(slider)
        self.input_processing_widgets.extend((label, slider))
        return slider

    def set_input_processing_visible(self):
        visible = self.input_processing_toggle.isChecked()
        for widget in getattr(self, "input_processing_widgets", ()):
            widget.setVisible(visible)

    def sync_input_processing_from_service(self):
        if not hasattr(self.service, "input_processing_state") or not hasattr(self, "input_processing_controls"):
            return
        state = self.service.input_processing_state()
        self._updating_input_processing = True
        try:
            for processor, controls in self.input_processing_controls.items():
                processor_state = state.get(processor, {})
                controls["enabled"].setChecked(bool(processor_state.get("enabled", False)))
                for key, slider in controls["params"].items():
                    value = processor_state.get(key, 0)
                    slider.setValue(int(round(float(value) * float(slider._voice_lab_scale))))
                    self._set_input_processing_slider_label(slider)
                self._set_input_processing_params_enabled(processor)
        finally:
            self._updating_input_processing = False

    def update_input_processing(self, processor):
        if self._updating_input_processing or not hasattr(self.service, "update_input_processing"):
            return
        controls = self.input_processing_controls[processor]
        changes = {"enabled": controls["enabled"].isChecked()}
        for key, slider in controls["params"].items():
            changes[key] = slider.value() / float(slider._voice_lab_scale)
        result = self.service.update_input_processing(processor, **changes)
        self.display_result(result)
        if result.success:
            self._set_input_processing_params_enabled(processor)
        else:
            self.sync_input_processing_from_service()

    def _set_input_processing_params_enabled(self, processor):
        controls = self.input_processing_controls[processor]
        enabled = controls["enabled"].isChecked()
        for slider in controls["params"].values():
            slider.setEnabled(enabled)
            slider._voice_lab_label.setEnabled(enabled)

    def _set_input_processing_slider_label(self, slider):
        value = slider.value() / float(slider._voice_lab_scale)
        if slider._voice_lab_scale == 1.0:
            text_value = f"{int(round(value))}"
        else:
            text_value = f"{value:.1f}"
        slider._voice_lab_label.setText(
            f"{slider._voice_lab_label_name}: {text_value} {slider._voice_lab_unit}"
        )

    def reset_input_processing(self):
        if not hasattr(self.service, "reset_input_processing"):
            return
        defaults = {}
        if hasattr(self.service, "input_processing_state"):
            defaults = self.service.input_processing_state()
        if defaults != {
            "high_pass": {"enabled": False, "cutoff_hz": 80.0},
            "noise_gate": {"enabled": False, "threshold_dbfs": -45.0, "release_ms": 180.0},
            "compressor": {
                "enabled": False,
                "threshold_dbfs": -18.0,
                "ratio": 3.0,
                "attack_ms": 10.0,
                "release_ms": 150.0,
                "makeup_gain_db": 0.0,
            },
            "limiter": {"enabled": False, "ceiling_dbfs": -1.0, "release_ms": 80.0},
        }:
            response = QMessageBox.question(
                self,
                "Reset Input Processing",
                "Reset input processing to defaults?",
                QMessageBox.Yes | QMessageBox.Cancel,
                QMessageBox.Cancel,
            )
            if response != QMessageBox.Yes:
                return
        result = self.service.reset_input_processing()
        self.display_result(result)
        self.sync_input_processing_from_service()

    def refresh_preset_box(self):
        current = self.preset_box.currentText()
        self.preset_box.blockSignals(True)
        self.preset_box.clear()
        names = self.service.custom_preset_names() if hasattr(self.service, "custom_preset_names") else self.service.preset_names()
        self.preset_box.addItems(names)
        if current in names:
            self.preset_box.setCurrentText(current)
        self.preset_box.blockSignals(False)
        if hasattr(self, "character_box"):
            self._populate_character_box()
        self.refresh_custom_voice_actions()

    def current_params(self):
        return {
            "gain": self.gain.value(),
            "pitch": self.pitch.value(),
            "robot": self.robot.value(),
            "lowpass": self.lowpass.value(),
        }

    def apply_selected_preset(self):
        return self._apply_selected_preset(persist=True)

    def _apply_selected_preset(self, persist=True):
        name = self.preset_box.currentText()
        if not name:
            return
        if not self.confirm_discard_unsaved_changes("Select another custom voice?"):
            self.sync_voice_controls_from_service()
            return
        try:
            result = self.service.select_preset(name, persist=persist)
        except TypeError:
            result = self.service.select_preset(name)
        if not result.success:
            self.display_result(result)
            return
        self.set_preset_controls(result.metadata["params"], persist_settings=persist, mark_custom=False)
        self.sync_voice_controls_from_service()

    def record_device_selection(self, role, selected_id):
        if hasattr(self.service, "record_device_selection"):
            result = self.service.record_device_selection(role, selected_id)
            if not result.success:
                self.display_result(result)

    def set_preset_by_name(self, name):
        result = self.service.select_preset(name)
        if result.success:
            self.preset_box.setCurrentText(name)
            self.set_preset_controls(result.metadata["params"], mark_custom=False)
            self.sync_voice_controls_from_service()
            self.set_status(f"Preset hotkey: {name}")
        else:
            self.display_result(result)

    def set_preset_from_service(self, name, params):
        self.preset_box.setCurrentText(name)
        self.set_preset_controls(params, mark_custom=False)
        self.sync_voice_controls_from_service()

    def set_preset_controls(self, params, persist_settings=True, mark_custom=False):
        for slider in (self.gain, self.pitch, self.robot, self.lowpass):
            slider.blockSignals(True)
        self.gain.setValue(params.get("gain", 10))
        self.pitch.setValue(params.get("pitch", 0))
        self.robot.setValue(params.get("robot", 0))
        self.lowpass.setValue(params.get("lowpass", 4000))
        for slider in (self.gain, self.pitch, self.robot, self.lowpass):
            slider._voice_lab_label.setText(f"{slider._voice_lab_label_name}: {slider.value()}")
        for slider in (self.gain, self.pitch, self.robot, self.lowpass):
            slider.blockSignals(False)
        self.apply_current_parameters(persist_settings=persist_settings, mark_custom=mark_custom)

    def save_current_as_preset(self):
        name, ok = QInputDialog.getText(self, "Save Preset", "Preset name:")
        name = name.strip()
        if not ok or not name:
            return
        result = self.service.save_preset(name, self.current_params())
        if not result.success and result.metadata.get("conflict"):
            if not self.confirm_overwrite_custom_voice(name):
                return
            result = self.service.save_custom_voice(name, self.current_params(), overwrite=True)
        if not result.success:
            self.display_result(result)
            return
        self.refresh_preset_box()
        self.preset_box.setCurrentText(result.metadata.get("name", name))
        self.sync_voice_controls_from_service()
        self.display_result(result)

    def rename_current_preset(self):
        name = self.current_custom_voice_name()
        if not name:
            return
        new_name, ok = QInputDialog.getText(
            self,
            "Rename Custom Voice",
            "New custom voice name:",
            text=name,
        )
        if not ok:
            return
        result = self.service.rename_custom_voice(name, new_name)
        if not result.success:
            self.display_result(result)
            return
        self.refresh_preset_box()
        self.preset_box.setCurrentText(result.metadata["name"])
        self.sync_voice_controls_from_service()
        self.display_result(result)

    def duplicate_current_preset(self):
        name = self.current_custom_voice_name()
        if not name:
            return
        new_name, ok = QInputDialog.getText(
            self,
            "Duplicate Custom Voice",
            "New custom voice name:",
        )
        if not ok:
            return
        result = self.service.duplicate_custom_voice(name, new_name)
        if not result.success:
            self.display_result(result)
            return
        self.refresh_preset_box()
        self.preset_box.setCurrentText(result.metadata["name"])
        self.sync_voice_controls_from_service()
        self.display_result(result)

    def delete_current_preset(self):
        name = self.current_custom_voice_name()
        if not name:
            return
        if not self.confirm_delete_custom_voice(name):
            return
        result = self.service.delete_preset(name)
        self.refresh_preset_box()
        self.sync_voice_controls_from_service()
        self.display_result(result)

    def current_custom_voice_name(self):
        if not hasattr(self.service, "active_voice_state"):
            return self.preset_box.currentText()
        state = self.service.active_voice_state()
        if state.get("kind") != "custom":
            return ""
        return state.get("custom_preset") or ""

    def refresh_custom_voice_actions(self):
        enabled = bool(self.current_custom_voice_name()) if hasattr(self, "preset_box") else False
        for button_name in ("rename_preset_button", "duplicate_preset_button", "delete_preset_button"):
            button = getattr(self, button_name, None)
            if button is not None:
                button.setEnabled(enabled)

    def confirm_delete_custom_voice(self, name):
        response = QMessageBox.question(
            self,
            "Delete Custom Voice",
            f"Delete custom voice '{name}'?",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        return response == QMessageBox.Yes

    def confirm_overwrite_custom_voice(self, name):
        response = QMessageBox.question(
            self,
            "Overwrite Custom Voice",
            f"Overwrite existing custom voice '{name}'?",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        return response == QMessageBox.Yes

    def confirm_discard_unsaved_changes(self, title):
        if not hasattr(self.service, "active_voice_state"):
            return True
        if self.service.active_voice_state().get("kind") != "unsaved":
            return True
        response = QMessageBox.question(
            self,
            "Unsaved Changes",
            f"{title}\n\nDiscard Custom - Unsaved changes?",
            QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        return response == QMessageBox.Discard

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

    def refresh_devices(self):
        result = self.service.refresh_devices(
            input_id=self.input_box.currentData(),
            output_id=self.output_box.currentData(),
            monitor_id=self.monitor_box.currentData(),
        )
        if result.success:
            self.devices = self.service.devices()
            self.populate_device_boxes(self.devices, result.metadata["selections"])
        self.display_result(result)

    def play_sound(self, filename):
        self.apply_current_parameters()
        result = self.service.play_sound_file(filename)
        self.display_result(result)

    def apply_current_parameters(self, persist_settings=True, mark_custom=True):
        if self._updating_voice_controls:
            mark_custom = False
        kwargs = {
            "gain": self.gain.value() / 10.0,
            "robot": self.robot.value() / 100.0,
            "lowpass": self.lowpass.value(),
            "pitch": self.pitch.value(),
            "monitor_enabled": self.monitor_check.isChecked(),
            "monitor_volume": self.monitor_volume.value() / 100.0,
            "soundboard_volume": self.soundboard_volume.value() / 100.0,
            "persist_settings": persist_settings,
            "mark_custom": mark_custom,
        }
        try:
            return self.service.apply_effect_parameters(**kwargs)
        except TypeError:
            kwargs.pop("persist_settings")
            kwargs.pop("mark_custom", None)
            return self.service.apply_effect_parameters(**kwargs)

    def start(self):
        self.apply_current_parameters(mark_custom=False)
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
            item_data = box.itemData(i)
            if item_data == value or (
                isinstance(item_data, tuple)
                and len(item_data) == 2
                and item_data[1] == value
            ):
                box.setCurrentIndex(i)
                return True
        return False

    def _select_first_available(self, box, already_matched):
        if already_matched or box.count() <= 1:
            return
        box.setCurrentIndex(1)

    def _select_first_selectable_voice(self):
        for index in range(self.character_box.count()):
            data = self.character_box.itemData(index)
            if data and data[0] != "section":
                self.character_box.setCurrentIndex(index)
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
        self.refresh_devices_button.setEnabled(status.refresh_enabled)
        self.active_voice_status.setText(status.active_voice)
        if hasattr(self, "bypass_check"):
            self.bypass_check.blockSignals(True)
            self.bypass_check.setChecked(bool(status.diagnostics.get("effects_bypassed")))
            self.bypass_check.blockSignals(False)
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

    def refresh_audio_levels(self):
        if not hasattr(self.service, "audio_level_snapshot"):
            return
        try:
            snapshot = self.service.audio_level_snapshot()
        except Exception:
            return
        now = monotonic()
        overloaded = []
        signal_state = "Stopped"
        for key, label in (
            ("input", "Microphone Input"),
            ("processed", "Processed Voice"),
            ("output", "Output"),
        ):
            reading = getattr(snapshot, key, None)
            display = self.level_display_models[key].update(
                reading,
                processing_state=snapshot.processing_state,
                captured_at=snapshot.captured_at,
                now=now,
            )
            widgets = self.level_widgets[key]
            widgets["bar"].setValue(display.bar_percent)
            widgets["value"].setText(
                f"{display.level_text} | peak {display.peak_percent}% | {display.state_text}"
            )
            if display.overload_active:
                overloaded.append(label)
            if key == "input":
                signal_state = display.state_text
        overload_text = ", ".join(overloaded) if overloaded else "None"
        self.level_summary.setText(f"Input signal: {signal_state} | Overload: {overload_text}")

    def closeEvent(self, event):
        if hasattr(self, "status_timer"):
            self.status_timer.stop()
        if hasattr(self, "meter_timer"):
            self.meter_timer.stop()
        if self.on_close is not None:
            self.on_close()
        event.accept()
