# ADR 0027: Phase 27 Agentic RAG (Optional) — Not Built, With Reasoning

## What "agentic RAG via LangGraph" would actually require

The brief marks this phase explicitly optional. Agentic RAG's defining property —
what distinguishes it from Phase 8's query intelligence — is **dynamic,
LLM-driven control flow**: at each step, the model itself decides what to do next
(retrieve again with a different query, accept the current evidence and answer,
ask a clarifying question, abandon a line of reasoning and try another), rather
than following a fixed sequence of steps chosen at request-handling time. Phase
8's pipeline (`app/services/query_intelligence/pipeline.py`) already does
classify → rewrite → decompose → expand → match-document, but every one of those
steps runs (or doesn't) based on **deterministic conditions decided in Python**
(`is_follow_up`, `is_multi_part`, feature flags) — the LLM calls it makes are
single-shot text transformations (rewrite this, split this, expand this), not
decisions about what to do next. A real agentic loop's LLM calls are the control
flow, not steps within a fixed one.

## Why it isn't built here

Every one of those decision points needs a real, configured LLM to produce a
decision worth evaluating. This dev environment has no `ANTHROPIC_API_KEY` — the
same constraint that has shaped every LLM-dependent scope decision since ADR 0008
(query intelligence's measurement gap), through ADR 0013 (evaluation dataset),
ADR 0025 (load testing excludes `/query` entirely), and ADR 0026 (MMR chosen over
HyDE/CRAG for the same reason). The difference this phase: for Phase 8's
single-shot transformations, a scripted fake LLM client can genuinely verify the
*orchestration* is correct (the right prompt gets built, the right fallback
happens on failure, a follow-up's rewritten form actually reaches retrieval) even
without a real model, because the transformation's *shape* — text in, text out —
doesn't depend on the model actually being intelligent about it. An agentic loop's
entire value proposition is the opposite: whether the model's *decision* to
retrieve again, or stop, or reformulate, is actually a good decision. A scripted
fake client can prove a `LangGraph` graph's edges wire up and the loop terminates
— it cannot prove anything about whether the agent behaves sensibly, which is the
only thing that would make building it worthwhile. Shipping that graph would be
indistinguishable, to a reader of this repo, from having built and validated real
agentic behavior — it would look like a completed feature while actually
being unverified scaffolding, which this project's engineering rules treat as
worse than not building it at all.

## Why not build the scaffold anyway, gated behind a flag like everything else

Every other LLM-optional feature in this project (query rewriting, decomposition,
expansion, vision captioning) *is* built and shipped despite the same missing-key
constraint, because each one degrades to a well-defined, tested no-op
(`LLMNotConfiguredError` → skip the step) and the orchestration around it is
independently correct regardless of whether the LLM call inside it is ever
exercised for real. An agentic *loop* has no equivalent safe degradation — a loop
that can't make real decisions isn't a smaller or degraded agent, it's not an
agent, so there's no meaningful "off-but-present" state analogous to
`QUERY_INTELLIGENCE_ENABLED=false`. Adding the `langgraph` dependency and a graph
definition that can only ever be exercised in its degraded (fake-client) form
would add real surface area (a new dependency, a new module, new tests asserting
only that plumbing doesn't crash) for a capability this repo cannot demonstrate
actually working.

## What this ADR is: a decision, not a placeholder

This is the same category of outcome as ADR 0024's cloud deployment (a real
architecture decision — Render, narrowed scope — reasoned through and documented,
without the credentials to run it) and ADR 0026's MMR finding (measured, and the
honest number said "don't"). Declining to build an unverifiable feature, for a
brief that explicitly marks it optional, and writing down exactly why, is a
complete and honest Phase 27 deliverable — not a placeholder for later, and not a
gap silently left unaddressed. If a real `ANTHROPIC_API_KEY` becomes available,
the actual next step would be building a small LangGraph graph (retrieve →
LLM-judge-sufficiency → answer-or-reformulate-and-retry, capped at N iterations)
and measuring it against the Phase 13 eval set the same way Phase 8's rewriting
would be measured — not before.
