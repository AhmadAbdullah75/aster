"""Supplied document boundary cases on real isolated PostgreSQL; no provider calls."""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import register
from nexus import documents
from nexus.config import settings
from nexus.db import transaction
from nexus.models import Chunk, Document, IngestionJob
from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[3]
FILES = ROOT / ".data/prepublication-files"


@pytest.fixture(scope="module", autouse=True)
def fixtures():
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/prepublication_fixtures.py"), "--full", "--extended"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )


def upload(client, filename, data=None, mime=None, project=None):
    suffix = Path(filename).suffix.lower()
    return client.post(
        "/documents",
        files={
            "file": (
                filename,
                (FILES / filename).read_bytes() if data is None else data,
                mime or documents.TYPES.get(suffix, "application/octet-stream"),
            )
        },
        data={"project_id": project} if project else {},
    )


def test_exact_upload_boundary_and_direct_11mib_rejection(client):
    register(client)
    accepted = upload(client, "exactly_10MiB.txt")
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()["size"] == 10 * 1024 * 1024
    oversized = upload(client, "direct.txt", b"x" * (11 * 1024 * 1024))
    assert oversized.status_code == 413
    assert len(client.get("/documents").json()) == 1
    # Upload acceptance and later text extraction are independent limits.
    with pytest.raises(ValueError, match="two million"):
        documents.parse((FILES / "exactly_10MiB.txt").read_bytes(), ".txt")


@pytest.mark.parametrize(
    "name,data,mime,status",
    [
        ("empty.txt", b"", "text/plain", 422),
        ("test.exe", b"Synthetic unsupported file", "application/octet-stream", 415),
        ("test.zip", b"Synthetic unsupported file", "application/zip", 415),
        ("test.png", b"Synthetic unsupported file", "image/png", 415),
        (
            "test.xlsx",
            b"Synthetic unsupported file",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            415,
        ),
        ("test.txt", b"Valid text with mismatched MIME", "image/png", 415),
    ],
)
def test_upload_rejections_leave_no_document(client, name, data, mime, status):
    register(client)
    assert upload(client, name, data, mime).status_code == status
    assert client.get("/documents").json() == []


def test_long_unicode_filename_retains_supported_extension(client):
    register(client)
    name = "اردو🧭" + "x" * 241 + ".txt"
    response = upload(client, name, b"Synthetic long Unicode filename fixture.")
    assert response.status_code == 202, response.text
    assert response.json()["filename"].endswith(".txt")
    assert response.json()["filename"].startswith("اردو🧭")
    assert len(response.json()["filename"]) <= 220


def test_renamed_executable_pdf_rejected_before_persistence(client):
    register(client)
    response = upload(
        client, "renamed.pdf", b"MZ Synthetic non-executable test payload", "application/pdf"
    )
    assert response.status_code == 422, response.text
    assert "PDF signature" in response.text
    assert client.get("/documents").json() == []


def test_traversal_filename_private_generated_blob_and_anonymous_denial(client):
    register(client)
    response = upload(
        client, "../../traversal.pdf", (FILES / "proposal.pdf").read_bytes(), "application/pdf"
    )
    assert response.status_code == 202
    document = response.json()
    assert "/" not in document["filename"] and "\\" not in document["filename"]
    assert "blob" not in document
    with transaction() as db:
        blob = db.get(Document, document["id"]).blob
    assert re.fullmatch(r"[a-f0-9-]{36}\.pdf", blob)
    assert (settings.blobs / blob).resolve().is_relative_to(settings.blobs.resolve())
    assert client.get(f"/documents/{document['id']}/preview?download=true").status_code == 200
    client.post("/auth/logout")
    assert client.get(f"/documents/{document['id']}/preview?download=true").status_code == 401
    assert client.get(f"/blobs/{blob}").status_code == 404


def test_dedup_same_project_separate_project_and_separate_user(client):
    register(client)
    first = upload(client, "plain.txt").json()
    assert upload(client, "plain.txt").json()["id"] == first["id"]
    project = client.post("/projects", json={"title": "Separate document scope"}).json()
    separate = upload(client, "plain.txt", project=project["id"]).json()
    assert separate["id"] != first["id"]
    with transaction() as db:
        assert db.scalar(select(func.count()).select_from(IngestionJob)) == 2
    client.post("/auth/logout")
    register(client, "publication-user-b@example.com")
    other = upload(client, "plain.txt").json()
    assert other["id"] not in {first["id"], separate["id"]}
    assert client.get(f"/documents/{first['id']}/preview").status_code == 404


def test_account_storage_quota_uses_owned_document_sizes(client):
    user = register(client)
    # Synthetic persisted usage avoids writing 200 MiB of disposable blobs.
    with transaction() as db:
        for number in range(20):
            db.add(
                Document(
                    user_id=user["id"],
                    filename=f"Quota fixture {number}.txt",
                    blob=f"quota-only-{number}.txt",
                    sha256=f"quota-{number}",
                    size=10 * 1024 * 1024,
                    media_type="text/plain",
                    status="ready",
                )
            )
    response = upload(client, "plain.txt")
    assert response.status_code == 413 and "Storage quota" in response.text
    assert len(client.get("/documents").json()) == 20


def test_db_only_restore_missing_original_returns_clear_private_404(client):
    register(client)
    result = upload(client, "proposal.pdf")
    assert result.status_code == 202
    document = result.json()
    with transaction() as db:
        blob = db.get(Document, document["id"]).blob
    (settings.blobs / blob).unlink()
    preview = client.get(f"/documents/{document['id']}/preview")
    assert preview.status_code == 404
    assert "Original file unavailable" in preview.text
    assert blob not in preview.text and str(settings.blobs) not in preview.text
    assert client.get("/documents").json()[0]["id"] == document["id"]


@pytest.mark.parametrize(
    "filename,reason",
    [
        ("scanned.pdf", "OCR not supported"),
        ("encrypted.pdf", "Encrypted"),
        ("large_pages.pdf", "500 pages"),
        ("corrupt.pdf", "Malformed or corrupted PDF"),
        ("empty.docx", "no usable text"),
        ("zipbomb.docx", "decompression limit"),
        ("binary.txt", "without binary"),
        ("latin1.txt", "codec"),
        ("huge_text.txt", "two million"),
        ("many_chunks.txt", "1,200|1200"),
    ],
)
def test_parser_rejects_bounded_malformed_fixtures(filename, reason):
    with pytest.raises(ValueError, match=reason):
        documents.parse((FILES / filename).read_bytes(), Path(filename).suffix)


def test_image_mixed_500page_docx_table_textbox_and_bom_fixture_integrity():
    from pypdf import PdfReader

    image = PdfReader(FILES / "scanned.pdf")
    assert len(image.pages[0].images) == 1
    assert image.pages[0].extract_text() == ""
    mixed = documents.parse((FILES / "mixed.pdf").read_bytes(), ".pdf")
    assert "owner is Mira" in mixed[0]["content"] and mixed[0]["page"] == 1
    pages = documents.parse((FILES / "500_pages.pdf").read_bytes(), ".pdf")
    assert len(pages) == 500 and pages[-1]["page"] == 500
    table = documents.parse((FILES / "notes.docx").read_bytes(), ".docx")
    assert "Acceptance | Mira" in "\n".join(chunk["content"] for chunk in table)
    textbox = documents.parse((FILES / "textbox.docx").read_bytes(), ".docx")
    assert "Main body remains readable" in textbox[0]["content"]
    assert "Sapphire Wren" not in "\n".join(chunk["content"] for chunk in textbox)
    assert documents.parse((FILES / "bom.txt").read_bytes(), ".txt")[0]["content"].startswith(
        "Cedar"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "filename", ["proposal.pdf", "notes.docx", "plain.txt", "guide.md", "urdu.txt", "mixed.pdf"]
)
async def test_real_parser_chunk_persistence_and_embedding_metadata(client, monkeypatch, filename):
    register(client)
    document = upload(client, filename).json()

    async def synthetic_embed(texts):
        return [[0.1] * 1536 for _ in texts]

    monkeypatch.setattr(documents, "embed", synthetic_embed)
    with transaction() as db:
        job = db.scalar(select(IngestionJob).where(IngestionJob.document_id == document["id"]))
        job.status, job.worker_id = "processing", "publication-parser-worker"
    await documents.ingest(document["id"], "publication-parser-worker")
    with transaction() as db:
        saved = db.get(Document, document["id"])
        assert saved.status == "ready"
        assert (
            saved.embedding_model == settings.embedding_model and saved.embedding_dimensions == 1536
        )
        chunks = list(
            db.scalars(select(Chunk).where(Chunk.document_id == saved.id).order_by(Chunk.position))
        )
        assert chunks and all(len(chunk.embedding) == 1536 for chunk in chunks)
        assert [chunk.position for chunk in chunks] == list(range(len(chunks)))
        if filename == "proposal.pdf":
            assert [chunk.page for chunk in chunks] == [1, 2, 3, 4, 5]
            assert "QUARTZ-FINCH" in chunks[2].content


def test_chunk_token_size_and_approximately_100_token_overlap():
    # Unique markers detect missing overlap; repeated words would pass even with gaps.
    text = " ".join(f"marker{number:05d}" for number in range(1200))
    chunks = documents.parse(text.encode(), ".txt")
    tokens = [documents.encoding.encode(chunk["content"]) for chunk in chunks]
    assert all(len(chunk) <= 700 for chunk in tokens)
    assert tokens[0][-100:][1:] == tokens[1][:100][1:]


def test_zip_expansion_is_rejected_before_large_allocation():
    import tracemalloc
    import zipfile

    data = (FILES / "zipbomb.docx").read_bytes()
    with zipfile.ZipFile(FILES / "zipbomb.docx") as archive:
        expanded = sum(item.file_size for item in archive.infolist())
    assert expanded > 50 * 1024 * 1024
    tracemalloc.start()
    try:
        with pytest.raises(ValueError, match="decompression limit"):
            documents.parse(data, ".docx")
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 4 * 1024 * 1024
    evidence = {
        "compressed_bytes": len(data),
        "declared_expanded_bytes": expanded,
        "python_allocation_peak_during_parse": peak,
        "limit_assertion_bytes": 4 * 1024 * 1024,
        "scope": "Python allocations during parsing only; fixture generation and process baseline excluded.",
    }
    (ROOT / "artifacts/prepublication/PRS-09-memory.json").write_text(
        json.dumps(evidence, indent=2), encoding="utf-8"
    )
