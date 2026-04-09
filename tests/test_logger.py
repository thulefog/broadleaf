"""Basic smoke tests for broadleaf core."""

import json
import tempfile
import time
from pathlib import Path

import pytest

from broadleaf import Level, LogReader, configure, get_logger, shutdown
from broadleaf.sinks.file_sink import FileSink


@pytest.fixture
def tmp_log_dir(tmp_path):
    sink = FileSink(log_dir=tmp_path)
    configure(sink=sink, min_level=Level.TRACE)
    yield tmp_path
    shutdown()


def _flush(tmp_log_dir: Path) -> list[dict]:
    time.sleep(0.05)  # let drain thread catch up
    records = []
    for f in tmp_log_dir.glob("*_broadleaf.jsonl"):
        for line in f.read_text().splitlines():
            if line.strip():
                records.append(json.loads(line))
    return records


# ------------------------------------------------------------------ #

def test_basic_emit(tmp_log_dir):
    log = get_logger("test")
    log.info("ping", msg="hello", value=42)
    recs = _flush(tmp_log_dir)
    assert any(r["event"] == "ping" and r["value"] == 42 for r in recs)


def test_level_filter(tmp_log_dir):
    configure(min_level=Level.WARN)
    log = get_logger("test")
    log.debug("quiet")
    log.warn("loud", note="should appear")
    recs = _flush(tmp_log_dir)
    assert not any(r["event"] == "quiet" for r in recs)
    assert any(r["event"] == "loud" for r in recs)


def test_bind_context(tmp_log_dir):
    log = get_logger("inference").bind(batch_id="abc123", weights="v1.pt")
    log.info("predict", prediction="shake")
    recs = _flush(tmp_log_dir)
    r = next(r for r in recs if r["event"] == "predict")
    assert r["batch_id"] == "abc123"
    assert r["weights"] == "v1.pt"
    assert r["prediction"] == "shake"


def test_reader_component_filter(tmp_log_dir):
    get_logger("receiver").info("batch_received", count=10)
    get_logger("inference").info("predict", prediction="no_shake")
    time.sleep(0.05)
    reader = LogReader(tmp_log_dir)
    results = list(reader.query(component="inference"))
    assert all(r["component"] == "inference" for r in results)
    assert len(results) == 1


def test_reader_level_filter(tmp_log_dir):
    log = get_logger("train")
    log.info("epoch_end", epoch=1)
    log.warn("overfit", epoch=2)
    time.sleep(0.05)
    reader = LogReader(tmp_log_dir)
    warn_only = list(reader.query(component="train", level="WARN"))
    assert all(r["level"] == "WARN" for r in warn_only)


def test_reader_search(tmp_log_dir):
    get_logger("receiver").info("batch_received", batch_id="deadbeef42")
    get_logger("receiver").info("batch_received", batch_id="cafebabe99")
    time.sleep(0.05)
    reader = LogReader(tmp_log_dir)
    results = list(reader.query(search="deadbeef42"))
    assert len(results) == 1
    assert results[0]["batch_id"] == "deadbeef42"


def test_reader_limit(tmp_log_dir):
    log = get_logger("bulk")
    for i in range(20):
        log.info("item", index=i)
    time.sleep(0.05)
    reader = LogReader(tmp_log_dir)
    results = list(reader.query(component="bulk", limit=5))
    assert len(results) == 5
