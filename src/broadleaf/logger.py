"""
Core logger and process-level engine.

Usage
-----
    from broadleaf import get_logger, configure

    # Optional — call once at startup to customise sink/level.
    # If omitted, defaults are read from LOG_SINK / LOG_LEVEL / LOG_DIR env vars.
    configure(log_dir="logs", min_level="INFO")

    log = get_logger("receiver")
    log.info("batch_received", batch_id="abc123", sample_count=864)

    # Bind context for a sub-operation — every record inherits the fields.
    engine_log = get_logger("inference").bind(weights="v1.pt", batch_id="abc123")
    engine_log.info("predict", prediction="shake", confidence=0.71, latency_ms=12.4)
"""

import os
import queue
import threading
from typing import Any

from .level import Level
from .record import LogRecord
from .sinks.base import Sink
from .sinks.file_sink import FileSink
from .sinks.stdout_sink import StdoutSink

# ---------------------------------------------------------------------------
# Public logger (bound to a component)
# ---------------------------------------------------------------------------

class Logger:
    """
    Structured logger bound to a component name.

    Holds a reference to the engine so that changes made via configure()
    (sink, min_level) take effect immediately on all existing Logger instances,
    regardless of call order.

    All emit methods accept an event name (machine-readable, snake_case),
    an optional human-readable msg, and arbitrary keyword fields that are
    merged into the top-level JSONL record.
    """

    __slots__ = ("_component", "_engine", "_ctx")

    def __init__(
        self,
        component: str,
        engine: "_Engine",
        ctx: dict[str, Any] | None = None,
    ) -> None:
        self._component = component
        self._engine = engine
        self._ctx: dict[str, Any] = ctx or {}

    # ------------------------------------------------------------------ #
    def bind(self, **ctx: Any) -> "Logger":
        """
        Return a child logger with additional pre-set context fields.

        Example::

            run = get_logger("train").bind(run_id="r42", config_hash="deadbeef")
            run.info("epoch_end", epoch=5, loss=0.31)
            # → every record from `run` includes run_id and config_hash
        """
        return Logger(self._component, self._engine, {**self._ctx, **ctx})

    # ------------------------------------------------------------------ #
    def _emit(self, level: Level, event: str, msg: str, **fields: Any) -> None:
        # Read min_level live from the engine — configure() changes take effect immediately
        if level < self._engine._min_level:
            return
        record = LogRecord.now(
            level=level.name,
            component=self._component,
            event=event,
            msg=msg,
            fields={**self._ctx, **fields},
        )
        try:
            self._engine._queue.put_nowait(record.to_dict())
        except queue.Full:
            pass  # drop rather than block the caller

    # ------------------------------------------------------------------ #
    def trace(self, event: str, msg: str = "", **fields: Any) -> None:
        self._emit(Level.TRACE, event, msg, **fields)

    def debug(self, event: str, msg: str = "", **fields: Any) -> None:
        self._emit(Level.DEBUG, event, msg, **fields)

    def info(self, event: str, msg: str = "", **fields: Any) -> None:
        self._emit(Level.INFO, event, msg, **fields)

    def warn(self, event: str, msg: str = "", **fields: Any) -> None:
        self._emit(Level.WARN, event, msg, **fields)

    def error(self, event: str, msg: str = "", **fields: Any) -> None:
        self._emit(Level.ERROR, event, msg, **fields)

    def fatal(self, event: str, msg: str = "", **fields: Any) -> None:
        self._emit(Level.FATAL, event, msg, **fields)


# ---------------------------------------------------------------------------
# Process-level engine (singleton)
# ---------------------------------------------------------------------------

class _Engine:
    """
    One per process.  Owns the async queue and the background drain thread.

    The drain thread pulls records off the queue and writes them to the
    configured sink.  Callers never wait for I/O — they enqueue and return.
    """

    _QUEUE_MAXSIZE = 10_000

    def __init__(self) -> None:
        self._sink: Sink | None = None
        self._min_level: Level = Level.INFO
        self._queue: queue.Queue[dict | None] = queue.Queue(maxsize=self._QUEUE_MAXSIZE)
        self._lock = threading.Lock()
        self._thread = threading.Thread(
            target=self._drain,
            daemon=True,
            name="broadleaf-drain",
        )
        self._thread.start()

    # ------------------------------------------------------------------ #
    def configure(
        self,
        sink: Sink | None = None,
        min_level: Level | str = Level.INFO,
        log_dir: str = "logs",
    ) -> None:
        with self._lock:
            if isinstance(min_level, str):
                min_level = Level.from_str(min_level)
            self._min_level = min_level

            if sink is not None:
                self._sink = sink
            elif self._sink is None:
                self._sink = self._default_sink(log_dir)

            # Restart the drain thread if it exited (e.g. after shutdown())
            if not self._thread.is_alive():
                self._queue = queue.Queue(maxsize=self._QUEUE_MAXSIZE)
                self._thread = threading.Thread(
                    target=self._drain,
                    daemon=True,
                    name="broadleaf-drain",
                )
                self._thread.start()

    def _default_sink(self, log_dir: str) -> Sink:
        sink_type = os.environ.get("LOG_SINK", "file").lower()
        if sink_type == "stdout":
            return StdoutSink()
        resolved_dir = os.environ.get("LOG_DIR", log_dir)
        return FileSink(log_dir=resolved_dir)

    # ------------------------------------------------------------------ #
    def get_logger(self, component: str) -> Logger:
        return Logger(component, self)

    # ------------------------------------------------------------------ #
    def _drain(self) -> None:
        """Background thread — pulls records and writes to sink."""
        while True:
            record = self._queue.get()
            if record is None:          # shutdown signal
                break
            try:
                with self._lock:
                    if self._sink is None:
                        self._sink = self._default_sink("logs")
                    sink = self._sink
                sink.write(record)
            except Exception:
                pass                    # never let the drain thread die

    def shutdown(self, timeout: float = 5.0) -> None:
        """Flush remaining records and stop the drain thread."""
        self._queue.put(None)
        self._thread.join(timeout=timeout)
        with self._lock:
            if self._sink:
                self._sink.flush()
                self._sink.close()
            self._sink = None  # allow configure() to accept a fresh sink on restart


# ---------------------------------------------------------------------------
# Module-level API
# ---------------------------------------------------------------------------

_engine = _Engine()


def configure(
    sink: Sink | None = None,
    min_level: Level | str = Level.INFO,
    log_dir: str = "logs",
) -> None:
    """
    Configure the global engine.  Call once at application startup.

    If not called, defaults are::

        LOG_SINK=file  → FileSink writing to LOG_DIR (default: "logs/")
        LOG_SINK=stdout → StdoutSink (for Docker)
        LOG_LEVEL=INFO  → minimum level
    """
    _engine.configure(sink=sink, min_level=min_level, log_dir=log_dir)


def get_logger(component: str) -> Logger:
    """Return a structured logger bound to the given component name."""
    return _engine.get_logger(component)


def shutdown() -> None:
    """Drain queue, flush, and close sinks.  Safe to call at process exit."""
    _engine.shutdown()
