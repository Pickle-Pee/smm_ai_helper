# app/services/url_analyzer.py
from __future__ import annotations

import asyncio
import hashlib
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, urlunparse

import httpx
from selectolax.parser import HTMLParser
from sqlalchemy import delete, select

from app.config import settings
from app.models import UrlCache

URL_RE = re.compile(r"(https?://[^\s\]\)>,\"']+)", re.IGNORECASE)
HANDLE_RE = re.compile(r"(?<!\w)@([a-zA-Z0-9_\.]{3,30})(?!\w)")
WORD_HANDLE_RE = re.compile(
    r"(?i)\b("
    r"instagram|inst|ig|"
    r"инстаграм(?:е|у|ом|а)?|"
    r"инста(?:е|у|ой|а)?|"
    r"инст(?:е|у|ой|а)?|"
    r"telegram|tg|"
    r"телеграм(?:е|у|ом|а)?|"
    r"тг"
    r")\b\s*@?([a-zA-Z0-9_\.]{3,32})\b"
)


def normalize_url(u: str) -> str:
    """
    Приводит URL к каноническому виду для кэша и анализа.
    - убирает fragment
    - для instagram/t.me/vk/tiktok/youtube убирает query (обычно мусор)
    - приводит scheme/host к lower
    - убирает trailing slash (кроме корня)
    """
    if not u:
        return u
    u = u.strip()

    try:
        p = urlparse(u)
        scheme = (p.scheme or "https").lower()
        netloc = (p.netloc or "").lower()
        path = p.path or ""

        # если прилетело без netloc (например //example.com/..)
        if not netloc and path.startswith("//"):
            p2 = urlparse(scheme + ":" + u)
            scheme = (p2.scheme or scheme).lower()
            netloc = (p2.netloc or "").lower()
            path = p2.path or ""

        host = netloc
        drop_query_hosts = ("instagram.com", "t.me", "vk.com", "tiktok.com", "youtube.com", "youtu.be")
        query = "" if any(h in host for h in drop_query_hosts) else (p.query or "")
        fragment = ""  # always drop fragments

        if path != "/" and path.endswith("/"):
            path = path[:-1]

        return urlunparse((scheme, netloc, path, "", query, fragment))
    except Exception:
        return u


def extract_urls(text: str) -> List[str]:
    """Extract up to 3 unique URLs preserving order."""
    if not text:
        return []
    urls = URL_RE.findall(text)
    cleaned: List[str] = []
    for u in urls:
        u = u.strip().rstrip(".,!?:;)")
        if u:
            cleaned.append(normalize_url(u))

    seen = set()
    out: List[str] = []
    for u in cleaned:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out[:3]


def extract_targets(text: str) -> List[str]:
    """
    Возвращает до 3 целей (urls) из:
    - прямых ссылок
    - @username
    - "инст username" / "tg username" и т.п.

    Логика:
    - Если пользователь явно про IG -> никогда не пробуем TG для @handle
    - Если явно про TG -> никогда не пробуем IG
    - Если неясно -> эвристика: точка в нике => IG, иначе TG
    """
    urls = extract_urls(text)

    found: List[str] = []
    raw = text or ""
    context = raw.lower()

    ig_markers = [
        "instagram", "инстаграм", "инста", "инст",
        "рилс", "reels", "сторис", "stories",
        "шапка профиля", "профиль", "био", "bio",
        "хайлайт", "highlights",
        "таплинк", "taplink", "link in bio", "ссылка в био",
        "просмотры рилс", "просмотры reels",
        "подписчики",  # часто пишут "подписчики в инсте"
    ]
    tg_markers = [
        "telegram", "телеграм", "тг",
        "канал", "группа", "чат",
        "пост", "репост", "переслать", "пересыл",
        "реакции", "закреп", "закрепленный", "пин", "pinned",
    ]

    prefer_ig = any(x in context for x in ig_markers)
    prefer_tg = any(x in context for x in tg_markers)

    # 1) word-handle: "инсте @name", "instagram name", "tg name"
    for m in WORD_HANDLE_RE.finditer(raw):
        platform = (m.group(1) or "").lower()
        handle = (m.group(2) or "").strip().lstrip("@")

        if platform.startswith(("instagram", "inst", "ig", "инстаграм", "инста", "инст")):
            found.append(normalize_url(f"https://www.instagram.com/{handle}/"))
        elif platform.startswith(("telegram", "tg", "телеграм", "тг")):
            found.append(normalize_url(f"https://t.me/{handle}"))

    # 2) plain @handle — с жёстким приоритетом платформы
    for m in HANDLE_RE.finditer(raw):
        handle = (m.group(1) or "").strip().lstrip("@")
        looks_like_instagram = "." in handle  # точки в TG username нет

        if prefer_ig and not prefer_tg:
            found.append(normalize_url(f"https://www.instagram.com/{handle}/"))
            continue

        if prefer_tg and not prefer_ig:
            found.append(normalize_url(f"https://t.me/{handle}"))
            continue

        # контекст не ясен → эвристика
        if looks_like_instagram:
            found.append(normalize_url(f"https://www.instagram.com/{handle}/"))
        else:
            found.append(normalize_url(f"https://t.me/{handle}"))

    combined = urls + found
    seen = set()
    out: List[str] = []
    for u in combined:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out[:3]


@dataclass
class UrlAnalysisResult:
    urls: List[str]
    url_summaries: List[Dict[str, Any]]


def _sha(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", errors="ignore")).hexdigest()


def _now_utc() -> datetime:
    return datetime.utcnow()


def _ttl_for(page_type: str, ok: bool) -> timedelta:
    if not ok:
        return timedelta(hours=1)
    if page_type in {"instagram", "vk", "tiktok", "youtube", "telegram"}:
        return timedelta(days=1)
    return timedelta(days=7)


def _classify(final_url: str) -> str:
    """Return coarse page type to tune extraction/caching."""
    host = urlparse(final_url).netloc.lower()
    path = urlparse(final_url).path.lower()

    if "instagram.com" in host:
        return "instagram"
    if host.endswith("t.me") or "t.me" in host:
        return "telegram"
    if "vk.com" in host:
        return "vk"
    if "tiktok.com" in host:
        return "tiktok"
    if "youtube.com" in host or "youtu.be" in host:
        return "youtube"
    if path.endswith(".pdf"):
        return "pdf"
    return "website"


async def _fetch_json(client: httpx.AsyncClient, url: str) -> Optional[Dict[str, Any]]:
    try:
        r = await client.get(url)
        if r.status_code >= 400:
            return None
        return r.json()
    except Exception:
        return None


class UrlAnalyzer:
    """Fetch and extract lightweight metadata + text snippet from user provided URLs.

    Notes:
    - Uses DB cache table UrlCache if session is provided.
    - Avoids heavy scraping for platforms that are frequently blocked.
    """

    def __init__(self, db_session: Any = None) -> None:
        self._db_session = db_session

    async def analyze(self, text: str) -> Optional[UrlAnalysisResult]:
        urls = extract_targets(text)
        if not urls:
            return None

        # дополнительно нормализуем (на всякий)
        urls = [normalize_url(u) for u in urls]

        summaries = await asyncio.gather(*(self._fetch_and_summarize(u) for u in urls))
        return UrlAnalysisResult(urls=urls, url_summaries=list(summaries))

    async def _get_cached(self, url: str) -> Optional[Dict[str, Any]]:
        if not self._db_session:
            return None

        try:
            await self._db_session.execute(delete(UrlCache).where(UrlCache.expires_at < _now_utc()))
            await self._db_session.commit()

            res = await self._db_session.execute(select(UrlCache).where(UrlCache.url == url))
            row = res.scalar_one_or_none()
            if not row:
                return None
            if row.expires_at and row.expires_at < _now_utc():
                return None
            if row.summary_json:
                data = dict(row.summary_json)
                data["cache"] = "hit"
                return data
        except Exception:
            return None
        return None

    async def _set_cache(self, url: str, extracted_hash: str, summary: Dict[str, Any]) -> None:
        if not self._db_session:
            return
        try:
            expires = _now_utc() + _ttl_for(summary.get("page_type", "website"), bool(summary.get("ok")))
            obj = UrlCache(
                url=url,
                extracted_text_hash=extracted_hash,
                summary_json=summary,
                expires_at=expires,
            )
            await self._db_session.merge(obj)
            await self._db_session.commit()
        except Exception:
            try:
                await self._db_session.rollback()
            except Exception:
                pass

    async def _fetch_and_summarize(self, url: str) -> Dict[str, Any]:
        url = normalize_url(url)

        cached = await self._get_cached(url)
        if cached is not None:
            return cached

        started = time.time()
        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; ChatplaceBot/1.0; +https://chatplace.io)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        timeout = httpx.Timeout(20.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
            try:
                resp = await client.get(url)
            except Exception as e:
                summary = {
                    "ok": False,
                    "url": url,
                    "status_code": None,
                    "error": f"fetch_error:{type(e).__name__}",
                    "warnings": ["fetch_failed"],
                    "page_type": "unknown",
                }
                await self._set_cache(url, _sha(str(summary)), summary)
                return summary

            status = resp.status_code
            final_url = normalize_url(str(resp.url))
            page_type = _classify(final_url)
            ctype = (resp.headers.get("content-type") or "").lower()

            # Fast-path: PDF / non-html
            if page_type == "pdf" or ("text/html" not in ctype and "application/xhtml+xml" not in ctype):
                summary = {
                    "ok": status < 400,
                    "url": url,
                    "final_url": final_url,
                    "status_code": status,
                    "content_type": ctype,
                    "page_type": page_type,
                    "elapsed_ms": int((time.time() - started) * 1000),
                    "warnings": ["not_html"],
                }
                await self._set_cache(url, _sha(final_url + ctype), summary)
                return summary

            if status >= 400:
                summary = {
                    "ok": False,
                    "url": url,
                    "final_url": final_url,
                    "status_code": status,
                    "error": f"http_{status}",
                    "warnings": ["blocked_or_not_found"],
                    "page_type": page_type,
                    "elapsed_ms": int((time.time() - started) * 1000),
                }
                await self._set_cache(url, _sha(final_url + str(status)), summary)
                return summary

            html = resp.text or ""

            # Try oEmbed for platforms where it exists
            oembed: Optional[Dict[str, Any]] = None
            if page_type == "youtube":
                oembed = await _fetch_json(client, f"https://www.youtube.com/oembed?format=json&url={final_url}")

            parsed = HTMLParser(html)

            def _meta_name(name: str) -> str:
                n = parsed.css_first(f'meta[name="{name}"]')
                if n and n.attributes.get("content"):
                    return n.attributes["content"].strip()
                return ""

            def _meta_prop(prop: str) -> str:
                n = parsed.css_first(f'meta[property="{prop}"]')
                if n and n.attributes.get("content"):
                    return n.attributes["content"].strip()
                return ""

            title = (parsed.css_first("title").text(strip=True) if parsed.css_first("title") else "")
            meta_desc = _meta_name("description")

            og = {
                "title": _meta_prop("og:title"),
                "description": _meta_prop("og:description"),
                "image": _meta_prop("og:image"),
                "type": _meta_prop("og:type"),
                "site_name": _meta_prop("og:site_name"),
                "url": _meta_prop("og:url"),
            }

            if oembed:
                title = title or oembed.get("title") or ""
                og["image"] = og.get("image") or oembed.get("thumbnail_url") or ""

            h1 = [n.text(strip=True) for n in parsed.css("h1")][:3]
            headings = [n.text(strip=True) for n in parsed.css("h2")][:10]

            # CTA texts: buttons/links
            ctas: List[str] = []
            for n in parsed.css("a,button"):
                t = (n.text(strip=True) or "").strip()
                if 0 < len(t) <= 50:
                    if any(
                        k in t.lower()
                        for k in [
                            "куп", "заказ", "рег", "скач", "подпис", "получ", "начать", "войти", "запис",
                            "book", "buy", "order", "sign", "download", "get", "start",
                        ]
                    ):
                        ctas.append(t)

            seen = set()
            cta_texts: List[str] = []
            for x in ctas:
                if x not in seen:
                    seen.add(x)
                    cta_texts.append(x)
            cta_texts = cta_texts[:10]

            # Remove noise
            for bad in parsed.css("script,style,noscript,svg"):
                bad.decompose()

            # Telegram pages: try extract last post snippets
            tg_posts: List[str] = []
            if page_type == "telegram":
                for n in parsed.css(".tgme_widget_message_text"):
                    t = (n.text(separator="\n", strip=True) or "").strip()
                    if t:
                        tg_posts.append(t[:500])
                    if len(tg_posts) >= 5:
                        break

            body = parsed.css_first("body")
            raw_text = body.text(separator="\n", strip=True) if body else parsed.text(separator="\n", strip=True)
            lines = [ln.strip() for ln in raw_text.splitlines()]
            lines = [ln for ln in lines if 30 <= len(ln) <= 500]
            main_text_excerpt = "\n".join(lines)[:5000]

            warnings: List[str] = []
            if not main_text_excerpt and not tg_posts:
                warnings.append("empty_main_text")

            # Common blocked platforms
            if page_type in {"instagram", "vk", "tiktok"} and ("empty_main_text" in warnings):
                warnings.append("platform_may_block_scraping")

            elapsed_ms = int((time.time() - started) * 1000)

            summary = {
                "ok": True,
                "url": url,
                "final_url": final_url,
                "status_code": status,
                "elapsed_ms": elapsed_ms,
                "content_type": ctype,
                "page_type": page_type,
                "title": (title or "")[:500],
                "meta_description": (meta_desc or "")[:800],
                "og": {
                    "title": (og.get("title") or "")[:800],
                    "description": (og.get("description") or "")[:1200],
                    "image": (og.get("image") or "")[:1200],
                    "type": (og.get("type") or "")[:120],
                    "site_name": (og.get("site_name") or "")[:200],
                    "url": (og.get("url") or "")[:1200],
                },
                "h1": [x[:300] for x in h1],
                "headings": [x[:300] for x in headings],
                "cta_texts": cta_texts,
                "main_text_excerpt": main_text_excerpt,
                "telegram_last_posts": tg_posts,
                "warnings": warnings,
            }

            extracted_hash = _sha(
                "\n".join(
                    [
                        summary.get("title", ""),
                        summary.get("meta_description", ""),
                        summary.get("main_text_excerpt", ""),
                        "\n".join(summary.get("cta_texts", []) or []),
                        "\n".join(summary.get("telegram_last_posts", []) or []),
                    ]
                )
            )
            await self._set_cache(url, extracted_hash, summary)
            return summary
