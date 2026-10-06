"""Exact owned evidence survives independent database/API lifetimes."""
import asyncio
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models import OwnedProductSnapshotRecord, User
from app.product_context.snapshot_store import OwnedSnapshotStore
from tests.postgresql_support import mvp_database
from tests.test_product_context import OWN, acquisition


def test_snapshot_roundtrip_immutable_binding_corruption_and_user_cascade(mvp_database):
    snapshot = acquisition()[0].snapshot
    async def check():
        actor = int(uuid.uuid4().hex[:12], 16)
        key = uuid.uuid4().hex
        engine = create_async_engine(mvp_database.kw["bind"].url, poolclass=NullPool)
        restarted_sessions = async_sessionmaker(engine, expire_on_commit=False)
        owner = None
        try:
            async with mvp_database() as session, session.begin():
                user = User(telegram_id=actor)
                session.add(user)
                await session.flush()
                owner = user.id
            store = OwnedSnapshotStore(mvp_database)
            await store.save(owner, key, snapshot)
            await store.save(owner, key, snapshot)
            # Same identity cannot overwrite the evidence already shown.
            await store.save(owner, key, snapshot.model_copy(update={"unknowns": ("Changed evidence",)}))
            restored = OwnedSnapshotStore(restarted_sessions)
            assert await restored.load(owner, key, snapshot.snapshot_id, OWN) == snapshot
            for binding in [(owner + 1, key, snapshot.snapshot_id, OWN),
                            (owner, key + "x", snapshot.snapshot_id, OWN),
                            (owner, key, "snapshot.missing", OWN),
                            (owner, key, snapshot.snapshot_id, "https://other.example")]:
                assert await restored.load(*binding) is None
            async with mvp_database() as session, session.begin():
                records = (await session.scalars(select(OwnedProductSnapshotRecord).where(
                    OwnedProductSnapshotRecord.owner_id == owner))).all()
                assert len(records) == 1 and records[0].created_at is not None
                records[0].snapshot_json = {"schema_version": "invalid"}
            assert await restored.load(owner, key, snapshot.snapshot_id, OWN) is None
            async with mvp_database() as session, session.begin():
                await session.execute(delete(User).where(User.id == owner))
            async with restarted_sessions() as session:
                assert not (await session.scalars(select(OwnedProductSnapshotRecord).where(
                    OwnedProductSnapshotRecord.owner_id == owner))).all()
        finally:
            if owner is not None:
                async with mvp_database() as session, session.begin():
                    await session.execute(delete(User).where(User.id == owner))
            await engine.dispose()
    asyncio.run(check())
