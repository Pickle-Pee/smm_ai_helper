"""One explicitly named page through the existing public-web boundary."""
from typing import Protocol, Any


class OwnedSiteAnalyzer(Protocol):
    async def analyze_url(self, url: str) -> Any: ...


def build_owned_site_analyzer():
    # No cache/DB needed. Callers can explicitly inject an existing cached analyzer;
    # its TTL, independent transactions and public_v1 policy remain unchanged.
    from app.services.url_analyzer import UrlAnalyzer
    return UrlAnalyzer(propagate_fetch_errors=True)


def page_segments(summary):
    """Only fetched text, not URLs, model summaries, image metadata or caller facts."""
    segments = []
    for name in ("title", "meta_description", "main_text_excerpt"):
        value = summary.get(name, "")
        if type(value) is not str:
            raise ValueError("Invalid page text")
        if value.strip():
            segments.append(value.strip())
    for name in ("h1", "headings", "cta_texts"):
        values = summary.get(name, [])
        if type(values) not in (list, tuple) or any(type(v) is not str for v in values):
            raise ValueError("Invalid page text list")
        segments.extend(v.strip() for v in values if v.strip())
    if sum(len(v) for v in segments) > 16000:
        raise ValueError("Page text exceeds extraction budget")
    return tuple(dict.fromkeys(segments))
