import os
from time import monotonic

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QTabWidget,
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
        transport_layout = QVBoxLayout()
        root_layout.addLayout(transport_layout)
        self.tabs = QTabWidget()
        root_layout.addWidget(self.tabs)
        layout = self._create_tab("Voice")
        input_processing_layout = self._create_tab("Input Processing")
        routing_layout = self._create_tab("Routing")
        soundboard_tab_layout = self._create_tab("Soundboard")
        diagnostics_layout = self._create_tab("Diagnostics")
        source_analysis_layout = None
        target_planner_layout = None
        self.restored_preferences = self.service.operator_preferences() if hasattr(self.service, "operator_preferences") else {}
        self._updating_voice_controls = False
        self._updating_input_processing = False
        self._updating_formant_lab = False
        self._updating_target_planner = False
        self._last_voice_selection = None
        self.formant_lab_enabled = (
            hasattr(self.service, "formant_lab_state") and self.service.formant_lab_state() is not None
        )
        self.source_analysis_enabled = (
            hasattr(self.service, "source_analysis_snapshot")
            and self.service.source_analysis_snapshot() is not None
        )
        self.target_planner_enabled = (
            hasattr(self.service, "target_planner_state")
            and self.service.target_planner_state() is not None
        )
        if self.source_analysis_enabled:
            source_analysis_layout = self._create_tab("Source Analysis")
        if self.target_planner_enabled:
            target_planner_layout = self._create_tab("Target Planner")

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
        transport_layout.addWidget(self.active_voice_status)

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

        self.bypass_check = QCheckBox("Bypass Effects")
        self.bypass_check.stateChanged.connect(lambda _state: self.set_effects_bypassed())
        transport_layout.addWidget(self.bypass_check)
        self.reset_voice_button = QPushButton("Reset Voice")
        self.reset_voice_button.clicked.connect(self.reset_voice)
        layout.addWidget(self.reset_voice_button)

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

        routing_layout.addWidget(QLabel("Input device"))
        routing_layout.addWidget(self.input_box)
        routing_layout.addWidget(QLabel("Output to virtual mic"))
        routing_layout.addWidget(self.output_box)

        self.monitor_check = QCheckBox("Enable monitor output")
        self.monitor_check.setChecked(bool(self.restored_preferences.get("monitor_enabled", False)))
        self.monitor_check.stateChanged.connect(lambda _state: self.apply_current_parameters())
        routing_layout.addWidget(self.monitor_check)
        routing_layout.addWidget(QLabel("Monitor output device"))
        routing_layout.addWidget(self.monitor_box)
        self.refresh_devices_button = QPushButton("Refresh Devices")
        self.refresh_devices_button.clicked.connect(self.refresh_devices)
        routing_layout.addWidget(self.refresh_devices_button)

        self.monitor_volume = self.slider(
            routing_layout,
            "Monitor volume",
            0,
            100,
            int(round(float(self.restored_preferences.get("monitor_volume", 0.35)) * 100)),
        )
        self.soundboard_volume = self.slider(
            routing_layout,
            "Soundboard volume",
            0,
            100,
            int(round(float(self.restored_preferences.get("soundboard_volume", 0.70)) * 100)),
        )

        self.input_processing_widgets = []
        input_processing_help = QLabel(
            "Input processors are global operator settings, not custom voices. "
            "Bypass Effects temporarily skips them without erasing settings."
        )
        input_processing_help.setWordWrap(True)
        input_processing_layout.addWidget(input_processing_help)
        self._build_input_processing_controls(input_processing_layout)

        if self.formant_lab_enabled:
            self._build_formant_lab_controls(layout)
        if self.source_analysis_enabled and source_analysis_layout is not None:
            self._build_source_analysis_tab(source_analysis_layout)
        if self.target_planner_enabled and target_planner_layout is not None:
            self._build_target_planner_tab(target_planner_layout)

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

        soundboard_tab_layout.addWidget(QLabel("Soundboard - F1/F2/F3 for first 3 sounds"))
        self.soundboard_layout = QHBoxLayout()
        soundboard_tab_layout.addLayout(self.soundboard_layout)

        refresh_sounds = QPushButton("Refresh Sounds")
        refresh_sounds.clicked.connect(self.refresh_soundboard)
        soundboard_tab_layout.addWidget(refresh_sounds)

        btns = QHBoxLayout()
        self.start_button = QPushButton("Start Processing")
        self.stop_button = QPushButton("Stop Processing")
        self.start_button.clicked.connect(self.start)
        self.stop_button.clicked.connect(self.stop)
        btns.addWidget(self.start_button)
        btns.addWidget(self.stop_button)
        transport_layout.addLayout(btns)

        self.status = QLabel("Stopped")
        diagnostics_layout.addWidget(self.status)
        self.processing_status = QLabel("Processing: Stopped")
        self.route_status = QLabel("Routes stopped")
        self.pitch_status = QLabel("Pitch: Off")
        self.latency_status = QLabel("Estimated pitch DSP latency: Not active")
        self.command_status = QLabel("")
        self.warning_status = QLabel("Warnings: None")
        self.diagnostic_status = QLabel("")
        for label in (self.processing_status, self.route_status):
            label.setWordWrap(True)
            transport_layout.addWidget(label)
        for label in (
            self.pitch_status,
            self.latency_status,
            self.command_status,
            self.warning_status,
            self.diagnostic_status,
        ):
            label.setWordWrap(True)
            diagnostics_layout.addWidget(label)

        self.advanced_widgets.append(self.diagnostic_status)
        self.sync_voice_controls_from_service()
        self.sync_input_processing_from_service()
        self.sync_formant_lab_from_service()
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
        if self.source_analysis_enabled:
            self.source_analysis_timer = QTimer(self)
            self.source_analysis_timer.setInterval(250)
            self.source_analysis_timer.timeout.connect(self.refresh_source_analysis)
            self.source_analysis_timer.start()
        self.refresh_operator_status()
        self.refresh_audio_levels()
        self.refresh_source_analysis()
        self.refresh_target_planner()

    def _create_tab(self, title):
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        layout = QVBoxLayout(content)
        scroll_area.setWidget(content)
        self.tabs.addTab(scroll_area, title)
        return layout

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
        status_label = QLabel("State: OFF")
        status_label.setWordWrap(True)
        self.input_processing_widgets.extend((title_label, enabled, status_label))
        layout.addWidget(title_label)
        layout.addWidget(enabled)
        layout.addWidget(status_label)
        controls = {"enabled": enabled, "status": status_label, "params": {}}
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
            self.refresh_input_processing_activity()
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
            self.refresh_input_processing_activity()
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

    def _build_formant_lab_controls(self, layout):
        layout.addWidget(QLabel("Experimental Formant Lab"))
        self.formant_lab_enable = QCheckBox("Enable Prototype")
        self.formant_lab_enable.stateChanged.connect(lambda _state: self.update_formant_lab())
        layout.addWidget(self.formant_lab_enable)
        self.formant_lab_bypass = QCheckBox("Prototype A/B Bypass")
        self.formant_lab_bypass.stateChanged.connect(lambda _state: self.update_formant_lab())
        layout.addWidget(self.formant_lab_bypass)
        self.formant_lab_pitch = self._formant_lab_slider(layout, "Prototype Pitch", -24, 24)
        self.formant_lab_formant = self._formant_lab_slider(layout, "Formant", -24, 24)
        self.formant_lab_status = QLabel("Formant Lab: inactive")
        self.formant_lab_status.setWordWrap(True)
        layout.addWidget(self.formant_lab_status)
        self.formant_lab_reset = QPushButton("Reset Prototype")
        self.formant_lab_reset.clicked.connect(self.reset_formant_lab)
        layout.addWidget(self.formant_lab_reset)

    def _formant_lab_slider(self, layout, name, low, high):
        label = QLabel("")
        slider = QSlider(Qt.Horizontal)
        slider.setRange(low, high)
        slider._voice_lab_label = label
        slider._voice_lab_label_name = name
        slider.valueChanged.connect(
            lambda _value, s=slider: (
                self._set_formant_lab_slider_label(s),
                self.update_formant_lab(),
            )
        )
        layout.addWidget(label)
        layout.addWidget(slider)
        return slider

    def _set_formant_lab_slider_label(self, slider):
        semitones = slider.value() / 2.0
        if slider is getattr(self, "formant_lab_formant", None):
            factor = 2.0 ** (semitones / 12.0)
            slider._voice_lab_label.setText(
                f"{slider._voice_lab_label_name}: {semitones:.1f} st | {factor:.3f}x"
            )
        else:
            slider._voice_lab_label.setText(f"{slider._voice_lab_label_name}: {semitones:.1f} st")

    def sync_formant_lab_from_service(self):
        if not self.formant_lab_enabled:
            return
        state = self.service.formant_lab_state()
        if state is None:
            return
        self._updating_formant_lab = True
        try:
            self.formant_lab_enable.setChecked(bool(state.get("available", True)))
            self.formant_lab_bypass.setChecked(bool(state.get("bypassed", False)))
            self.formant_lab_pitch.setValue(int(round(float(state.get("pitch_semitones", 0.0)) * 2.0)))
            self.formant_lab_formant.setValue(int(round(float(state.get("formant_semitones", 0.0)) * 2.0)))
            self._set_formant_lab_slider_label(self.formant_lab_pitch)
            self._set_formant_lab_slider_label(self.formant_lab_formant)
        finally:
            self._updating_formant_lab = False
        self.refresh_formant_lab_status()

    def update_formant_lab(self):
        if self._updating_formant_lab or not self.formant_lab_enabled:
            return
        result = self.service.update_formant_lab(
            enabled=self.formant_lab_enable.isChecked(),
            pitch_semitones=self.formant_lab_pitch.value() / 2.0,
            formant_semitones=self.formant_lab_formant.value() / 2.0,
            bypassed=self.formant_lab_bypass.isChecked(),
        )
        self.display_result(result)
        if result.success:
            self.refresh_formant_lab_status()
        else:
            self.sync_formant_lab_from_service()

    def reset_formant_lab(self):
        if not self.formant_lab_enabled:
            return
        result = self.service.reset_formant_lab()
        self.display_result(result)
        self.sync_formant_lab_from_service()

    def refresh_formant_lab_status(self):
        if not self.formant_lab_enabled:
            return
        state = self.service.formant_lab_state()
        if state is None:
            return
        active = "active" if state.get("active") else "inactive"
        bypassed = "bypassed" if state.get("bypassed") else "engaged"
        self.formant_lab_status.setText(
            "Formant Lab: "
            f"{active} | {bypassed} | pitch {float(state.get('pitch_semitones', 0.0)):.1f} st | "
            f"formant {float(state.get('formant_semitones', 0.0)):.1f} st | "
            f"latency {int(state.get('latency_frames', 0))} frames"
        )

    def _build_source_analysis_tab(self, layout):
        heading = QLabel("Experimental - Passive Analysis Only")
        heading.setWordWrap(True)
        layout.addWidget(heading)
        guidance = QLabel(
            "For a stable profile, speak naturally for several seconds and include normal sentences, "
            "quiet and loud phrases, sustained vowels, and sibilant sounds such as s and sh."
        )
        guidance.setWordWrap(True)
        layout.addWidget(guidance)

        layout.addWidget(QLabel("Live Reading"))
        self.source_analysis_live = QLabel("No active reading")
        self.source_analysis_live.setWordWrap(True)
        layout.addWidget(self.source_analysis_live)

        layout.addWidget(QLabel("Rolling Source Profile"))
        self.source_analysis_profile = QLabel("Profile collecting")
        self.source_analysis_profile.setWordWrap(True)
        layout.addWidget(self.source_analysis_profile)

        layout.addWidget(QLabel("Runtime Status"))
        self.source_analysis_status = QLabel("Analyzer stopped")
        self.source_analysis_status.setWordWrap(True)
        layout.addWidget(self.source_analysis_status)

        self.source_analysis_reset = QPushButton("Reset Source Analysis")
        self.source_analysis_reset.clicked.connect(self.reset_source_analysis)
        layout.addWidget(self.source_analysis_reset)

    def reset_source_analysis(self):
        if not self.source_analysis_enabled:
            return
        result = self.service.reset_source_analysis()
        self.display_result(result)
        self.refresh_source_analysis()

    def refresh_source_analysis(self):
        if not getattr(self, "source_analysis_enabled", False):
            return
        try:
            snapshot = self.service.source_analysis_snapshot()
        except Exception:
            return
        if snapshot is None:
            return
        current = snapshot.get("current", {})
        profile = snapshot.get("profile", {})
        status = snapshot.get("status", {})
        voiced = "voiced" if current.get("voiced") else "unvoiced"
        self.source_analysis_live.setText(
            f"State: {voiced} | F0: {self._fmt_hz(current.get('f0_hz'))} | "
            f"confidence {self._fmt_ratio(current.get('f0_confidence'))} | "
            f"RMS {self._fmt_db(current.get('rms_dbfs'))} | peak {self._fmt_db(current.get('peak_dbfs'))} | "
            f"tilt {self._fmt_db(current.get('spectral_tilt_db'))} | "
            f"chest {self._fmt_ratio(current.get('chest_energy_ratio'))} | "
            f"low-mid {self._fmt_ratio(current.get('low_mid_energy_ratio'))} | "
            f"presence {self._fmt_ratio(current.get('presence_energy_ratio'))} | "
            f"brightness {self._fmt_ratio(current.get('brightness_energy_ratio'))} | "
            f"sibilance {self._fmt_ratio(current.get('sibilance_energy_ratio'))} | "
            f"resonance F1/F2/F3 {self._fmt_hz(current.get('f1_hz'))}/"
            f"{self._fmt_hz(current.get('f2_hz'))}/{self._fmt_hz(current.get('f3_hz'))}"
        )
        self.source_analysis_profile.setText(
            f"State: {profile.get('reliability', 'collecting')} | "
            f"voiced {float(profile.get('voiced_duration_seconds') or 0.0):.1f}s | "
            f"median F0 {self._fmt_hz(profile.get('median_f0_hz'))} | "
            f"range {self._fmt_hz(profile.get('lower_f0_hz'))}-"
            f"{self._fmt_hz(profile.get('upper_f0_hz'))} | "
            f"span {self._fmt_hz(profile.get('pitch_span_hz'))} / "
            f"{self._fmt_st(profile.get('pitch_span_semitones'))} | "
            f"tilt {self._fmt_db(profile.get('median_spectral_tilt_db'))} | "
            f"chest {self._fmt_ratio(profile.get('chest_energy_ratio'))} | "
            f"low-mid {self._fmt_ratio(profile.get('low_mid_energy_ratio'))} | "
            f"presence {self._fmt_ratio(profile.get('presence_energy_ratio'))} | "
            f"brightness {self._fmt_ratio(profile.get('brightness_energy_ratio'))} | "
            f"sibilance {self._fmt_ratio(profile.get('sibilance_energy_ratio'))} | "
            f"resonance F1/F2/F3 {self._fmt_hz(profile.get('f1_hz'))}/"
            f"{self._fmt_hz(profile.get('f2_hz'))}/{self._fmt_hz(profile.get('f3_hz'))}"
        )
        self.source_analysis_status.setText(
            f"Analyzer: {'active' if status.get('active') else 'stopped'} | "
            f"cadence {float(status.get('analysis_cadence_hz') or 0.0):.1f} Hz | "
            f"age {self._fmt_seconds(status.get('latest_snapshot_age_seconds'))} | "
            f"analyzed {int(status.get('analyzed_frame_count') or 0)} | "
            f"dropped {int(status.get('dropped_frame_count') or 0)} | "
            f"skipped {int(status.get('skipped_frame_count') or 0)} | "
            f"invalid {int(status.get('invalid_frame_count') or 0)} | "
            f"failure {status.get('last_failure') or 'none'}"
        )
        self.refresh_target_planner()

    def _build_target_planner_tab(self, layout):
        heading = QLabel("Experimental - Planning Only - Audio Is Not Modified")
        heading.setWordWrap(True)
        layout.addWidget(heading)

        refs = QHBoxLayout()
        neutral = QPushButton("Neutral")
        higher = QPushButton("Higher / Brighter")
        lower = QPushButton("Lower / Weightier")
        neutral.clicked.connect(lambda: self.load_target_reference("neutral"))
        higher.clicked.connect(lambda: self.load_target_reference("higher_brighter"))
        lower.clicked.connect(lambda: self.load_target_reference("lower_weightier"))
        refs.addWidget(neutral)
        refs.addWidget(higher)
        refs.addWidget(lower)
        layout.addLayout(refs)

        self.target_strength_label = QLabel("Character Strength: 100%")
        self.target_strength = QSlider(Qt.Horizontal)
        self.target_strength.setRange(0, 100)
        self.target_strength.setValue(100)
        self.target_strength.valueChanged.connect(self.set_target_planner_strength)
        layout.addWidget(self.target_strength_label)
        layout.addWidget(self.target_strength)

        self.target_planner_controls = {}
        for key, label, low, high, step, suffix in (
            ("target_median_f0_hz", "Target median F0", 60.0, 500.0, 1.0, " Hz"),
            ("target_pitch_span_st", "Target pitch span", 0.0, 24.0, 0.1, " st"),
            ("max_pitch_shift_st", "Max pitch shift", 0.0, 24.0, 0.5, " st"),
            ("nominal_formant_shift_st", "Nominal formant hint", -2.0, 2.0, 0.1, " st"),
            ("max_abs_formant_shift_st", "Max formant shift", 0.0, 2.0, 0.1, " st"),
            ("chest_energy_ratio", "Chest ratio", 0.0, 1.0, 0.01, ""),
            ("low_mid_energy_ratio", "Low-mid ratio", 0.0, 1.0, 0.01, ""),
            ("presence_energy_ratio", "Presence ratio", 0.0, 1.0, 0.01, ""),
            ("brightness_energy_ratio", "Brightness ratio", 0.0, 1.0, 0.01, ""),
            ("sibilance_energy_ratio", "Sibilance ratio", 0.0, 1.0, 0.01, ""),
            ("spectral_tilt_db", "Spectral tilt", -30.0, 10.0, 0.5, " dB"),
            ("breathiness", "Breathiness", 0.0, 1.0, 0.01, ""),
            ("harmonic_weight", "Harmonic weight", 0.0, 1.0, 0.01, ""),
        ):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            spin = QDoubleSpinBox()
            spin.setRange(low, high)
            spin.setSingleStep(step)
            spin.setDecimals(2)
            spin.setSuffix(suffix)
            spin.valueChanged.connect(lambda _value, field=key: self.update_target_profile_field(field))
            row.addWidget(spin)
            layout.addLayout(row)
            self.target_planner_controls[key] = spin

        self.target_source_summary = QLabel("Source Profile: unavailable")
        self.target_source_summary.setWordWrap(True)
        layout.addWidget(self.target_source_summary)
        self.target_plan_summary = QLabel("Calculated Plan: unavailable")
        self.target_plan_summary.setWordWrap(True)
        layout.addWidget(self.target_plan_summary)
        self.target_plan_details = QLabel("")
        self.target_plan_details.setWordWrap(True)
        layout.addWidget(self.target_plan_details)
        reset = QPushButton("Reset Planner")
        reset.clicked.connect(self.reset_target_planner)
        layout.addWidget(reset)
        self.refresh_target_planner()

    def set_target_planner_strength(self, value):
        if self._updating_target_planner or not getattr(self, "target_planner_enabled", False):
            return
        self.target_strength_label.setText(f"Character Strength: {int(value)}%")
        result = self.service.set_target_planner_strength(value)
        if not result.success:
            self.display_result(result)
        self.refresh_target_planner()

    def update_target_profile_field(self, field):
        if self._updating_target_planner or not getattr(self, "target_planner_enabled", False):
            return
        spin = self.target_planner_controls[field]
        result = self.service.update_target_profile(**{field: spin.value()})
        if not result.success:
            self.display_result(result)
        self.refresh_target_planner()

    def load_target_reference(self, reference):
        if not getattr(self, "target_planner_enabled", False):
            return
        result = self.service.load_target_reference(reference)
        self.display_result(result)
        self.refresh_target_planner()

    def reset_target_planner(self):
        if not getattr(self, "target_planner_enabled", False):
            return
        result = self.service.reset_target_planner()
        self.display_result(result)
        self.refresh_target_planner()

    def refresh_target_planner(self):
        if not getattr(self, "target_planner_enabled", False):
            return
        try:
            state = self.service.target_planner_state()
        except Exception:
            return
        if state is None:
            return
        profile = state.get("target_profile", {})
        plan = state.get("plan", {})
        self._updating_target_planner = True
        try:
            self.target_strength.setValue(int(round(float(state.get("strength_percent") or 0.0))))
            self.target_strength_label.setText(f"Character Strength: {self.target_strength.value()}%")
            for key, spin in self.target_planner_controls.items():
                if key in profile:
                    spin.setValue(float(profile[key]))
        finally:
            self._updating_target_planner = False

        self.target_source_summary.setText(
            f"Source Profile: {plan.get('source_reliability', 'unavailable')} | "
            f"confidence {self._fmt_ratio(plan.get('aggregate_confidence'))} | "
            f"age {self._fmt_seconds(plan.get('source_profile_age_seconds'))}"
        )
        pitch = plan.get("pitch", {})
        formant = plan.get("formant", {})
        spectral = plan.get("spectral", {})
        brightness = spectral.get("brightness_db", {})
        tilt = spectral.get("spectral_tilt_db", {})
        self.target_plan_summary.setText(
            f"Calculated Plan: {plan.get('status', 'unavailable')} | "
            f"pitch {self._fmt_st(pitch.get('applied_pitch_shift_st'))} | "
            f"range x{float(pitch.get('applied_pitch_range_scale') or 1.0):.2f} | "
            f"formant {self._fmt_st(formant.get('applied_formant_shift_st'))} | "
            f"brightness {self._fmt_db(brightness.get('applied_db'))} | "
            f"tilt {self._fmt_db(tilt.get('applied_db'))}"
        )
        self.target_plan_details.setText(
            "Capabilities: "
            f"{', '.join(plan.get('required_capabilities') or ('none',))} | "
            "Warnings: "
            f"{', '.join(plan.get('warnings') or ('none',))}"
        )

    def _fmt_hz(self, value):
        return "unavailable" if value is None else f"{float(value):.1f} Hz"

    def _fmt_db(self, value):
        return "unavailable" if value is None else f"{float(value):.1f} dB"

    def _fmt_ratio(self, value):
        return "unavailable" if value is None else f"{float(value):.2f}"

    def _fmt_st(self, value):
        return "unavailable" if value is None else f"{float(value):.1f} st"

    def _fmt_seconds(self, value):
        return "unavailable" if value is None else f"{float(value):.2f}s"

    def refresh_input_processing_activity(self):
        if not hasattr(self.service, "input_processing_activity") or not hasattr(self, "input_processing_controls"):
            return
        try:
            activity = self.service.input_processing_activity()
        except Exception:
            return
        for processor, controls in self.input_processing_controls.items():
            state = activity.get(processor, {})
            enabled = bool(state.get("enabled", False))
            status = state.get("state", "OFF")
            gain_reduction = float(state.get("gain_reduction_db", 0.0) or 0.0)
            details = f"State: {'ENABLED' if enabled else 'OFF'}"
            if enabled:
                details += f" | {status}"
                if processor == "high_pass":
                    details += f" | cutoff {state.get('cutoff_hz', 0):g} Hz"
                else:
                    details += f" | reduction {gain_reduction:.1f} dB"
                if processor == "limiter" and state.get("ceiling_hit"):
                    details += " | ceiling hit"
                if state.get("bypassed"):
                    details += " | bypassed"
            controls["status"].setText(details)

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
        self.refresh_formant_lab_status()
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
        self.refresh_input_processing_activity()
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
        if hasattr(self, "source_analysis_timer"):
            self.source_analysis_timer.stop()
        if self.on_close is not None:
            self.on_close()
        event.accept()
