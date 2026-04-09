from abc import ABC, abstractmethod
from typing import Any


class Sink(ABC):
    """Abstract base for all log destinations."""

    @abstractmethod
    def write(self, record: dict[str, Any]) -> None:
        """Write a single log record. Must be thread-safe."""
        ...

    def flush(self) -> None:
        """Flush any buffered output."""

    def close(self) -> None:
        """Release resources."""
