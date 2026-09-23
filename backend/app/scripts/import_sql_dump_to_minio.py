"""
One-off: parse a plain pg_dump COPY-format .sql file (from database_dumps/)
into the JSON shape app.core.backup.create_dump() produces, upload it to
MinIO's db-backups bucket as the newest dump, then restore it into Postgres.

Usage (inside the backend container, where boto3 + config are available):
    python -m app.scripts.import_sql_dump_to_minio /project/database_dumps/dronearjuna_dump.sql
"""
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import Boolean, Float, Integer, JSON, Numeric

from app.core import backup
from app.database import Base


def _coerce(raw: str, column_type):
    if isinstance(column_type, Boolean):
        return raw == "t"
    if isinstance(column_type, Integer):
        return int(raw)
    if isinstance(column_type, (Float, Numeric)):
        return float(raw)
    if isinstance(column_type, JSON):
        # pg_dump writes a JSON column's stored value as its literal text,
        # e.g. the bare word `null` for a JSON null, or `{...}` for an object.
        return json.loads(raw)
    return raw


def _parse_copy_blocks(sql_path: Path) -> dict:
    tables_by_name = {table.name: table for table in Base.metadata.sorted_tables}

    text = sql_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    data = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("COPY public."):
            # COPY public.<table> (<col1>, <col2>, ...) FROM stdin;
            header = line[len("COPY public."):]
            table_name, rest = header.split(" ", 1)
            cols_str = rest[rest.index("(") + 1: rest.index(")")]
            columns = [c.strip().strip('"') for c in cols_str.split(",")]

            table = tables_by_name.get(table_name)
            column_types = {c.name: c.type for c in table.columns} if table is not None else {}

            rows = []
            i += 1
            while i < len(lines) and lines[i] != r"\.":
                raw = lines[i]
                values = raw.split("\t")
                row = {}
                for col, val in zip(columns, values):
                    if val == r"\N":
                        row[col] = None
                    else:
                        row[col] = _coerce(val, column_types.get(col))
                rows.append(row)
                i += 1
            if table is not None:
                data[table_name] = rows
        i += 1
    return data


async def main(sql_path_str: str):
    sql_path = Path(sql_path_str)
    data = _parse_copy_blocks(sql_path)

    non_empty = {k: len(v) for k, v in data.items() if v}
    print("Parsed tables with rows:", non_empty)

    backup.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dump_name = f"dump_{stamp}.json"
    dump_path = backup.BACKUP_DIR / dump_name
    dump_path.write_text(json.dumps(data, default=backup._json_default, indent=2))
    print("Wrote", dump_path)

    backup._upload_to_minio(dump_path, dump_name)
    print("Uploaded to MinIO as", dump_name)

    restored = await backup.restore_latest_dump()
    print("Restore result:", restored)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
