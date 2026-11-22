import asyncio
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from app.models import EmailCredential, ExternalIdentity, User
from app.services.email_identity import normalize_email
from app.services.identity_service import IdentityService
from tests.postgresql_support import mvp_database

FIXTURE_PHC = "$argon2id$v=19$m=65536,t=3,p=1$Zml4dHVyZS1zYWx0$c2NoZW1hLW9ubHk"


def test_only_verified_email_can_own_password_and_telegram_id_stays_immutable(mvp_database):
    async def run():
        email = f"auth-scope-{uuid.uuid4().hex}@example.test"
        other_email = f"other-{email}"
        actor = uuid.uuid4().int >> 80
        async with mvp_database.begin() as db:
            web = User(telegram_id=None)
            telegram = User(telegram_id=actor)
            db.add_all([web, telegram])
            await db.flush()
            web_id, telegram_id = web.id, telegram.id
        try:
            for provider, subject in [("email", email), ("telegram", str(actor))]:
                async with mvp_database.begin() as db:
                    with pytest.raises(IntegrityError):
                        async with db.begin_nested():
                            db.add(EmailCredential(email=subject, identity_provider=provider, password_hash=FIXTURE_PHC))
                            await db.flush()

            async with mvp_database.begin() as db:
                db.add(ExternalIdentity(
                    user_id=web_id, provider="email", subject=email, verified_at=datetime.now(timezone.utc),
                ))
                await db.flush()
                with pytest.raises(IntegrityError):
                    async with db.begin_nested():
                        db.add(EmailCredential(email=email, password_hash="plaintext"))
                        await db.flush()
                db.add(EmailCredential(email=email, password_hash=FIXTURE_PHC))
            async with mvp_database.begin() as db:
                assert await IdentityService.resolve_user_id(db, "email", email) == web_id
                assert await IdentityService.resolve_telegram_user_id(db, actor) == telegram_id
                assert (await db.get(EmailCredential, email)).password_hash == FIXTURE_PHC
                assert (await db.get(User, web_id)).telegram_id is None
                with pytest.raises(IntegrityError):
                    async with db.begin_nested():
                        db.add(ExternalIdentity(
                            user_id=web_id, provider="email", subject=other_email,
                            verified_at=datetime.now(timezone.utc),
                        ))
                        await db.flush()
                with pytest.raises(IntegrityError):
                    async with db.begin_nested():
                        await db.execute(update(User).where(User.id == telegram_id).values(telegram_id=actor + 1))
        finally:
            async with mvp_database.begin() as db:
                await db.execute(delete(User).where(User.id.in_([web_id, telegram_id])))

    asyncio.run(run())


def test_same_normalized_email_never_commits_for_two_users(mvp_database):
    async def run():
        email = f"auth-race-{uuid.uuid4().hex}@example.test"

        async def register(address):
            try:
                async with mvp_database.begin() as db:
                    user = User(telegram_id=None)
                    db.add(user)
                    await db.flush()
                    db.add(ExternalIdentity(
                        user_id=user.id, provider="email", subject=normalize_email(address),
                        verified_at=datetime.now(timezone.utc),
                    ))
                    await db.flush()
                    return user.id
            except IntegrityError:
                return None

        owners = await asyncio.gather(register(email.upper()), register(email))
        try:
            winners = [owner for owner in owners if owner is not None]
            assert len(winners) == 1
            async with mvp_database.begin() as db:
                assert await IdentityService.resolve_user_id(db, "email", email) == winners[0]
                with pytest.raises(IntegrityError):
                    async with db.begin_nested():
                        db.add(ExternalIdentity(
                            user_id=winners[0], provider="email", subject=email.upper(),
                            verified_at=datetime.now(timezone.utc),
                        ))
                        await db.flush()
        finally:
            async with mvp_database.begin() as db:
                ids = select(ExternalIdentity.user_id).where(ExternalIdentity.provider == "email", ExternalIdentity.subject == email)
                await db.execute(delete(User).where(User.id.in_(ids)))

    asyncio.run(run())
