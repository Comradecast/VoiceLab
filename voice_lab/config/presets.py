import json
import os

from voice_lab.config.config import PRESET_PATH


DEFAULT_PRESETS = {
    "Natural": {"gain": 10, "robot": 0, "lowpass": 4000, "pitch": 0},
    "Deep Voice": {"gain": 9, "robot": 0, "lowpass": 2200, "pitch": -4},
    "High Voice": {"gain": 9, "robot": 0, "lowpass": 6500, "pitch": 4},
    "Clean": {"gain": 10, "robot": 0, "lowpass": 4000, "pitch": 0},
    "Muffled": {"gain": 12, "robot": 0, "lowpass": 900, "pitch": 0},
    "Robot": {"gain": 12, "robot": 100, "lowpass": 4000, "pitch": 0},
    "Deep-ish": {"gain": 18, "robot": 25, "lowpass": 1800, "pitch": 0},
    "Radio": {"gain": 16, "robot": 15, "lowpass": 2300, "pitch": 0},
}


def load_presets():
    if os.path.exists(PRESET_PATH):
        try:
            with open(PRESET_PATH, "r") as f:
                user_presets = json.load(f)
                if isinstance(user_presets, dict):
                    presets = DEFAULT_PRESETS.copy()
                    presets.update(user_presets)
                    return presets
        except Exception:
            pass
    return DEFAULT_PRESETS.copy()


def save_presets(presets):
    with open(PRESET_PATH, "w") as f:
        json.dump(presets, f, indent=2)
