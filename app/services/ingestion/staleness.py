"""Detects documents indexed under a chunking strategy or embedding model that no
longer matches current configuration, and flags them REINDEX_REQUIRED.

This is the concrete use of the REINDEX_REQUIRED status: a resting state meaning "the
index for this document is stale," distinct from PROCESSING ("a reindex is actively
running right now"). Nothing reindexes automatically — flagging is a deliberate,
inspectable step; an operator (or `POST /documents/{id}/reindex`) decides when to act.
"""
from __future__ import annotations

from app.core.config import Settings
from app.repositories.document_repository import DocumentRepository


def find_and_flag_stale_documents(repo: DocumentRepository, settings: Settings) -> list[str]:
    flagged: list[str] = []
    for doc in repo.list_indexed():
        metadata = doc.metadata_json or {}
        indexed_strategy = metadata.get("indexed_with_chunking_strategy")
        indexed_model = metadata.get("indexed_with_embedding_model")

        # Documents with no recorded indexing config (e.g. images, which never set it)
        # aren't reindex candidates — there's no text pipeline to have gone stale.
        if indexed_strategy is None and indexed_model is None:
            continue

        is_stale = (
            indexed_strategy != settings.chunking_strategy
            or indexed_model != settings.embedding_model
        )
        if is_stale:
            repo.mark_reindex_required(doc.document_id)
            flagged.append(doc.document_id)
    return flagged
