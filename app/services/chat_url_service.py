from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.url_analyzer import UrlAnalysisResult, UrlAnalyzer, extract_urls


@dataclass(frozen=True)
class ChatUrlContext:
    data: UrlAnalysisResult | None
    used_url: bool
    has_url_intent: bool


class ChatUrlService:
    """Builds URL context for chat messages."""

    def __init__(self, db_session: AsyncSession) -> None:
        self.db_session = db_session

    async def analyze(self, text: str) -> ChatUrlContext:
        url_analyzer = UrlAnalyzer(self.db_session)
        url_data = await url_analyzer.analyze(text)
        return ChatUrlContext(
            data=url_data,
            used_url=url_data is not None,
            has_url_intent=bool(extract_urls(text)),
        )
