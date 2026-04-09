from enum import IntEnum


class Level(IntEnum):
    TRACE = 0
    DEBUG = 10
    INFO  = 20
    WARN  = 30
    ERROR = 40
    FATAL = 50

    @classmethod
    def from_str(cls, s: str) -> "Level":
        try:
            return cls[s.upper()]
        except KeyError:
            raise ValueError(f"Unknown log level: {s!r}. Choose from: {[m.name for m in cls]}")
