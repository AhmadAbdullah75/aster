from contextlib import asynccontextmanager

import pytest
from google.genai import types
from nexus import provider
from nexus.config import settings


def test_free_only_policy_and_redacted_capabilities(client, monkeypatch):
    from conftest import register

    register(client)
    monkeypatch.setattr(settings, "free_only", True)
    monkeypatch.setattr(settings, "ai_provider", "openai")
    with pytest.raises(ValueError, match="FREE_ONLY"):
        provider.require_provider()
    monkeypatch.setattr(settings, "ai_provider", "gemini")
    monkeypatch.setattr(settings, "gemini_api_key", "")
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        provider.require_provider()
    monkeypatch.setattr(settings, "gemini_api_key", "test-only-gemini-key")
    provider.require_provider()
    capability = client.get("/capabilities")
    assert capability.json()["models"]["chat"] == "gemini-3.5-flash-lite"
    assert "test-only-gemini-key" not in capability.text
    monkeypatch.setattr(settings, "web_backend", "gemini")
    monkeypatch.setattr(settings, "gemini_search_model", "gemini-3.7-flash")
    with pytest.raises(ValueError, match="FREE_ONLY"):
        provider.require_provider()


def test_gemini_grounding_preserves_real_annotations_and_suggestions():
    response = types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(parts=[types.Part.from_text(text="Grounded answer")]),
                grounding_metadata=types.GroundingMetadata(
                    grounding_chunks=[
                        types.GroundingChunk(
                            web=types.GroundingChunkWeb(
                                uri="https://example.com/evidence", title="Evidence"
                            )
                        )
                    ],
                    grounding_supports=[
                        types.GroundingSupport(
                            grounding_chunk_indices=[0],
                            segment=types.Segment(
                                text="Grounded answer", start_index=0, end_index=15
                            ),
                        )
                    ],
                    search_entry_point=types.SearchEntryPoint(
                        rendered_content='<a href="https://google.com/search?q=evidence">Search</a>'
                    ),
                ),
            )
        ]
    )
    result = provider.gemini_grounding(response)
    assert result["sources"][0]["url"] == "https://example.com/evidence"
    assert result["annotations"][0]["grounding_chunk_indices"] == [0]
    assert result["sources"][1]["type"] == "google_search_suggestions"
    with pytest.raises(ValueError, match="no grounded sources"):
        provider.gemini_grounding(types.GenerateContentResponse())


@pytest.mark.asyncio
async def test_gemini_embeddings_batch_dimensions_and_no_fallback(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "gemini")
    requests = []

    class FakeModels:
        async def embed_content(self, **kwargs):
            requests.append(kwargs)
            return types.EmbedContentResponse(
                embeddings=[
                    types.ContentEmbedding(values=[1.0] + [0.0] * 1535) for _ in kwargs["contents"]
                ]
            )

    class FakeClient:
        models = FakeModels()

    @asynccontextmanager
    async def fake_client():
        yield FakeClient()

    monkeypatch.setattr(provider, "google_client", fake_client)
    result = await provider.embed(["section"] * 17)
    assert len(result) == 17 and len(requests) == 2
    assert [len(request["contents"]) for request in requests] == [16, 1]
    assert requests[0]["config"].output_dimensionality == 1536
    assert requests[0]["model"] == "gemini-embedding-2"


@pytest.mark.asyncio
async def test_timeout_classification_preserves_terminal_deadline():
    import asyncio

    from httpx import ReadTimeout
    from nexus.agent import safe_error

    with pytest.raises(TimeoutError) as expired:
        async with asyncio.timeout(0.01):
            await asyncio.sleep(1)
    assert isinstance(expired.value.__cause__, asyncio.CancelledError)
    assert safe_error(expired.value).startswith("Run timed out.")
    request_timeout = ReadTimeout("Synthetic local request deadline")
    request_timeout.__cause__ = asyncio.CancelledError()
    assert safe_error(request_timeout).startswith("Provider request timed out.")


def test_temporary_gemini_outage_does_not_blame_credentials_or_quota():
    from google.genai.errors import ServerError
    from nexus.agent import safe_error

    message = safe_error(ServerError(503, {"error": {"message": "Synthetic high demand"}}))
    assert "temporarily unavailable (HTTP 503)" in message
    assert "quota" not in message.lower() and "key" not in message.lower()
