"""Optional explicit composition helper, never imported by ingress or factory."""


def build_public_site_analyzer():
    """Reuse safe fetch/extraction with no cache, retries or swallowed transport errors.

    The import is lazy because UrlAnalyzer's compatibility module imports DB/config.
    Construction performs no I/O; execution never opens a DB session.
    """
    from app.services.url_analyzer import UrlAnalyzer

    return _ExactPublicSiteAnalyzer(UrlAnalyzer(propagate_fetch_errors=True))


class _ExactPublicSiteAnalyzer:
    def __init__(self, analyzer):
        self._analyzer = analyzer

    async def analyze(self, url):
        return await self._analyzer.analyze_url(url)
