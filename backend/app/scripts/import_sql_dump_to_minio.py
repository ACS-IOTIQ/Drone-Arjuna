"""
Manual import of a pg_dump COPY-format .sql file (from database_dumps/):
convert it into the JSON shape app.core.backup.create_dump() produces, upload it
to MinIO as the newest dump, then restore it into any currently-empty tables.

The app now does this automatically when every other backup is gone (see
app/core/sql_dump_loader.py); use this script to force a specific file.

Usage (inside the backend container, where boto3 + config are available):
    python -m app.scripts.import_sql_dump_to_minio /project/database_dumps/dronearjuna_dump.sql
"""
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.core import backup, sql_dump_loader


async def main(sql_path_str: str):
    target = backup.MAIN_TARGET
    data = sql_dump_loader.parse_sql_dump(
        Path(sql_path_str), {t.name: t for t in target.sorted_tables()}
    )

    non_empty = {k: len(v) for k, v in data.items() if v}
    print("Parsed tables with rows:", non_empty)

    target.backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dump_name = f"dump_{stamp}.json"
    dump_path = target.backup_dir / dump_name
    dump_path.write_text(backup._pack_dump(data))
    print("Wrote", dump_path)

    backup._upload_to_minio(target, dump_path, dump_name)
    print("Uploaded to MinIO as", dump_name)

    restored = await backup.restore_latest_dump(target)
    print("Restore result:", restored)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
