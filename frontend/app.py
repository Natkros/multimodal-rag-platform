"""Minimal Streamlit UI for the Multimodal RAG Platform (Phase 1).

Talks to the FastAPI backend over HTTP only — no business logic lives here, matching
the API-first architecture in docs/architecture.md.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import requests
import streamlit as st

# Phase 28: where to look for evaluation/reports/*.json (written by scripts/
# run_eval.py, compare_*.py, profile_pipeline.py, load_test.py). Only readable
# when this container/process has that directory mounted — see
# docs/decisions/0028-phase28-admin-dashboard.md for why that's true by default
# in docker-compose.yml but not guaranteed on every deployment target.
EVAL_REPORTS_DIR = Path(os.environ.get("EVAL_REPORTS_DIR", "../evaluation/reports"))

_PROM_LINE_RE = re.compile(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[^}]*\})?\s+([0-9.eE+-]+)$')


def _parse_prometheus_text(text: str) -> list[tuple[str, str, float]]:
    """Minimal Prometheus text-exposition-format parser — no new dependency for
    something this small. Returns (metric_name, labels_str, value) tuples,
    skipping comment/HELP/TYPE lines."""
    parsed = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = _PROM_LINE_RE.match(line)
        if match:
            name, labels, value = match.groups()
            parsed.append((name, labels or "", float(value)))
    return parsed

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
if API_BASE_URL and "://" not in API_BASE_URL:
    # Phase 24: Render's `fromService: property: hostport` env var reference gives
    # a scheme-less "host:port" (no equivalent to docker-compose's already-schemed
    # "http://api:8000") — assume plain HTTP for same-project private-network
    # traffic rather than requiring every deployment target to supply a scheme.
    API_BASE_URL = f"http://{API_BASE_URL}"

st.set_page_config(page_title="Multimodal RAG Platform", layout="wide")
st.title("Multimodal RAG Platform")

tab_upload, tab_query, tab_docs, tab_admin = st.tabs(["Upload", "Ask", "Documents", "Admin"])

with tab_upload:
    st.subheader("Upload a document")
    uploaded_file = st.file_uploader(
        "PDF, TXT, Markdown, DOCX, HTML, or image (PNG/JPEG)",
        type=["pdf", "txt", "md", "markdown", "docx", "html", "png", "jpg", "jpeg"],
    )
    if uploaded_file is not None and st.button("Upload & Index"):
        resp = requests.post(
            f"{API_BASE_URL}/documents/upload",
            files={"file": (uploaded_file.name, uploaded_file.getvalue())},
            timeout=60,
        )
        if resp.status_code in (200, 202):
            st.success(f"Uploaded: {resp.json()}")
        elif resp.status_code == 409:
            st.warning("This exact file is already indexed.")
        else:
            st.error(f"Upload failed ({resp.status_code}): {resp.text}")

with tab_query:
    st.subheader("Ask a question")
    question = st.text_input("Question")
    top_k = st.slider("Top K", min_value=1, max_value=20, value=5)
    if st.button("Ask") and question:
        with st.spinner("Retrieving and generating..."):
            resp = requests.post(
                f"{API_BASE_URL}/query", json={"question": question, "top_k": top_k}, timeout=60
            )
        if resp.status_code == 200:
            body = resp.json()
            st.markdown(f"**Answer** (confidence: `{body['confidence']}`)")
            st.write(body["answer"])
            if body["sources"]:
                st.markdown("**Sources**")
                for i, source in enumerate(body["sources"], start=1):
                    st.markdown(
                        f"[{i}] `{source['document_name']}`"
                        + (f", page {source['page']}" if source.get("page") else "")
                        + f" — relevance {source['relevance_score']:.2f}"
                    )
            with st.expander("Retrieval stats"):
                st.json(body["retrieval"])
        elif resp.status_code == 503:
            st.error("LLM is not configured on the server (missing ANTHROPIC_API_KEY).")
        else:
            st.error(f"Query failed ({resp.status_code}): {resp.text}")

with tab_docs:
    st.subheader("Indexed documents")
    if st.button("Refresh"):
        st.rerun()
    resp = requests.get(f"{API_BASE_URL}/documents", timeout=30)
    if resp.status_code == 200:
        docs = resp.json()["documents"]
        for doc in docs:
            cols = st.columns([4, 2, 2, 1])
            cols[0].write(doc["filename"])
            cols[1].write(doc["processing_status"])
            cols[2].write(f"{doc['chunk_count']} chunks")
            if cols[3].button("Delete", key=doc["document_id"]):
                requests.delete(f"{API_BASE_URL}/documents/{doc['document_id']}", timeout=30)
                st.rerun()
    else:
        st.error("Could not load documents.")

with tab_admin:
    st.subheader("Live metrics")
    st.caption(f"From `GET {API_BASE_URL}/metrics` (Phase 19) — always available, no local file access needed.")
    if st.button("Refresh metrics"):
        st.rerun()
    try:
        metrics_resp = requests.get(f"{API_BASE_URL}/metrics", timeout=10)
        if metrics_resp.status_code == 200:
            samples = _parse_prometheus_text(metrics_resp.text)
            requests_total = [s for s in samples if s[0] == "http_requests_total"]
            cache_total = [s for s in samples if s[0] == "retrieval_cache_total"]
            rate_limit_total = [s for s in samples if s[0] == "rate_limit_rejections_total"]

            if requests_total:
                st.markdown("**HTTP requests by route / status**")
                st.table(
                    [{"labels": labels, "count": int(value)} for _, labels, value in requests_total]
                )
            else:
                st.info("No requests recorded yet.")

            cache_cols = st.columns(2)
            hit = sum(v for n, l, v in cache_total if 'result="hit"' in l)
            miss = sum(v for n, l, v in cache_total if 'result="miss"' in l)
            cache_cols[0].metric("Retrieval cache hits", int(hit))
            cache_cols[1].metric("Retrieval cache misses", int(miss))
            if hit + miss > 0:
                st.caption(f"Hit rate: {hit / (hit + miss):.1%}")

            rejections = sum(v for _, _, v in rate_limit_total)
            st.metric("Rate limit rejections", int(rejections))
        else:
            st.error(f"Could not fetch metrics ({metrics_resp.status_code}).")
    except requests.RequestException as exc:
        st.error(f"Could not reach {API_BASE_URL}/metrics: {exc}")

    st.divider()
    st.subheader("Evaluation report history")
    st.caption(
        f"Reading `{EVAL_REPORTS_DIR}` on this process's own filesystem — only "
        "populated when that directory is mounted/available (true by default in "
        "docker-compose.yml's local stack; not guaranteed on every deployment "
        "target). See docs/decisions/0028-phase28-admin-dashboard.md."
    )
    if not EVAL_REPORTS_DIR.is_dir():
        st.info(f"`{EVAL_REPORTS_DIR}` is not accessible from this process — no report history to show here.")
    else:
        report_files = sorted(EVAL_REPORTS_DIR.glob("*.json"), reverse=True)
        if not report_files:
            st.info("No evaluation reports found yet — run scripts/run_eval.py or a compare_*.py script.")
        else:
            rows = []
            for path in report_files[:50]:
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                # Reports have different shapes (dense baseline vs. compare_* vs.
                # profile_pipeline vs. load_test) - surface whatever top-level
                # summary fields exist rather than assuming one schema.
                summary = data if isinstance(data, dict) else {}
                metrics_blob = summary.get("metrics", summary)
                rows.append(
                    {
                        "file": path.name,
                        "recall@5": metrics_blob.get("recall@5"),
                        "mrr": metrics_blob.get("mrr"),
                        "throughput_req_per_s": summary.get("throughput_req_per_s"),
                        "error_rate": summary.get("error_rate"),
                    }
                )
            st.dataframe(rows, use_container_width=True)
