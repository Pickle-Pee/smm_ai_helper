"""Run python -m app.web_auth_cleanup from the backend maintenance scheduler."""
import asyncio

from app.db import AsyncSessionLocal
from app.services.web_auth import cleanup


async def main():
    async with AsyncSessionLocal.begin() as db:
        await cleanup(db)


if __name__ == "__main__":
    asyncio.run(main())
