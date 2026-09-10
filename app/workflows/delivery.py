"""Short transactions for independent Telegram delivery attempts."""
import uuid
from datetime import timedelta

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import aliased

from app.db import AsyncSessionLocal
from app.models import Job, MarketingRun, User, WorkflowDelivery
from app.workflows.service import utcnow


class DeliveryService:
    def __init__(self, sessions=AsyncSessionLocal, clock=utcnow):
        self.sessions, self.clock = sessions, clock

    async def claim(self):
        now = self.clock()
        earlier = aliased(WorkflowDelivery)
        async with self.sessions() as session, session.begin():
            row = await session.scalar(select(WorkflowDelivery).where(
                WorkflowDelivery.status.in_(["pending", "sending"]), WorkflowDelivery.available_at <= now,
                or_(WorkflowDelivery.lease_until.is_(None), WorkflowDelivery.lease_until <= now),
                ~exists(select(earlier.delivery_id).where(earlier.job_id == WorkflowDelivery.job_id,
                    earlier.part < WorkflowDelivery.part, earlier.status != "delivered")),
            ).order_by(WorkflowDelivery.available_at, WorkflowDelivery.delivery_id)
                .with_for_update(skip_locked=True).limit(1))
            if row is None:
                return None
            if row.attempts >= 8:
                row.status, row.error = "failed", "Delivery retry limit reached"
                row.claim_token = row.lease_until = None
                return None
            actor = await session.scalar(select(User.telegram_id)
                .join(MarketingRun, MarketingRun.user_id == User.id)
                .join(Job, Job.marketing_run_id == MarketingRun.run_id).where(Job.job_id == row.job_id))
            if actor is None:
                row.status, row.error = "failed", "Delivery owner missing"
                row.claim_token = row.lease_until = None
                return None
            row.status, row.claim_token = "sending", uuid.uuid4().hex
            row.lease_until = now + timedelta(seconds=90)
            row.attempts += 1
            return {"delivery_id": row.delivery_id, "claim_token": row.claim_token, "telegram_id": actor, "payload": row.payload_json}

    async def acknowledge(self, delivery_id, token, *, message_id=None, retryable=True, retry_after=0):
        async with self.sessions() as session, session.begin():
            row = await session.scalar(select(WorkflowDelivery).where(WorkflowDelivery.delivery_id == delivery_id).with_for_update())
            if row is None or row.claim_token != token or row.lease_until <= self.clock():
                return False
            row.claim_token = row.lease_until = None
            if message_id is not None:
                row.status, row.telegram_message_id, row.error = "delivered", message_id, None
            else:
                row.status = "pending" if retryable and row.attempts < 8 else "failed"
                row.error = "Telegram delivery unavailable"
                row.available_at = self.clock() + timedelta(seconds=max(retry_after, min(300, 5 * 2 ** (row.attempts - 1))))
        return True
