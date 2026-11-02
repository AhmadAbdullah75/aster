"""Run real document parsing/index persistence with deterministic embeddings in nexus_e2e."""

import asyncio
import io
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import dotenv_values

root = Path(__file__).resolve().parents[2]
os.environ["DATABASE_URL"] = (
    str(dotenv_values(root / ".env")["DATABASE_URL"]).rsplit("/", 1)[0] + "/nexus_e2e"
)
os.environ["DATA_DIR"] = str(root / ".data" / "e2e")
if sys.argv[1] != "live":
    os.environ["GEMINI_API_KEY"] = ""
    os.environ["OPENAI_API_KEY"] = ""
sys.path.insert(0, str(root / "apps" / "api"))

from nexus import documents  # noqa: E402
from nexus.agent import safe_error  # noqa: E402
from nexus.db import transaction  # noqa: E402
from nexus.models import Document, IngestionJob, User  # noqa: E402
from sqlalchemy import select  # noqa: E402

if sys.argv[1] == "files":
    from docx import Document as Docx
    from pypdf import PdfWriter
    from pypdf.actions import JavaScript
    from pypdf.generic import (
        ArrayObject,
        DecodedStreamObject,
        DictionaryObject,
        NameObject,
        NumberObject,
        TextStringObject,
    )

    target = root / ".data" / "audit-files"
    target.mkdir(parents=True, exist_ok=True)
    docx = Docx()
    docx.add_heading("Audit document", 1)
    docx.add_paragraph("Copper Finch launches in June.")
    docx.save(target / "Audit.docx")
    pdf = PdfWriter()
    page = pdf.add_blank_page(600, 800)
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 50 700 Td (Copper Finch launches in June.) Tj ET")
    page[NameObject("/Contents")] = pdf._add_object(stream)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    second = pdf.add_blank_page(600, 800)
    second_stream = DecodedStreamObject()
    second_stream.set_data(b"BT /F1 12 Tf 50 700 Td (Second audit page.) Tj ET")
    second[NameObject("/Contents")] = pdf._add_object(second_stream)
    second[NameObject("/Resources")] = page[NameObject("/Resources")]
    output = io.BytesIO()
    pdf.write(output)
    (target / "Audit.pdf").write_bytes(output.getvalue())
    interactive = PdfWriter()
    interactive.append(io.BytesIO(output.getvalue()))
    interactive.add_open_action(
        JavaScript(
            "app.alert('NEXUS_PDF_SCRIPT_EXECUTED'); app.launchURL('http://127.0.0.1:9/pdf-js');"
        )
    )
    widget = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/FT"): NameObject("/Tx"),
            NameObject("/T"): TextStringObject("synthetic-field"),
            NameObject("/V"): TextStringObject("Data only"),
            NameObject("/Rect"): ArrayObject([NumberObject(n) for n in (50, 650, 250, 675)]),
        }
    )
    widget_ref = interactive._add_object(widget)
    interactive.pages[0][NameObject("/Annots")] = ArrayObject([widget_ref])
    interactive._root_object[NameObject("/AcroForm")] = DictionaryObject(
        {NameObject("/Fields"): ArrayObject([widget_ref])}
    )
    interactive.write(target / "Audit-interactive.pdf")
    huge = PdfWriter()
    huge_page = huge.add_blank_page(10_000_000, 10_000_000)
    huge_page[NameObject("/Contents")] = huge._add_object(stream)
    huge_page[NameObject("/Resources")] = page[NameObject("/Resources")]
    huge.write(target / "Audit-huge-page.pdf")
    print(target)
    sys.exit(0)


async def embed(texts):
    return [[1.0] + [0.0] * 1535 for _ in texts]


async def ingest_one(document_id):
    with transaction() as db:
        doc = db.get(Document, document_id)
        assert doc, "Test document must exist"
        job = db.scalar(select(IngestionJob).where(IngestionJob.document_id == doc.id))
        job.status, job.worker_id, doc.status = "processing", "audit-ingest", "processing"
    try:
        await documents.ingest(document_id, "audit-ingest")
    except Exception as error:
        if sys.argv[1] == "live" and getattr(error, "code", None) == 429:
            logging.critical("HTTP/1.1 429 RESOURCE_EXHAUSTED (real embedding provider)")
            for _ in range(100):
                if json.loads((root / "artifacts/prepublication/results.json").read_text()).get(
                    "halt"
                ):
                    raise SystemExit(75) from None
                await asyncio.sleep(0.05)
            raise SystemExit(75) from None
        with transaction() as db:
            doc = db.get(Document, document_id)
            doc.status, doc.error = "failed", safe_error(error)
            job = db.scalar(select(IngestionJob).where(IngestionJob.document_id == doc.id))
            job.status = "failed"


async def main():
    mode = sys.argv[1]
    if mode == "live":
        from nexus.config import settings

        assert settings.ai_provider == "gemini" and settings.free_only
        assert not json.loads((root / "artifacts/prepublication/results.json").read_text()).get(
            "halt"
        )
        logging.basicConfig(
            level=logging.INFO,
            filename=root / ".data/logs/prepublication-live.err.log",
            encoding="utf-8",
            format="%(asctime)s %(levelname)s %(message)s",
        )
    elif mode != "missing-key":
        documents.embed = embed
    if mode == "slow":

        async def slow_embed(texts):
            (root / "artifacts/prepublication" / f"index-wait-{sys.argv[2]}.json").write_text(
                '{"embedding_started": true}', encoding="utf-8"
            )
            await asyncio.sleep(8)
            return await embed(texts)

        documents.embed = slow_embed
    if mode == "outage":
        from google.genai.errors import ServerError

        async def outage(texts):
            raise ServerError(
                503,
                {
                    "error": {
                        "code": 503,
                        "message": "Controlled test outage",
                        "status": "UNAVAILABLE",
                    }
                },
            )

        documents.embed = outage
    if sys.argv[1] == "user":
        with transaction() as db:
            user = db.get(User, sys.argv[2])
            assert (
                user
                and user.email.startswith("publication-upload-")
                and user.email.endswith("@example.com")
            )
            ids = list(
                db.scalars(
                    select(Document.id).where(
                        Document.user_id == user.id, Document.status.in_(["queued", "processing"])
                    )
                )
            )
        for document_id in ids:
            await ingest_one(document_id)
    else:
        await ingest_one(
            sys.argv[2] if mode in {"live", "missing-key", "slow", "outage"} else sys.argv[1]
        )
    print("Controlled document ingestion attempt completed.")


asyncio.run(main())
