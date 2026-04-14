"""
LogReader — streaming JSONL query interface.

Reads across all broadleaf_*.jsonl files in a directory, oldest-first,
without loading any full file into memory.

Example::

    from broadleaf import LogReader
    from datetime import datetime, timedelta, timezone

    reader = LogReader("logs/")

    # All inference predictions for a specific batch
    for rec in reader.query(component="inference", search="abc123"):
        print(rec["prediction"], rec["confidence"])

    # All warnings and above from training, last hour
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    for rec in reader.query(component="train", level="WARN", since=since):
        print(rec)

    # Collect into a list (small result sets only)
    results = list(reader.query(component="receiver", event="batch_received", limit=50))

    # Arbitrary predicate
    for rec in reader.query(predicate=lambda r: r.get("confidence", 1.0) < 0.5):
        print(rec)

    # Load a single file directly
    reader = LogReader.from_file("logs/2026-04-13_broadleaf.jsonl")
    for rec in reader.query(level="ERROR"):
        print(rec)
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Generator

from .level import Level


class LogReader:
    """Streaming query over broadleaf JSONL log files."""

    def __init__(self, log_dir: str | Path = "logs") -> None:
        self._dir = Path(log_dir)
        self._file: Path | None = None

    @classmethod
    def from_file(cls, path: str | Path) -> "LogReader":
        """Create a reader targeting a single JSONL file instead of a directory."""
        reader = cls.__new__(cls)
        reader._dir = Path(path).parent
        reader._file = Path(path)
        return reader

    # ------------------------------------------------------------------ #
    def query(
        self,
        *,
        component: str | None = None,
        level: str | None = None,
        event: str | None = None,
        search: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        predicate: Callable[[dict[str, Any]], bool] | None = None,
        limit: int | None = 500,
    ) -> Generator[dict[str, Any], None, None]:
        """
        Stream records matching all supplied filters, oldest-first.

        Parameters
        ----------
        component : str, optional
            Prefix match on the component field.
            ``"inference"`` matches ``"inference"`` and ``"inference.embed"``.
        level : str, optional
            Minimum level name (TRACE/DEBUG/INFO/WARN/ERROR/FATAL).
        event : str, optional
            Exact match on the event field.
        search : str, optional
            Case-insensitive substring match across the full JSON line.
        since : datetime, optional
            Only records at or after this timestamp (tz-aware recommended).
        until : datetime, optional
            Only records at or before this timestamp.
        predicate : callable, optional
            ``fn(record: dict) -> bool``.  Applied after all other filters.
            Use for field-level checks that the named filters don't cover,
            e.g. ``predicate=lambda r: r.get("confidence", 1.0) < 0.5``.
        limit : int, optional
            Stop after this many matches.  Default 500.  Pass None for all.
        """
        min_level = Level.from_str(level) if level else Level.TRACE
        count = 0

        paths = [self._file] if self._file is not None else sorted(self._dir.glob("*_broadleaf*.jsonl"))

        for path in paths:
            with open(path, "r", encoding="utf-8") as f:
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        record = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    if not self._matches(record, raw, component, min_level, event, search, since, until):
                        continue

                    if predicate is not None and not predicate(record):
                        continue

                    yield record
                    count += 1
                    if limit is not None and count >= limit:
                        return

    # ------------------------------------------------------------------ #
    def tail(self, n: int = 50, **filters: Any) -> list[dict[str, Any]]:
        """Return the last n matching records (newest-first not guaranteed — use for quick inspection)."""
        results = list(self.query(**filters, limit=None))
        return results[-n:]

    # ------------------------------------------------------------------ #
    @staticmethod
    def _matches(
        record: dict[str, Any],
        raw: str,
        component: str | None,
        min_level: Level,
        event: str | None,
        search: str | None,
        since: datetime | None,
        until: datetime | None,
    ) -> bool:
        # Component prefix match
        if component is not None:
            rec_comp = record.get("component", "")
            if not (rec_comp == component or rec_comp.startswith(component + ".")):
                return False

        # Level filter
        try:
            rec_level = Level.from_str(record.get("level", "INFO"))
        except ValueError:
            rec_level = Level.INFO
        if rec_level < min_level:
            return False

        # Exact event match
        if event is not None and record.get("event") != event:
            return False

        # Time range
        if since is not None or until is not None:
            ts_str = record.get("ts", "")
            try:
                ts = datetime.fromisoformat(ts_str)
                if since is not None and ts < since:
                    return False
                if until is not None and ts > until:
                    return False
            except (ValueError, TypeError):
                pass

        # Full-text search across the raw JSON line
        if search is not None and search.lower() not in raw.lower():
            return False

        return True
