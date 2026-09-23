import asyncio
from app.database import AsyncSessionLocal, Base
from sqlalchemy import text

async def main():
    async with AsyncSessionLocal() as db:
        for table in Base.metadata.sorted_tables:
            count = (await db.execute(text(f'SELECT COUNT(*) FROM "{table.name}"'))).scalar_one()
            print(table.name, count)

asyncio.run(main())
