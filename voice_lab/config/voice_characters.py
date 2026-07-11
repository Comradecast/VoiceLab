from dataclasses import dataclass
from math import exp, isfinite, log
from numbers import Real

from voice_lab.config.validation import validate_preset_parameters


@dataclass(frozen=True)
class VoiceCharacter:
    id: str
    display_name: str
    description: str
    target_parameters: dict
    strength_enabled: bool = True
    compatibility_preset_name: str | None = None

    def asdict(self):
        return {
            "id": self.id,
            "display_name": self.display_name,
            "description": self.description,
            "target_parameters": dict(self.target_parameters),
            "strength_enabled": self.strength_enabled,
            "compatibility_preset_name": self.compatibility_preset_name,
        }


NATURAL_CHARACTER_ID = "natural"
DEFAULT_CHARACTER_STRENGTH = 100.0


BUILT_IN_CHARACTERS = (
    VoiceCharacter(
        id="natural",
        display_name="Natural",
        description="Clear voice with no intentional pitch transformation",
        target_parameters={"gain": 10, "robot": 0, "lowpass": 4000, "pitch": 0},
        strength_enabled=False,
        compatibility_preset_name="Natural",
    ),
    VoiceCharacter(
        id="deep",
        display_name="Deep",
        description="Lower, darker voice intended for normal use",
        target_parameters={"gain": 9, "robot": 0, "lowpass": 2200, "pitch": -4},
        compatibility_preset_name="Deep Voice",
    ),
    VoiceCharacter(
        id="heavy_bass",
        display_name="Heavy Bass",
        description="Stronger low-pitched transformation",
        target_parameters={"gain": 10, "robot": 0, "lowpass": 1800, "pitch": -6},
    ),
    VoiceCharacter(
        id="higher",
        display_name="Higher",
        description="Brighter, higher-pitched voice",
        target_parameters={"gain": 9, "robot": 0, "lowpass": 6500, "pitch": 4},
        compatibility_preset_name="High Voice",
    ),
    VoiceCharacter(
        id="robot",
        display_name="Robot",
        description="Full robotic modulation",
        target_parameters={"gain": 12, "robot": 100, "lowpass": 4000, "pitch": 0},
        compatibility_preset_name="Robot",
    ),
    VoiceCharacter(
        id="radio",
        display_name="Radio",
        description="Compressed, mechanical radio-style voice",
        target_parameters={"gain": 16, "robot": 15, "lowpass": 2300, "pitch": 0},
        compatibility_preset_name="Radio",
    ),
    VoiceCharacter(
        id="muffled",
        display_name="Muffled",
        description="Dark, heavily filtered voice",
        target_parameters={"gain": 12, "robot": 0, "lowpass": 900, "pitch": 0},
        compatibility_preset_name="Muffled",
    ),
)


def voice_characters():
    return BUILT_IN_CHARACTERS


def character_by_id(character_id):
    for character in BUILT_IN_CHARACTERS:
        if character.id == character_id:
            return character
    return None


def character_by_compatibility_preset(name):
    if not name:
        return None
    for character in BUILT_IN_CHARACTERS:
        if name in {character.display_name, character.compatibility_preset_name}:
            return character
    return None


def protected_voice_names():
    names = set()
    for character in BUILT_IN_CHARACTERS:
        names.add(character.display_name)
        if character.compatibility_preset_name:
            names.add(character.compatibility_preset_name)
    return frozenset(names)


def resolve_character_parameters(character_id, strength):
    character = character_by_id(character_id)
    if character is None:
        raise ValueError(f"Unknown voice character: {character_id}")
    normalized_strength = validate_strength(strength)
    natural = character_by_id(NATURAL_CHARACTER_ID)
    if character.id == NATURAL_CHARACTER_ID or not character.strength_enabled:
        resolved = dict(natural.target_parameters)
    else:
        t = normalized_strength / 100.0
        resolved = {
            "gain": _lerp(natural.target_parameters["gain"], character.target_parameters["gain"], t),
            "robot": _lerp(natural.target_parameters["robot"], character.target_parameters["robot"], t),
            "pitch": _lerp(natural.target_parameters["pitch"], character.target_parameters["pitch"], t),
            "lowpass": _log_lerp(
                natural.target_parameters["lowpass"],
                character.target_parameters["lowpass"],
                t,
            ),
        }
    validation = validate_preset_parameters(resolved)
    if not validation.success:
        raise ValueError(validation.message)
    return validation.preset, validation.effect_parameters


def validate_character_catalog():
    ids = [character.id for character in BUILT_IN_CHARACTERS]
    names = [character.display_name for character in BUILT_IN_CHARACTERS]
    if len(set(ids)) != len(ids):
        raise ValueError("Voice character ids must be unique")
    if len(set(names)) != len(names):
        raise ValueError("Voice character display names must be unique")
    for character in BUILT_IN_CHARACTERS:
        validation = validate_preset_parameters(character.target_parameters)
        if not validation.success:
            raise ValueError(f"Invalid character target {character.id}: {validation.message}")
    return True


def validate_strength(value):
    if not isinstance(value, Real) or isinstance(value, bool) or not isfinite(value):
        raise ValueError("Character strength must be a finite number")
    value = float(value)
    if value < 0.0 or value > 100.0:
        raise ValueError("Character strength must be between 0 and 100")
    return value


def _lerp(start, end, t):
    return float(start) + (float(end) - float(start)) * float(t)


def _log_lerp(start, end, t):
    start = float(start)
    end = float(end)
    if start <= 0 or end <= 0:
        return int(round(_lerp(start, end, t)))
    return int(round(exp(log(start) + (log(end) - log(start)) * float(t))))
