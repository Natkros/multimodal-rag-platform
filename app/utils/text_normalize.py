"""Text normalization applied to every extracted page before chunking (the
"Normalization" step in the Phase 2 ingestion pipeline diagram).

Kept deliberately narrow: canonicalize encoding artifacts and whitespace only. Never
rewrites words or strips content that later phases (or a human reviewer) would expect
to see verbatim in a citation.
"""
from __future__ import annotations

import re
import unicodedata

_BLANK_LINES_RE = re.compile(r"\n{3,}")
_TRAILING_WS_RE = re.compile(r"[ \t]+\n")


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _TRAILING_WS_RE.sub("\n", text)
    text = _BLANK_LINES_RE.sub("\n\n", text)
    return text.strip()
