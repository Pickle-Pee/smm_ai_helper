"""Durable authority for the exact evidence presented for confirmation."""
import json

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.models import OwnedProductSnapshotRecord
from .contracts import OwnedProductSnapshot


class OwnedSnapshotStore:
    def __init__(self, sessions):
        self.sessions = sessions

    async def save(self, owner, request_key, snapshot):
        snapshot = OwnedProductSnapshot.model_validate(snapshot)
        async with self.sessions() as session, session.begin():
            # Never overwrite evidence which a caller may already be reviewing.
            await session.execute(insert(OwnedProductSnapshotRecord).values(
                owner_id=owner, request_key=request_key, snapshot_id=snapshot.snapshot_id,
                owned_site_url=snapshot.owned_site_url, snapshot_json=snapshot.model_dump(mode="json")
            ).on_conflict_do_nothing())

    async def load(self, owner, request_key, snapshot_id, owned_site_url):
        async with self.sessions() as session:
            raw = await session.scalar(select(OwnedProductSnapshotRecord.snapshot_json).where(
                OwnedProductSnapshotRecord.owner_id == owner,
                OwnedProductSnapshotRecord.request_key == request_key,
                OwnedProductSnapshotRecord.snapshot_id == snapshot_id,
                OwnedProductSnapshotRecord.owned_site_url == owned_site_url))
        if raw is None:
            return None
        try:
            snapshot = OwnedProductSnapshot.model_validate_json(json.dumps(raw))
        except (ValidationError, ValueError, TypeError):
            return None
        if snapshot.snapshot_id != snapshot_id or snapshot.owned_site_url != owned_site_url:
            return None
        return snapshot
