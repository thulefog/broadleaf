import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from .base import Sink

_50MB = 50 * 1024 * 1024


class FileSink(Sink):
    """
    Daily-rotating JSONL file sink.

    Writes to  <log_dir>/broadleaf_YYYY-MM-DD.jsonl.
    When a file exceeds max_bytes within a day a timestamped suffix is added
    and a fresh file is opened — previous lines are never touched.
    """

    def __init__(self, log_dir: str | Path = "logs", max_bytes: int = _50MB):
        self._dir = Path(log_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._max_bytes = max_bytes
        self._lock = Lock()
        self._current_date: str = ""
        self._file = None
        self._open_file()

    # ------------------------------------------------------------------ #
    def _today(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y%m%d")

    def _open_file(self) -> None:
        """Open (or re-open after rotation) the current log file."""
        if self._file:
            self._file.close()
        self._current_date = self._today()
        path = self._dir / f"{self._current_date}_broadleaf.jsonl"
        # buffering=1 → line-buffered: each newline triggers an OS write
        self._file = open(path, "a", buffering=1, encoding="utf-8")

    def _rotate_if_needed(self) -> None:
        if self._today() != self._current_date:
            self._open_file()
            return
        if self._file and self._file.tell() >= self._max_bytes:
            self._file.close()
            ts = datetime.now(timezone.utc).strftime("%H%M%S")
            path = self._dir / f"{self._current_date}_{ts}_broadleaf.jsonl"
            self._file = open(path, "a", buffering=1, encoding="utf-8")

    # ------------------------------------------------------------------ #
    def write(self, record: dict[str, Any]) -> None:
        with self._lock:
            self._rotate_if_needed()
            self._file.write(json.dumps(record, default=str) + "\n")

    def flush(self) -> None:
        with self._lock:
            if self._file:
                self._file.flush()

    def close(self) -> None:
        with self._lock:
            if self._file:
                self._file.close()
                self._file = None
