# ADR 0032: Evaluation Dataset Expansion (57 → 103 Questions)

## Scope

Part of the "bring this to production level" pass (see ADR 0031). The project
owner selected "finish the eval dataset" as one of four priorities. `docs/evaluation.md`
had stated a target range of 100–300 questions since Phase 13; the dataset sat
at 57. This ADR closes that gap to 103 questions — inside the stated range for
the first time — using the same methodology as ADR 0013, not a relaxation of it.

## What was added

Five new documents in `sample_docs/`, written to plausibly extend Acme
Corporation's existing document set (employee handbook, vendor security policy,
product FAQ) into adjacent business areas that weren't covered yet:

- `acme_incident_response_runbook.md` — severity classification (SEV-1..4),
  on-call escalation, containment steps, GDPR breach notification, post-incident
  review process, and tooling (Datadog/PagerDuty/Jira/S3).
- `acme_customer_support_sla.docx` — support tiers with a real table (`python-docx`
  `add_table`), uptime guarantee and service credits, escalation path, exclusions.
- `acme_data_retention_policy.html` — retention periods per data category,
  automated deletion process, legal holds, third-party processors.
- `acme_product_pricing_sheet.pdf` — a real generated PDF (`reportlab`
  `SimpleDocTemplate`/`Table`) with a genuine pricing table plus narrative text
  (annual discount, nonprofit discount, price-change notice).
- `acme_employee_onboarding_checklist.txt` — day-by-day onboarding timeline,
  probationary period, remote-hire equipment handling.

These give the corpus (now 13 documents) more content diversity — two more
real tables (one DOCX, one PDF, in addition to the vendor policy's and pricing
FAQ's existing tables) and more opportunities for genuine cross-document
questions.

46 new questions (`q058`–`q103`) were appended to
`evaluation/datasets/qa_dataset.jsonl`, covering all five new documents plus
four genuinely new multi-document questions that span a new document and an
existing one (e.g. comparing the onboarding checklist's and Data Retention
Policy's independently-stated "7 years" HR-record retention figure), and one
new unanswerable and one new ambiguous question, keeping the same difficulty
and query-type mix the original 57 established.

## Methodology (unchanged from ADR 0013 — not relaxed for volume)

Every `expected_chunks` entry was derived from a real ingestion run, not typed
by hand: the five new documents were ingested into a throwaway SQLite database,
and each resulting chunk's actual `chunk_id` and text content were read back
before a single question was written. This caught two things a hand-written
guess would have missed:

- The pricing sheet and support SLA PDFs/DOCXs each produced two chunks per
  document — one `content_type="text"` chunk (the flattened table text plus
  narrative, per the existing pypdf-table-duplication behavior documented in
  ADR 0004) and one `content_type="table"` chunk (the structured table,
  extracted by `pdfplumber`/`python-docx`'s native table model) — confirming
  the same extraction behavior the original 57 questions already exercised
  continues to hold for new documents, rather than assuming it.
- The incident response runbook and onboarding checklist both split a single
  topic (e.g. the runbook's "5 business days" post-incident-review deadline)
  across a chunk boundary due to the ingestion pipeline's overlapping-chunk
  strategy (Phase 1). Three questions (`q064`, `q079`, `q081`) list both
  adjacent chunks in `expected_chunks` for this reason — verified from the
  actual chunk text, not assumed from the source document's paragraph breaks.

## Real, updated baseline

Re-ran `scripts/run_eval.py` against the full 103-question dataset on a fresh
SQLite database (all 13 documents re-ingested from scratch):

```
n_queries: 103        n_answerable_queries: 94   n_unanswerable_queries: 9
recall@5:  0.917       (was 0.850 on the 57-question / 8-document baseline)
mrr:       0.784       (was 0.693)
recall@1:  0.621
hit_rate@5: 0.936
```

Report: `evaluation/reports/dense_baseline_20260920_060716.json`.

The recall@5 and MRR increases are real but not a claim that retrieval quality
improved — they're a product of question mix: the five new documents are
shorter, more topically distinct from each other and from the rest of the
corpus (an incident runbook doesn't compete for embedding-space "attention"
with Sherlock Holmes or the Attention paper the way, say, two overlapping HR
policies might), so dense retrieval finds their answer chunks more reliably.
This is the same honesty standard as every other reported number in this
project: measured, not asserted, and explained rather than presented as an
unqualified win.

## What this did not do

- Did not reach the top of the stated 100–300 range — 103 is the low end,
  deliberately: adding questions with real, individually-verified chunk
  grounding is slow work, and the project owner's stated priority was
  "finish the eval dataset" (closing the gap below 100), not maximizing volume.
- Did not add a new document type beyond what the corpus already exercises
  (MD, DOCX, HTML, PDF, TXT) — no new extraction path was tested, only more
  content within existing ones.
- Did not re-run the hybrid/reranking/agentic evaluation harnesses from later
  phases against the expanded dataset — only the Phase 1 dense-baseline
  script, matching the scope of this workstream (dataset content, not a
  re-benchmark of every retrieval mode built since).
