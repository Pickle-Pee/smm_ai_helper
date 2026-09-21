"""Cheap readiness over production composition and the durable truth store."""
import asyncio
import logging

from sqlalchemy import text

log = logging.getLogger(__name__)


async def readiness(api):
    if api is None:
        return False
    try:
        async with asyncio.timeout(3), api.sessions() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        log.warning("Readiness unavailable error_type=%s", type(exc).__name__)
        return False
