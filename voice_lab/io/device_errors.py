from dataclasses import dataclass


@dataclass(frozen=True)
class DeviceFailure:
    category: str
    role: str
    selected_device_id: int | None = None
    technical_detail: str = ""
    recoverable: bool = True


class DeviceFailureError(RuntimeError):
    def __init__(self, failure):
        self.failure = failure
        super().__init__(failure.technical_detail or failure.category)
