import numpy as np
from .base import Effect

class GainEffect(Effect):
    name = "Gain"

    def __init__(self, get_gain):
        self.get_gain = get_gain

    def process(self, mono, frames, sample_rate):
        mono = mono * self.get_gain()
        return np.clip(mono, -0.95, 0.95)
