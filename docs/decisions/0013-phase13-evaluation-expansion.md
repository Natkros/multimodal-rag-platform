# ADR 0013: Phase 13 Evaluation Dataset Expansion

## Scope: grow the dataset honestly, not fabricate the 100-300 target

The brief's Phase 13 goal is a 100-300 question evaluation dataset. This project's
sample corpus (`sample_docs/`) is 8 short documents — an employee handbook, a vendor
security policy, a product FAQ, a scanned expense notice, a revenue chart image, and
one long paper (`attention_is_all_you_need.pdf`) used mainly for chunking-strategy
tests. Writing 100+ genuinely distinct, non-duplicate, source-grounded questions
against that corpus without inventing facts that aren't actually in the documents is
not honestly possible — past a certain point, "new" questions become paraphrases of
existing ones or require content the corpus doesn't contain. This phase expands the
dataset from 12 to 57 questions: every fact asked about was read directly from the
source documents (or, for the two OCR'd files, from the actual post-OCR chunk text —
see below), and every `expected_chunks` entry was derived from a real local ingestion
run, not estimated by hand. 57, not 100-300, is where that honest process landed.
Reaching 100-300 for real means growing the corpus (more documents), not squeezing
more questions out of the same 8 files — left as an explicit, disclosed gap rather
than closed by padding the count with weak or duplicate questions.

## Building the new 45 questions (q013-q057): read the source, then verify against the real index

Every new question was written after re-reading each source document directly
(`sample_docs/acme_employee_handbook.md`, the `.docx`/`.html` FAQ parsed via
`python-docx`/`BeautifulSoup`, and the scanned PDF/PNG read directly as images) to
confirm both the fact and its exact wording — not recalled from memory or
paraphrased loosely. `expected_chunks` were then backfilled by actually running
`scripts/run_eval.py`'s ingestion path against a throwaway SQLite DB and inspecting
the real `chunks` table (`chunk_id`, `content_type`, `text`) rather than guessing
chunk boundaries by hand — the same `deterministic_document_id()` (content-hash based)
that the existing 12 questions rely on made this reproducible: re-ingesting the same
corpus files always produces the same document/chunk IDs. Two Phase-6-era questions
about the handbook's Q2 revenue paragraphs already relied on this determinism; the new
questions extend it to all 8 documents instead of just 2.

## The OCR chunks exposed real extraction noise — questions were written to match it, not around it

Inspecting the actual post-ingestion chunk text (not the source file) surfaced two
real OCR artifacts:

- The scanned expense notice's `$1,240.00` OCRs to `$1.240.00` (Tesseract misreads
  the comma as a period). `q038`'s `expected_answer_substrings` deliberately checks
  for `"1.240.00"` — the actual indexed text — not the visually-correct `"$1,240.00"`
  a human reading the PDF would type. Testing against the wrong (correct-looking but
  not-actually-indexed) string would make the question fail for the wrong reason.
- The revenue chart PNG's OCR is badly garbled: `'ome Quarterly Revenue ($M)\n\n$358m\n\na\n\n423m\n\nsaaim\n\ns510M\n\ney'`
  — the `$44.1M` bar reads back as `saaim`, and even the intact-looking numbers have
  dropped their commas/decimals. `q041` ("Show me Acme's quarterly revenue chart")
  therefore tests only that content-type routing retrieves the right chunk
  (`expected_chunks` set, `query_type=image`) with **no** `expected_answer_substrings`
  — asserting a specific dollar figure against text this garbled would be asserting
  something the pipeline doesn't actually reliably produce. This is the same
  "measure, don't assume" discipline as Phases 6/7/11: a limitation surfaced by
  actually looking at the data, disclosed instead of quietly worked around by picking
  an easier question.

## New query types: `multi_part` and `image`

Two `query_type` values didn't exist in the original taxonomy:

- **`multi_part`**: one question asking two distinct, independently-gradable facts
  (e.g. q017: "within how many days must expense reports be submitted, and after how
  many days is VP-level approval required?"). Different from `comparison` (relating
  two facts to each other, e.g. "how does X's margin compare to Y's") and from
  `multi_document` (facts that live in two different source documents) — a
  `multi_part` question's two facts can live in the same chunk, which several do.
- **`image`**: a retrieval-only check against an image chunk, used exactly once
  (`q041`, above) precisely because OCR quality on this corpus's one chart doesn't
  support a fact-checked answer.

Both are documented in `docs/evaluation.md`'s `query_type` enum.

## Re-baselined dense retrieval: Recall@5 drops from 1.0 to 0.9, and that's the honest result

Re-running `scripts/run_eval.py` (dense-only, unchanged from Phase 1) against the full
57-question set: `recall@5` 0.900, `hit_rate@5` 0.920, `mrr` 0.751, `nDCG@5` 0.789 —
down from the 12-question set's perfect 1.000/1.000/0.750/0.812 (full report:
`evaluation/reports/dense_baseline_20260919_192100.json`). This is not a regression —
nothing about retrieval changed this phase — it's the 12-question set having been too
small to expose gaps that a larger, harder set does. The main contributors are the new
multi-document/multi-part questions (e.g. q030, q048) whose two ground-truth chunks
don't both reliably land in a single un-decomposed query's top 5. Reporting the drop
plainly, rather than only publishing metrics that look good, follows the same rule
that produced Phase 7's negative reranking result: numbers are reported as measured,
not selected for how they read.

## What wasn't done: re-running Phase 3/6/7's comparison scripts against the new dataset

`scripts/compare_chunking_strategies.py`, `compare_retrieval_modes.py`, and
`compare_reranking.py` still report their original numbers against the 10-12 question
sets they were run on — `docs/evaluation.md` and the README are explicit about which
seed size each table used. Re-running them against 57 questions would produce new,
directly comparable numbers, but was not done this phase: Phase 13's scope, per the
brief, is dataset expansion, and re-running three separate comparison scripts (one of
which takes ~130s just for the `semantic` chunking pass, per ADR 0003) is a
half-day-scale task better scoped to whichever future phase actually needs an
updated comparison, rather than bundled in here for its own sake.

## What wasn't done: a `compare_query_intelligence.py`

The larger dataset makes measuring query intelligence's actual effect on retrieval
(rewriting/decomposition vs. not) newly possible in principle, but producing that
number honestly requires a configured `ANTHROPIC_API_KEY`, which this dev environment
doesn't have — same reasoning as ADR 0008's original deferral. Left explicitly
unbuilt rather than faked.
