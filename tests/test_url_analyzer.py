from app.services.url_analyzer import extract_targets, extract_urls, normalize_url


def test_extract_urls():
    text = "Посмотри https://example.com и https://test.io/page."
    urls = extract_urls(text)
    assert urls == ["https://example.com", "https://test.io/page"]


def test_extract_urls_normalizes_deduplicates_and_limits_targets():
    text = (
        "https://example.com/ https://example.com "
        "https://second.example/path/ https://third.example "
        "https://fourth.example"
    )

    assert extract_urls(text) == [
        "https://example.com",
        "https://second.example/path",
        "https://third.example",
    ]


def test_extract_targets_resolves_telegram_handle():
    assert extract_targets("Посмотри Telegram @sample_channel") == [
        "https://t.me/sample_channel"
    ]


def test_normalize_url_drops_fragment_and_trailing_slash():
    assert normalize_url("HTTPS://Example.COM/path/#section") == "https://example.com/path"
