from dataclasses import dataclass


@dataclass(frozen=True)
class DeviceDescriptor:
    index: int
    name: str
    hostapi: int | str
    max_input_channels: int
    max_output_channels: int
    default_samplerate: float | None = None

    @property
    def input_capable(self):
        return self.max_input_channels > 0

    @property
    def output_capable(self):
        return self.max_output_channels > 0

    @property
    def identity(self):
        return (
            self.name,
            self.hostapi,
            self.max_input_channels,
            self.max_output_channels,
            self.default_samplerate,
        )

    def asdict(self):
        return {
            "index": self.index,
            "name": self.name,
            "hostapi": self.hostapi,
            "max_input_channels": self.max_input_channels,
            "max_output_channels": self.max_output_channels,
            "default_samplerate": self.default_samplerate,
            "input_capable": self.input_capable,
            "output_capable": self.output_capable,
        }


def describe_devices(raw_devices):
    return tuple(
        DeviceDescriptor(
            index=index,
            name=str(device.get("name", "")),
            hostapi=device.get("hostapi", ""),
            max_input_channels=int(device.get("max_input_channels", 0) or 0),
            max_output_channels=int(device.get("max_output_channels", 0) or 0),
            default_samplerate=_optional_float(device.get("default_samplerate")),
        )
        for index, device in enumerate(raw_devices)
    )


def _optional_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
