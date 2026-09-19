# ADR 0010: Phase 10 Grounded Generation

Most of grounded generation shipped in Phase 1 (system prompt, abstention on low
retrieval confidence, citation markers) because the MVP couldn't be an honest RAG demo
without it. Phase 10 formalizes and finishes the two gaps:

## The "high"/"low" confidence boundary was hardcoded, now configurable

`generator.py` compared the top chunk's score against a literal `0.6`. Moved to
`GROUNDING_HIGH_CONFIDENCE_THRESHOLD` (default 0.6, unchanged), alongside the
existing `GROUNDING_CONFIDENCE_THRESHOLD` (abstain floor, default 0.35) — both
tunable per deployment/retrieval-mode without a code change, and both now have direct
unit tests (`tests/unit/test_generator.py`) instead of only being exercised
incidentally through API tests.

## Partial/conflicting evidence gets a hedge, not silence

The original prompt handled two cases well — full evidence (cite it) and no evidence
(abstain) — but said nothing about the middle: sources that partially answer the
question, or that disagree with each other. Rule 5 now requires the model to say so
explicitly ("the sources do not specify...", "source [1] and [2] give different
figures...") rather than confidently picking one silently. This is prompt-only — no
deterministic contradiction *detection* is implemented (comparing chunk claims for
disagreement is a real NLI problem); Phase 14's adversarial testing is where
contradictory-document behavior gets exercised end-to-end.
