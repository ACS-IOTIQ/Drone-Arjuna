import asyncio
from app.database import engine
from sqlalchemy import text

async def check():
    async with engine.connect() as conn:
        try:
            r = await conn.execute(text("SELECT version_num FROM alembic_version"))
            print("alembic_version:", r.fetchall())
        except Exception as e:
            print("alembic_version missing:", e)

        r = await conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'drone_instances' ORDER BY ordinal_position"
        ))
        print("drone_instances columns:", [row[0] for row in r.fetchall()])

        r = await conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'missions' ORDER BY ordinal_position"
        ))
        print("missions columns:", [row[0] for row in r.fetchall()])

asyncio.run(check())
