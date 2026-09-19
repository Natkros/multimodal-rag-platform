# ADR 0011: Phase 11 Citation Engine

## Validation is deterministic (word overlap + exact number/proper-noun matching), not LLM-as-judge

`app/services/generation/citation_validator.py` checks each cited sentence against
the chunk(s) its `[n]` markers reference: token-overlap ratio must clear a threshold
(default 0.5), and any number/dollar amount/percentage or novel proper noun in the
sentence must appear in the cited source verbatim (case-insensitive). This is the
"citation correctness [deterministic]" metric already named in `docs/evaluation.md` —
an LLM-as-judge citation checker is a legitimate alternative but costs a model call
per answer and isn't free to run on every request the way this is. Numbers and proper
nouns get special treatment because they're the most falsifiable part of a claim: a
sentence that overlaps 90% with its source but states a different dollar figure is a
hallucination, not a paraphrase, and the failure mode this feature exists to catch.

## On by default — unlike hybrid retrieval, reranking, or query intelligence

Every other opt-in feature since Phase 6 costs real latency (an extra search, a
cross-encoder pass) or needs an LLM call. Citation validation is regex and set
arithmetic over text already in memory — negligible cost, no external dependency, no
measured tradeoff to gate behind a flag. `CITATION_VALIDATION_ENABLED=true` is the
default; `false` exists for completeness, not because turning it off is recommended.

## A real bug the tests caught: generic overlap can mask a fabricated distinctive claim

First implementation only checked token-overlap ratio and exact numbers. A test case —
"The company was founded on Mars" cited against a source saying "founded in Austin,
Texas" — passed validation: "company," "was," "founded" overlap heavily, dragging the
ratio above threshold, while the one word that actually matters ("Mars") was ignored
by a purely statistical overlap measure. Added a second check: any capitalized word
other than the sentence's own first word (a candidate name or place) must also appear
in the cited source, or the claim is unsupported regardless of overall overlap. Caught
by `tests/unit/test_citation_validator.py::test_validate_catches_fabricated_proper_noun_despite_high_word_overlap`
before this shipped, not after.

## What this doesn't catch

Word-overlap and entity matching aren't semantic entailment — a sentence that
correctly *contradicts* its source using entirely different, overlapping vocabulary
("revenue fell" cited against "revenue grew," sharing "revenue" and little else) would
likely fail the overlap check anyway, but the more general case (a cited claim that's
a valid logical negation or paraphrase using different words) isn't distinguished from
a genuine hallucination by this method. A real NLI model would close that gap at the
cost of a per-citation model call; not implemented here — the same "prove it before
adding heavier machinery" posture as Phase 6/7's fusion and reranking work.
