"""Visual descriptions for images with no OCR-extractable text (photos, diagrams,
charts) — the last piece of Phase 4's "unified representation" step. Best-effort by
design: an unconfigured or failing LLM must not fail document ingestion, since the
image is still validly cataloged (Phase 2 behavior) even without a caption.
"""
from __future__ import annotations

import logging

from app.core.config import Settings
from app.services.generation.llm_client import LLMNotConfiguredError, get_llm_client

logger = logging.getLogger(__name__)

DESCRIBE_PROMPT = (
    "Describe this image factually and concisely for a document search index. "
    "If it is a chart or graph, state the chart type, axis labels, and approximate "
    "values shown. If it is a diagram, describe its structure and labeled "
    "components. If it contains any visible text, transcribe it. Do not speculate "
    "beyond what is visibly shown."
)

_FORMAT_TO_MEDIA_TYPE = {
    "PNG": "image/png",
    "JPEG": "image/jpeg",
    "JPG": "image/jpeg",
    "GIF": "image/gif",
    "WEBP": "image/webp",
}


def describe_image(image_bytes: bytes, image_format: str | None, settings: Settings) -> str | None:
    """Returns a caption, or None if vision description is disabled, unconfigured, or
    fails for any reason — never raises."""
    if not settings.vision_description_enabled:
        return None

    media_type = _FORMAT_TO_MEDIA_TYPE.get((image_format or "").upper())
    if media_type is None:
        logger.info("Skipping visual description for unsupported image format: %s", image_format)
        return None

    try:
        llm_client = get_llm_client(settings)
    except LLMNotConfiguredError:
        return None

    try:
        caption = llm_client.describe_image(
            image_bytes, media_type=media_type, prompt=DESCRIBE_PROMPT, max_tokens=400
        )
        return caption.strip() or None
    except Exception:
        logger.warning("Visual description failed", exc_info=True)
        return None
