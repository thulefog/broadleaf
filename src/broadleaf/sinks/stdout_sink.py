import json
import sys
from threading import Lock
from typing import Any

from .base import Sink


class StdoutSink(Sink):
    """
    Write JSONL to stdout — one record per line.

    Intended for Docker / Kubernetes where the container runtime or a log
    driver (awslogs, gcplogs, fluentd) picks up stdout and forwards it to
    CloudWatch, Cloud Logging, or an aggregator.  No file I/O, no rotation.
    """

    def __init__(self) -> None:
        self._lock = Lock()

    def write(self, record: dict[str, Any]) -> None:
        line = json.dumps(record, default=str)
        with self._lock:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
