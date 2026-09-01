"""Minimal Streamlit UI for the Multimodal RAG Platform (Phase 1).

Talks to the FastAPI backend over HTTP only — no business logic lives here, matching
the API-first architecture in docs/architecture.md.
"""
from __future__ import annotations

import os

import requests
import streamlit as st

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")

st.set_page_config(page_title="Multimodal RAG Platform", layout="wide")
st.title("Multimodal RAG Platform")

tab_upload, tab_query, tab_docs = st.tabs(["Upload", "Ask", "Documents"])

with tab_upload:
    st.subheader("Upload a document")
    uploaded_file = st.file_uploader("PDF, TXT, or Markdown", type=["pdf", "txt", "md", "markdown"])
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
