"""
Last-resort restore source: plain `pg_dump` COPY-format .sql files.

The normal restore path reads the JSON dumps the app writes itself (local disk +
MinIO). If those are gone too (e.g. every Docker volume was recreated) the
project's `database_dumps/` folder is the only copy left, so `backup.py` falls
back to the best .sql file found there.

Safeguards:
  * Only ONE dump is used per restore (the one with the most rows, newest on a
    tie), so tables are never mixed from dumps of different dates (FK safety).
  * A dump is applied at most once per backup volume — recorded in a marker file
    next to the JSON dumps — so rows an operator deliberately deleted later are
    not resurrected from a stale file. A wiped backup volume wipes the marker,
    which is exactly the situation the fallback exists for.
  * Files over `MAX_SQL_DUMP_BYTES` are skipped (e.g. the telemetry history dump).
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import structlog
from sqlalchemy import Boolean, Float, Integer, JSON, Numeric

from app.config import get_settings

log = structlog.get_logger()
cfg = get_settings()

MAX_SQL_DUMP_BYTES = 64 * 1024 * 1024
MARKER_NAME = "sql_fallback_applied.json"
_IGNORED_TABLES = {"alembic_version"}

_UNESCAPE = {"t": "\t", "n": "\n", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "\\": "\\"}


def _unescape(raw: str) -> str:
    """Undo pg_dump COPY text-format backslash escapes."""
    if "\\" not in raw:
        return raw
    out, i = [], 0
    while i < len(raw):
        ch = raw[i]
        if ch == "\\" and i + 1 < len(raw):
            out.append(_UNESCAPE.get(raw[i + 1], raw[i + 1]))
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _coerce(raw: str, column_type):
    if isinstance(column_type, Boolean):
        return raw == "t"
    if isinstance(column_type, Integer):
        return int(raw)
    if isinstance(column_type, (Float, Numeric)):
        return float(raw)
    raw = _unescape(raw)
    if isinstance(column_type, JSON):
        # pg_dump writes a JSON column's stored value as its literal text,
        # e.g. the bare word `null` for a JSON null, or `{...}` for an object.
        return json.loads(raw)
    return raw


def parse_sql_dump(sql_path: Path, tables_by_name: dict) -> dict[str, list[dict]]:
    """Parse the COPY blocks of a pg_dump file into {table: [row dicts]}.

    Only tables present in `tables_by_name` are kept, and columns the current
    model no longer has are dropped, so an older dump still loads.
    """
    data: dict[str, list[dict]] = {}
    table = None
    columns: list[str] = []
    rows: list[dict] = []
    with sql_path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if table is None:
                if not line.startswith("COPY public."):
                    continue
                # COPY public.<table> (<col1>, <col2>, ...) FROM stdin;
                header = line[len("COPY public."):]
                name, rest = header.split(" ", 1)
                table = tables_by_name.get(name.strip('"'))
                columns = [c.strip().strip('"') for c in rest[rest.index("(") + 1: rest.index(")")].split(",")]
                rows = []
                continue
            if line == r"\.":
                if table is not None and table.name not in _IGNORED_TABLES:
                    data[table.name] = rows
                table = None
                continue
            if table is None:
                continue
            row = {}
            for col, val in zip(columns, line.split("\t")):
                if col not in table.columns:
                    continue
                row[col] = None if val == r"\N" else _coerce(val, table.columns[col].type)
            rows.append(row)
    return data


def _dump_key(path: Path) -> str:
    st = path.stat()
    return f"{path.name}:{st.st_size}:{int(st.st_mtime)}"


def _read_marker(backup_dir: Path) -> dict:
    try:
        return json.loads((backup_dir / MARKER_NAME).read_text())
    except (OSError, ValueError):
        return {}


def mark_applied(backup_dir: Path, dump_name: str) -> None:
    """Record that a dump (named as returned by `load_best`) was restored."""
    marker = _read_marker(backup_dir)
    marker[dump_name] = datetime.now(timezone.utc).isoformat()
    backup_dir.mkdir(parents=True, exist_ok=True)
    (backup_dir / MARKER_NAME).write_text(json.dumps(marker, indent=2))


def _candidates(target_name: str) -> list[Path]:
    directory = Path(cfg.backup_sql_dump_dir)
    if not directory.is_dir():
        return []
    files = []
    for p in directory.glob("*.sql"):
        is_telemetry = "telemetry" in p.name.lower()
        if (target_name == "telemetry") != is_telemetry:
            continue
        if p.stat().st_size > MAX_SQL_DUMP_BYTES:
            log.info("SQL dump skipped (too large)", file=p.name, bytes=p.stat().st_size)
            continue
        files.append(p)
    return files


def load_best(target_name: str, backup_dir: Path, tables_by_name: dict) -> tuple[str, dict] | None:
    """
    Return (name, data) for the best not-yet-applied SQL dump for this database,
    or None. `name` is `sql:<key>` so it can be told apart from JSON dumps; pass
    it to `mark_applied` once rows from it were actually restored.
    """
    marker = _read_marker(backup_dir)
    best = None  # (rows, mtime, name, data)
    for path in _candidates(target_name):
        name = f"sql:{_dump_key(path)}"
        if name in marker:
            continue
        try:
            data = parse_sql_dump(path, tables_by_name)
        except Exception as e:
            log.error("SQL dump could not be parsed — skipped", file=path.name, error=str(e))
            continue
        total = sum(len(rows) for rows in data.values())
        if total == 0:
            continue
        score = (total, path.stat().st_mtime)
        if best is None or score > best[:2]:
            best = (*score, name, data)
    if best is None:
        return None
    log.info("SQL dump fallback available", db=target_name, file=best[2], rows=best[0])
    return best[2], best[3]
