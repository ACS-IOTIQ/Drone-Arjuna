"""
Verify the audit_log hash chain.

    docker compose exec backend python -m app.scripts.verify_audit_log

Exit code 0 = chain intact, 1 = tampering detected (prints the first bad row id),
2 = could not run. Run it on a schedule and alert on a non-zero exit. Note the
chain proves rows were not edited, removed from the middle or re-ordered; to also
detect truncation of the newest rows, ship events to a write-once store (SIEM)
and compare counts.
"""
import asyncio
import sys

from sqlalchemy import text

from app.core.security import verify_audit_chain
from app.database import AsyncSessionLocal

BATCH = 5000


async def _verify() -> int:
    checked = 0
    last_id = 0
    carry = None            # last row of the previous batch, so links across batches are checked
    async with AsyncSessionLocal() as db:
        while True:
            res = await db.execute(text("""
                SELECT id, timestamp, category, action, user_id, drone_id, mission_id,
                       ip_address, detail, severity, prev_hash, row_hash
                FROM audit_log WHERE id > :last ORDER BY id LIMIT :n
            """), {"last": last_id, "n": BATCH})
            rows = [dict(r) for r in res.mappings()]
            if not rows:
                break
            batch = ([carry] if carry else []) + rows
            bad = verify_audit_chain(batch)
            if bad is not None:
                print(f"TAMPERING DETECTED: first failing audit_log id = {bad}")
                return 1
            checked += len(rows)
            last_id = rows[-1]["id"]
            chained = [r for r in rows if r["row_hash"] is not None]
            carry = chained[-1] if chained else carry
    print(f"audit_log chain intact ({checked} rows checked)")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(_verify()))
    except Exception as exc:        # noqa: BLE001
        print(f"could not verify audit log: {exc}")
        sys.exit(2)
