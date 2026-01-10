from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List

import httpx
import asyncio
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.llm.openai_text import chat as openai_chat
from app.models import UrlCache
from app.agents.utils import safe_json_parse


logger = logging.getLogger(__name__)

URL_REGEX = re.compile(r"(https?://[^\s]+)")
MAX_TEXT_CHARS = 60000
DEFAULT_TTL_HOURS = 24


@dataclass
class UrlSummary:
    url: str
    title: str
    extracted_text: str
    url_summary: Dict[str, Any]


def extract_urls(text: str) -> List[str]:
    urls = URL_REGEX.findall(text or "")
    return [u.rstrip(").,") for u in urls]


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class DbUrlCacheStore:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, url: str) -> UrlSummary | None:
        result = await self.session.execute(
            select(UrlCache).where(UrlCache.url == url, UrlCache.expires_at > datetime.utcnow())
        )
        cached = result.scalar_one_or_none()
        if not cached or not cached.summary_json:
            return None
        return UrlSummary(
            url=cached.url,
            title=cached.summary_json.get("title", ""),
            extracted_text=cached.summary_json.get("extracted_text", ""),
            url_summary=cached.summary_json.get("url_summary", {}),
        )

    async def set(self, url: str, title: str, extracted_text: str, summary: Dict[str, Any]) -> None:
        payload = {
            "title": summary.get("title", title),
            "extracted_text": extracted_text,
            "url_summary": summary,
        }
        cache = UrlCache(
            url=url,
            extracted_text_hash=_hash_text(extracted_text),
            summary_json=payload,
            expires_at=datetime.utcnow() + timedelta(hours=DEFAULT_TTL_HOURS),
        )
        self.session.merge(cache)
        await self.session.commit()


class InMemoryUrlCacheStore:
    def __init__(self) -> None:
        self.storage: Dict[str, tuple[UrlSummary, datetime]] = {}

    async def get(self, url: str) -> UrlSummary | None:
        item = self.storage.get(url)
        if not item:
            return None
        summary, expires = item
        if expires <= datetime.utcnow():
            self.storage.pop(url, None)
            return None
        return summary

    async def set(self, url: str, title: str, extracted_text: str, summary: Dict[str, Any]) -> None:
        expires = datetime.utcnow() + timedelta(hours=DEFAULT_TTL_HOURS)
        payload = UrlSummary(url=url, title=title, extracted_text=extracted_text, url_summary=summary)
        self.storage[url] = (payload, expires)


class UrlAnalyzer:
    def __init__(self, session: AsyncSession | None = None, cache_store: Any | None = None) -> None:
        self.session = session
        if cache_store:
            self.cache_store = cache_store
        elif session:
            self.cache_store = DbUrlCacheStore(session)
        else:
            self.cache_store = None

    async def analyze(self, text: str) -> UrlSummary | None:
        urls = extract_urls(text)
        if not urls:
            return None
        url = urls[0]
        cached = await self._get_cached(url)
        if cached:
            return cached

        extracted = await self._fetch_and_extract(url)
        if not extracted:
            return None
        title, extracted_text = extracted
        url_summary = await self._summarize(url, title, extracted_text)

        await self._set_cache(url, title, extracted_text, url_summary)
        return UrlSummary(
            url=url,
            title=title,
            extracted_text=extracted_text,
            url_summary=url_summary,
        )

    async def _get_cached(self, url: str) -> UrlSummary | None:
        if not self.cache_store:
            return None
        return await self.cache_store.get(url)

    async def _set_cache(
        self, url: str, title: str, extracted_text: str, summary: Dict[str, Any]
    ) -> None:
        if not self.cache_store:
            return
        await self.cache_store.set(url, title, extracted_text, summary)

    async def _fetch_and_extract(self, url: str) -> tuple[str, str] | None:
        headers = {"User-Agent": "SMM-AI-Helper/1.0"}
        timeout = httpx.Timeout(settings.HTTP_TIMEOUT)
        resp = None
        for attempt in range(settings.HTTP_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                    resp = await client.get(url, headers=headers)
                    resp.raise_for_status()
                    break
            except httpx.HTTPError as exc:
                if attempt >= settings.HTTP_RETRIES:
                    logger.warning(
                        "url_fetch_failed",
                        extra={"request_id": "-", "user_id": "-", "error": str(exc)},
                    )
                    return None
                await asyncio.sleep(settings.HTTP_BACKOFF * (2**attempt))
        if resp is None:
            return None

        html = resp.text[: MAX_TEXT_CHARS * 2]
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        title = soup.title.string.strip() if soup.title and soup.title.string else ""
        meta_desc = ""
        meta_tag = soup.find("meta", attrs={"name": "description"})
        if meta_tag and meta_tag.get("content"):
            meta_desc = meta_tag["content"].strip()

        text = soup.get_text(separator=" ")
        clean = " ".join(text.split())
        if meta_desc:
            clean = f"{meta_desc}\n{clean}"
        clean = clean[:MAX_TEXT_CHARS]
        return title, clean

    async def _summarize(self, url: str, title: str, extracted_text: str) -> Dict[str, Any]:
        prompt = f"""
Сделай короткое резюме страницы (2-4 предложения) и ключевые тезисы.

URL: {url}
Title: {title}
Text: {extracted_text[:4000]}

Верни JSON:
{{
  "summary": "...",
  "key_points": ["..."],
  "topics": ["..."]
}}
"""
        messages = [
            {"role": "system", "content": "Ты — помощник по резюмированию веб-страниц. Отвечай JSON."},
            {"role": "user", "content": prompt},
        ]
        content, _usage = await openai_chat(
            messages=messages,
            model=settings.DEFAULT_TEXT_MODEL_LIGHT,
            temperature=0.2,
            max_output_tokens=400,
        )
        try:
            data = safe_json_parse(content)
        except Exception:
            data = {"summary": "", "key_points": [], "topics": []}
        data["title"] = title
        data["url"] = url
        return data
