import httpx
import pytest
from nexus import provider
from nexus.config import settings


@pytest.mark.asyncio
async def test_tavily_bounded_basic_request(monkeypatch):
    monkeypatch.setattr(settings, 'web_backend', 'tavily')
    monkeypatch.setattr(settings, 'tavily_api_key', 'synthetic')
    async def post(self, url, **kwargs):
        assert url == 'https://api.tavily.com/search'
        assert kwargs['json']['search_depth'] == 'basic'
        assert kwargs['json']['auto_parameters'] is False
        return httpx.Response(200, json={'results': [
            {'url': 'https://example.com', 'title': 'Example', 'content': 'Evidence'},
            {'url': 'javascript:alert(1)', 'content': 'Invalid'}]})
    monkeypatch.setattr(httpx.AsyncClient, 'post', post)
    result = await provider.web_search('test')
    assert len(result['sources']) == 1
    assert result['sources'][0]['excerpt'] == 'Evidence'


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [429, 432, 433, 401, 500])
async def test_tavily_failure_has_no_fallback(monkeypatch, status):
    monkeypatch.setattr(settings, 'web_backend', 'tavily')
    monkeypatch.setattr(settings, 'tavily_api_key', 'synthetic')
    async def post(self, url, **kwargs):
        return httpx.Response(status)
    monkeypatch.setattr(httpx.AsyncClient, 'post', post)
    with pytest.raises(ValueError, match='quota|unavailable'):
        await provider.web_search('test')
