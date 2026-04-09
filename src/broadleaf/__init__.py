"""
broadleaf — structured JSONL logging for Substrates projects.

    BroadLeaf: a nod to the log. The Baobab is the logo.

Quick start::

    from broadleaf import get_logger

    log = get_logger("mycomponent")
    log.info("started", version="0.1.0")
    log.warn("high_latency", latency_ms=310.5)

    # Bind shared context for a sub-operation
    batch_log = log.bind(batch_id="abc123", weights="v1.pt")
    batch_log.info("predict", prediction="shake", confidence=0.73)

Read side::

    from broadleaf import LogReader

    reader = LogReader("logs/")
    for rec in reader.query(component="mycomponent", level="WARN"):
        print(rec)

Cloud / Docker — set environment variables, no code changes::

    LOG_SINK=stdout    # → StdoutSink (picked up by awslogs / gcplogs)
    LOG_SINK=file      # → FileSink (default)
    LOG_DIR=/app/logs  # override log directory
    LOG_LEVEL=DEBUG    # override minimum level
"""

from .level import Level
from .logger import Logger, configure, get_logger, shutdown
from .reader import LogReader
from .sinks.base import Sink
from .sinks.file_sink import FileSink
from .sinks.stdout_sink import StdoutSink

__all__ = [
    "Level",
    "Logger",
    "configure",
    "get_logger",
    "shutdown",
    "LogReader",
    "Sink",
    "FileSink",
    "StdoutSink",
]

__version__ = "0.1.0"
