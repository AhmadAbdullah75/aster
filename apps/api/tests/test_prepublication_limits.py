"""Literal at/over boundaries on actual parsers, request validation and persistence."""

import io
import json
import time
import zipfile
from pathlib import Path

import pytest
from conftest import register
from docx import Document as WordDocument
from nexus import documents
from nexus.config import settings
from nexus.db import transaction
from nexus.models import Document


def test_upload_one_byte_over_and_storage_exact_boundary(client):
    user = register(client)
    size = 10 * 1024 * 1024
    response = client.post(
        "/documents", files={"file": ("over.txt", b"x" * (size + 1), "text/plain")}
    )
    assert response.status_code == 413
    with transaction() as db:
        db.add(
            Document(
                user_id=user["id"],
                filename="Synthetic usage.txt",
                blob="not-a-real-file.txt",
                sha256="synthetic-limit-usage",
                size=200 * 1024 * 1024 - 1,
                media_type="text/plain",
                status="ready",
            )
        )
    exact = client.post("/documents", files={"file": ("one.txt", b"a", "text/plain")})
    assert exact.status_code == 202
    over = client.post("/documents", files={"file": ("two.txt", b"b", "text/plain")})
    assert over.status_code == 413 and "Storage quota" in over.text


def test_extracted_text_and_chunk_count_exact_boundaries():
    assert documents.parse(("word " * 400_000).encode(), ".txt")
    with pytest.raises(ValueError, match="two million"):
        documents.parse(("word " * 400_000 + "x").encode(), ".txt")
    text = "".join(f"# Section {number}\nSmall evidence.\n" for number in range(1200))
    assert len(documents.parse(text.encode(), ".md")) == 1200
    with pytest.raises(ValueError, match="maximum 1200"):
        documents.parse((text + "# Extra\nEvidence.").encode(), ".md")


def word_archive():
    doc = WordDocument()
    doc.add_paragraph("Boundary evidence remains readable.")
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def test_docx_expansion_and_entry_exact_boundaries():
    original = word_archive()
    with zipfile.ZipFile(io.BytesIO(original)) as archive:
        expanded = sum(item.file_size for item in archive.infolist())
        entries = len(archive.infolist())
    for extra, accepted in [(0, True), (1, False)]:
        out = io.BytesIO(original)
        with zipfile.ZipFile(
            out, "a", compression=zipfile.ZIP_DEFLATED, compresslevel=1
        ) as archive:
            archive.writestr("unused-padding.bin", b"x" * (50 * 1024 * 1024 - expanded + extra))
        if accepted:
            assert "Boundary evidence" in documents.parse(out.getvalue(), ".docx")[0]["content"]
        else:
            with pytest.raises(ValueError, match="decompression limit"):
                documents.parse(out.getvalue(), ".docx")
    for count, accepted in [(2000, True), (2001, False)]:
        out = io.BytesIO(original)
        with zipfile.ZipFile(out, "a", compression=zipfile.ZIP_DEFLATED) as archive:
            for number in range(count - entries):
                archive.writestr(f"unused/{number}", b"")
        if accepted:
            assert documents.parse(out.getvalue(), ".docx")
        else:
            with pytest.raises(ValueError, match="decompression limit"):
                documents.parse(out.getvalue(), ".docx")


def test_message_selected_documents_and_memory_exact_boundaries(client, monkeypatch):
    user = register(client)
    monkeypatch.setattr(settings, "openai_api_key", "synthetic-only-not-a-provider-key")
    with transaction() as db:
        docs = [
            Document(
                user_id=user["id"],
                filename=f"Synthetic {n}.txt",
                blob=f"unused-{n}.txt",
                sha256=f"limit-{n}",
                size=1,
                media_type="text/plain",
                status="ready",
            )
            for n in range(31)
        ]
        db.add_all(docs)
        db.flush()
        ids = [doc.id for doc in docs]
    thread = client.post("/conversations", json={}).json()
    url = f"/conversations/{thread['id']}/runs"
    assert client.post(url, json={"message": "x" * 40001}).status_code == 422
    assert client.post(url, json={"message": "x", "document_ids": ids}).status_code == 422
    accepted = client.post(url, json={"message": "x" * 40000, "document_ids": ids[:30]})
    assert accepted.status_code == 202, accepted.text
    assert client.post(url, json={"message": "Another run"}).status_code == 409
    assert (
        client.post("/memories", json={"title": "Exact memory", "content": "x" * 4000}).status_code
        == 200
    )
    assert (
        client.post("/memories", json={"title": "Over memory", "content": "x" * 4001}).status_code
        == 422
    )


@pytest.mark.parametrize("resource", ["projects", "conversations", "tasks", "notes", "memories"])
def test_resource_title_200_accepted_201_rejected(client, resource):
    register(client)
    payload = {"title": "x" * 200}
    if resource == "memories":
        payload["content"] = "Synthetic preference"
    assert client.post(f"/{resource}", json=payload).status_code == 200
    payload["title"] += "x"
    assert client.post(f"/{resource}", json=payload).status_code == 422


def test_profile_name_exact_120_and_over_121(client):
    user = register(client)
    profile = {
        "name": "n" * 120,
        "version": user["version"],
        "timezone": "Asia/Karachi",
        "theme": "light",
        "memory_enabled": True,
    }
    saved = client.put("/me", json=profile)
    assert saved.status_code == 200
    profile.update(name="n" * 121, version=saved.json()["version"])
    assert client.put("/me", json=profile).status_code == 422
    assert client.get("/me").json()["name"] == "n" * 120


def test_ten_mib_text_hits_documented_text_limit_without_provider_or_timeout():
    data = b"x" * (10 * 1024 * 1024)
    started = time.perf_counter()
    with pytest.raises(ValueError, match="two million"):
        documents.parse(data, ".txt")
    elapsed = time.perf_counter() - started
    root = Path(__file__).resolve().parents[3]
    (root / "artifacts/prepublication/ten-mib-processing.json").write_text(
        json.dumps(
            {
                "upload_bytes": len(data),
                "parse_seconds": elapsed,
                "outcome": "Documented2million-character extraction limit; no indexing/model request attempted.",
                "scope": "UTF8TXT at10MiB cannot fit2millioncharacters, so ready status is not expected; bounded parser rejection is expected.",
            },
            indent=2,
        )
        + "\n"
    )
    assert elapsed < 5
