from dataclasses import dataclass

from voice_lab.core import AudioFrame


@dataclass(frozen=True)
class OutputBuses:
    main_bus: AudioFrame
    monitor_bus: AudioFrame

    def __post_init__(self):
        if not isinstance(self.main_bus, AudioFrame):
            raise ValueError("OutputBuses main_bus must be an AudioFrame")
        if not isinstance(self.monitor_bus, AudioFrame):
            raise ValueError("OutputBuses monitor_bus must be an AudioFrame")
