"""PostgreSQL owns revision identity, immutable race winners and restart recovery."""
import asyncio
import uuid

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models import InterpretedRequestRecord, User
from app.marketing_copilot.contracts import CopilotContractError, IntentKind
from app.marketing_copilot.interpretation_store import InterpretationStore
from tests.postgresql_support import mvp_database
from tests.test_interpretation_store import MESSAGE, interpretation


def test_restart_revisions_owners_race_and_corruption(mvp_database):
    async def check():
        owners = []
        engine = create_async_engine(mvp_database.kw["bind"].url, poolclass=NullPool)
        restarted = async_sessionmaker(engine, expire_on_commit=False)
        key = uuid.uuid4().hex
        try:
            async with mvp_database() as session, session.begin():
                for _ in range(2):
                    user = User(telegram_id=int(uuid.uuid4().hex[:12], 16))
                    session.add(user)
                    await session.flush()
                    owners.append(user.id)
            store = InterpretationStore(mvp_database)
            assert await store.load(owners[0], key, MESSAGE) is None
            first, second = interpretation(), interpretation(IntentKind.POSITIONING)
            winners = await asyncio.gather(
                store.save(owners[0], key, MESSAGE, first),
                store.save(owners[0], key, MESSAGE, second),
            )
            assert winners[0] == winners[1]
            restored = InterpretationStore(restarted)
            assert await restored.load(owners[0], key, MESSAGE) == winners[0]
            assert await restored.load(owners[1], key, MESSAGE) is None
            assert await restored.load(owners[0], key, MESSAGE + " revised") is None
            assert await store.save(owners[0], key, MESSAGE + " revised", second) == second
            assert await restored.load(owners[0], key, MESSAGE) == winners[0]
            assert await store.save(owners[1], key, MESSAGE, second) == second
            async with mvp_database() as session, session.begin():
                rows = (await session.scalars(select(InterpretedRequestRecord).where(
                    InterpretedRequestRecord.owner_id.in_(owners)))).all()
                assert len(rows) == 3 and all(row.created_at is not None for row in rows)
                await session.execute(update(InterpretedRequestRecord).where(
                    InterpretedRequestRecord.owner_id == owners[0]).values(interpretation_json={"invalid": True}))
            with pytest.raises(CopilotContractError):
                await restored.load(owners[0], key, MESSAGE)
            with pytest.raises(CopilotContractError):
                await store.save(owners[0], key, MESSAGE, first)
        finally:
            async with mvp_database() as session, session.begin():
                await session.execute(delete(User).where(User.id.in_(owners)))
            await engine.dispose()
    asyncio.run(check())
