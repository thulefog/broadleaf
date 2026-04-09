from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class LogRecord:
    ts: str
    level: str
    component: str
    event: str
    msg: str
    fields: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def now(
        cls,
        level: str,
        component: str,
        event: str,
        msg: str,
        fields: dict[str, Any],
    ) -> "LogRecord":
        return cls(
            ts=datetime.now(timezone.utc).isoformat(),
            level=level,
            component=component,
            event=event,
            msg=msg,
            fields=fields,
        )

    def to_dict(self) -> dict[str, Any]:
        """Flat dict — fixed fields first, then arbitrary fields."""
        return {
            "ts": self.ts,
            "level": self.level,
            "component": self.component,
            "event": self.event,
            "msg": self.msg,
            **self.fields,
        }
