<div align="center">
  <img src="statics/baobab-broadleaf.PNG" width="120" alt="BroadLeaf logo — baobab tree"/>
  <h1>BroadLeaf</h1>
  <p><em>Structured JSONL Logging</em></p>
</div>

---

## ABSTRACT

The **BroadLeaf** library is a lightweight structured logging library for Python services and pipelines. Every log call produces a single, self-contained JSON Lines record. No external dependencies. Async drain thread so callers never wait on I/O.

Implemented as local in first dry runs, but scaffolding in place for sinks in the cloudy.

```jsonl
{"ts":"2026-04-09T11:04:22.103Z","level":"INFO","component":"receiver","event":"batch_received","batch_id":"abc123","sample_count":864}
{"ts":"2026-04-09T11:04:22.218Z","level":"INFO","component":"inference","event":"predict","prediction":"shake","confidence":0.71,"latency_ms":12.4,"batch_id":"abc123","weights":"v1.pt"}
```
---

## Installation

```bash
# editable install (from within a uv project)
uv add --editable /path/to/broadleaf

# or as a path dependency in pyproject.toml
[tool.uv.sources]
broadleaf = { path = "/path/to/broadleaf", editable = true }
```

Dev dependencies (tests only):

```bash
uv sync --extra dev
```

---

## Basic Wiring

```python
from broadleaf import get_logger, configure, Level
from broadleaf.sinks.file_sink import FileSink

# Optional: call once at startup to set sink and minimum level.
# If omitted, defaults are read from LOG_SINK / LOG_LEVEL / LOG_DIR env vars.
configure(sink=FileSink(log_dir="logs"), min_level=Level.INFO)

log = get_logger("receiver")
log.info("batch_received", batch_id="abc123", sample_count=864)
log.warn("queue_pressure", depth=8200, capacity=10000)
log.error("write_failed", path="/data/batches/abc123.json", reason="disk full")
```

`get_logger()` can be called before `configure()` — the sink is lazily initialized on the first record that drains. Subsequent `configure()` calls propagate immediately to all existing loggers.

---

## Levels

```python
from broadleaf import Level

log.trace("raw_frame", frame_id=7)          # development detail
log.debug("tensor_shape", shape=[1, 9, 128])
log.info("epoch_end", epoch=5, loss=0.31)
log.warn("low_confidence", score=0.42)
log.error("inference_failed", batch_id="xyz")
log.fatal("engine_unrecoverable", reason="OOM")
```

Levels in order: `TRACE(0)` < `DEBUG(10)` < `INFO(20)` < `WARN(30)` < `ERROR(40)` < `FATAL(50)`.

---

## Bound Context

`bind()` returns a child logger that stamps every subsequent record with fixed fields. Original logger is unchanged.

```python
run_log = get_logger("train").bind(run_id="r42", config_hash="deadbeef")
run_log.info("epoch_end", epoch=5, loss=0.31)
run_log.info("epoch_end", epoch=6, loss=0.28)
# both records carry run_id and config_hash automatically
```

Useful for request-scoped context, batch IDs, model version tags — anything that should appear on every record within a logical scope without repeating it at every call site.

---

## Sinks

### FileSink — daily-rotating JSONL files

```python
from broadleaf.sinks.file_sink import FileSink

configure(sink=FileSink(log_dir="logs"))
# writes: logs/20260409_broadleaf.jsonl
# rolls:  logs/20260409_143022_broadleaf.jsonl  (when file exceeds 50 MB)
```

Files are named `{YYYYMMDD}_broadleaf.jsonl` — date-first so directory listings sort chronologically. The `broadleaf` segment is a stable marker; it can be replaced with a service name to differentiate log streams in future.

### StdoutSink — Docker / cloud log collectors

```python
from broadleaf.sinks.stdout_sink import StdoutSink

configure(sink=StdoutSink())
# or: LOG_SINK=stdout (no code change needed)
```

Writes one JSON line per record to stdout. Compatible with `awslogs`, `gcplogs`, Datadog, and any collector that reads container stdout.

### Environment Variable Overrides

| Variable | Default | Effect |
|----------|---------|--------|
| `LOG_SINK` | `file` | `file` or `stdout` |
| `LOG_DIR` | `logs` | directory for FileSink |
| `LOG_LEVEL` | `INFO` | minimum level name |

---

## Reading Logs

`LogReader` streams JSONL records without loading full files into memory. All filters are additive (AND).

```python
from broadleaf import LogReader
from datetime import datetime, timedelta, timezone

reader = LogReader("logs/")

# All inference predictions for a specific batch
for rec in reader.query(component="inference", search="abc123"):
    print(rec["prediction"], rec["confidence"])

# Warnings and above from training, last hour
since = datetime.now(timezone.utc) - timedelta(hours=1)
for rec in reader.query(component="train", level="WARN", since=since):
    print(rec)

# Collect into a list — pass limit=None for unbounded
results = list(reader.query(component="receiver", event="batch_received", limit=50))

# Quick tail inspection
recent = reader.tail(n=20, component="inference")
```

### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `component` | `str` | Prefix match — `"inference"` matches `"inference"` and `"inference.embed"` |
| `level` | `str` | Minimum level — `"WARN"` returns WARN, ERROR, FATAL |
| `event` | `str` | Exact match on the `event` field |
| `search` | `str` | Case-insensitive substring across the full JSON line |
| `since` | `datetime` | Records at or after this timestamp |
| `until` | `datetime` | Records at or before this timestamp |
| `limit` | `int` | Stop after N matches (default 500; `None` = all) |

---

## Record Schema

Every JSONL record has these top-level fields:

```jsonl
{
  "ts":        "2026-04-09T11:04:22.103456Z",  // ISO-8601 UTC
  "level":     "INFO",
  "component": "receiver",
  "event":     "batch_received",               // machine-readable, snake_case
  "msg":       "",                             // optional human-readable note
  "batch_id":  "abc123",                       // ...arbitrary fields merged in
  "count":     864
}
```

`event` is the primary machine-readable identifier. `msg` is optional free text for human notes. All keyword arguments passed to the log call are merged into the top-level record.

---

## Structured over Formatted

BroadLeaf records are designed to be queried, not read. Each call should be a single self-contained event:

```python
# good — one record, one event, queryable fields
log.info("export_options_available", formats=["coreml", "onnx", "swift_wrapper"])

# avoid — several records for one moment, no queryable structure
log.info("Export options:")
log.info("  - CoreML")
log.info("  - ONNX")
```

If content is developer-facing output rather than an operational event, use `print()`.

---

## Graceful Shutdown

```python
from broadleaf import shutdown

# Drains queue, flushes, and closes the sink.
# Safe to call at process exit; configure() can restart the engine afterward.
shutdown()
```

---

## Running Tests

```bash
uv sync --extra dev
uv run pytest tests/ -v
```

---

## Project Layout

```
broadleaf/
├── src/broadleaf/
│   ├── __init__.py          # public API
│   ├── level.py             # Level(IntEnum)
│   ├── record.py            # LogRecord dataclass
│   ├── logger.py            # Logger, _Engine singleton
│   ├── reader.py            # LogReader streaming query
│   └── sinks/
│       ├── base.py          # Sink ABC
│       ├── file_sink.py     # daily-rotating JSONL
│       └── stdout_sink.py   # Docker / cloud stdout
├── tests/
│   └── test_logger.py
└── pyproject.toml
```

#### APPENDIX

This project was designed as a purpose built level up logger library to enable a more modern, durable approach to log traces - still enabling fine grain meta data content control. 

Initial bring up was related to building out inference pathways in the areas of fine tuning model implementations plus follow up passes and iterations to test and train - including key steps like determinations of weights as downstream model inputs.

- Library Name

NOTE: On inception, was interested to call the library _Baobab_ to mix it beyond the usual reference to a *log* and instead shift into the broader set of *tree* terms. With *baobab*, pronunciation questions surfaced right away. The compromise was **BroadLeaf**, the category of deciduous trees in which the _Baobab_ tree resides. This name fits, as there is a lot of data carried in the unique trunk but the branches and leaf structures are not just interesting but key as well.

/jmw