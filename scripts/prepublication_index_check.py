"""Inspect real native Gemini vectors for the two known synthetic publication accounts."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
assert not json.loads((ROOT / "artifacts/prepublication/results.json").read_text()).get("halt")
sys.path.insert(0, str(ROOT / "apps/api"))
from nexus.config import settings  # noqa: E402
from nexus.db import transaction  # noqa: E402
from nexus.models import Chunk, Document, User  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

evidence = []
with transaction() as db:
    users = list(
        db.scalars(
            select(User.id).where(
                User.email.in_(
                    [
                        "nexus-smoke-publication-20261024a@example.com",
                        "nexus-empty-publication-20261024a@example.com",
                    ]
                )
            )
        )
    )
    assert len(users) == 2
    for doc in db.scalars(select(Document).where(Document.user_id.in_(users))):
        assert doc.status == "ready" and doc.embedding_dimensions == 1536
        assert doc.embedding_model == settings.embedding_model
        chunks = db.execute(
            select(Chunk.position, Chunk.page, func.vector_dims(Chunk.embedding))
            .where(Chunk.document_id == doc.id)
            .order_by(Chunk.position)
        ).all()
        assert chunks and all(dimension == 1536 for _, _, dimension in chunks)
        assert [position for position, _, _ in chunks] == list(range(len(chunks)))
        if doc.filename == "proposal.pdf":
            assert [page for _, page, _ in chunks] == [1, 2, 3, 4, 5]
        evidence.append(
            {
                "filename": doc.filename,
                "model": doc.embedding_model,
                "dimensions": doc.embedding_dimensions,
                "chunks": [
                    {"position": position, "page": page, "vector_dimensions": dimension}
                    for position, page, dimension in chunks
                ],
            }
        )
result = {
    "scope": "Known synthetic accounts only. These native embeddings came from actual Gemini Embedding 2, not deterministic test vectors.",
    "documents": evidence,
}
(ROOT / "artifacts/prepublication/native-index-metadata.json").write_text(
    json.dumps(result, indent=2), encoding="utf-8"
)
print(
    f"{len(evidence)} real native documents verified: configured model, 1536 dimensions, ordered positions and PDF page metadata."
)
