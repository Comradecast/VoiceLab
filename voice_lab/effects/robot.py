import numpy as np

from .base import Effect


class RobotEffect(Effect):
    name = "Robot"

    def __init__(self, get_amount):
        self.get_amount = get_amount
        self.phase = 0

    def process(self, mono, frames, sample_rate):
        amount = self.get_amount()
        t = (np.arange(frames) + self.phase) / sample_rate
        carrier = np.sin(2 * np.pi * 85 * t)
        self.phase += frames
        return mono * (1.0 - amount) + (mono * carrier) * amount
