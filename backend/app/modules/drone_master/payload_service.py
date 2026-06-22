import structlog
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.payload import PayloadType
from app.schemas.payload import PayloadTypeCreate, PayloadTypeUpdate

log = structlog.get_logger()


class PayloadTypeService:

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_all(self) -> list[PayloadType]:
        result = await self.db.execute(
            select(PayloadType).order_by(PayloadType.name)
        )
        return result.scalars().all()

    async def get_by_id(self, pt_id: int) -> PayloadType:
        pt = await self.db.get(PayloadType, pt_id)
        if not pt:
            raise HTTPException(404, f"Payload type #{pt_id} not found")
        return pt

    async def create(self, body: PayloadTypeCreate) -> PayloadType:
        existing = await self.db.execute(
            select(PayloadType).where(PayloadType.name == body.name)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(409, f"Payload type '{body.name}' already exists")
        pt = PayloadType(**body.model_dump())
        self.db.add(pt)
        await self.db.flush()
        await self.db.refresh(pt)
        log.info("payload_type.created", id=pt.id, name=pt.name)
        return pt

    async def update(self, pt_id: int, body: PayloadTypeUpdate) -> PayloadType:
        pt = await self.get_by_id(pt_id)
        for field, value in body.model_dump(exclude_unset=True).items():
            setattr(pt, field, value)
        await self.db.flush()
        await self.db.refresh(pt)
        return pt

    async def delete(self, pt_id: int) -> None:
        pt = await self.get_by_id(pt_id)
        # Block deletion if payloads still reference this type
        result = await self.db.execute(
            select(Payload).where(Payload.payload_type_id == pt_id)
        )
        if result.scalar_one_or_none():
            raise HTTPException(
                409, f"Cannot delete payload type #{pt_id} — payloads still reference it"
            )
        await self.db.delete(pt)
        log.info("payload_type.deleted", id=pt_id)


