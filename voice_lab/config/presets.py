import json
import os

from voice_lab.config.config import PRESET_PATH


DEFAULT_PRESETS = {
    "Clean": {"gain": 10, "robot": 0, "lowpass": 4000},
    "Muffled": {"gain": 12, "robot": 0, "lowpass": 900},
    "Robot": {"gain": 12, "robot": 100, "lowpass": 4000},
    "Deep-ish": {"gain": 18, "robot": 25, "lowpass": 1800},
    "Radio": {"gain": 16, "robot": 15, "lowpass": 2300},
}


def load_presets():
    if os.path.exists(PRESET_PATH):
        try:
            with open(PRESET_PATH, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return DEFAULT_PRESETS.copy()


def save_presets(presets):
    with open(PRESET_PATH, "w") as f:
        json.dump(presets, f, indent=2)
