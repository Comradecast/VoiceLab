from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CommandResult:
    success: bool
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok(cls, message: str = "", **metadata: Any) -> "CommandResult":
        return cls(True, message, metadata)

    @classmethod
    def fail(cls, message: str = "", **metadata: Any) -> "CommandResult":
        return cls(False, message, metadata)
