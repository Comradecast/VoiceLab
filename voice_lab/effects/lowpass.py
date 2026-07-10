from scipy.signal import butter, lfilter

from .base import Effect


class LowpassEffect(Effect):
    name = "Lowpass"

    def __init__(self, get_cutoff):
        self.get_cutoff = get_cutoff

    def process(self, mono, frames, sample_rate):
        cutoff = max(300, min(self.get_cutoff(), 8000))
        b, a = butter(2, cutoff / (sample_rate / 2), btype="low")
        return lfilter(b, a, mono)
