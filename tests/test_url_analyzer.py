import pytest

from app.services.url_analyzer import InMemoryUrlCacheStore, UrlSummary, extract_urls


def test_extract_urls():
    text = "Посмотри https://example.com и https://test.io/page."
    urls = extract_urls(text)
    assert urls == ["https://example.com", "https://test.io/page"]


@pytest.mark.asyncio
async def test_in_memory_cache_store():
    store = InMemoryUrlCacheStore()
    summary = UrlSummary(
        url="https://example.com",
        title="Example",
        extracted_text="hello",
        url_summary={"summary": "ok"},
    )
    await store.set(summary.url, summary.title, summary.extracted_text, summary.url_summary)
    cached = await store.get(summary.url)
    assert cached is not None
    assert cached.title == "Example"
