# Architecture — Multimodal RAG Platform

## 1. Requirements

### 1.1 Functional Requirements

| ID | Requirement |
|----|-------------|
| FR-1 | Users can upload PDF, DOCX, TXT, Markdown, HTML, and image documents. |
| FR-2 | The system classifies document type and extracts text, tables, and images. |
| FR-3 | Scanned/image documents are processed with OCR. |
| FR-4 | Documents are chunked using a configurable strategy that preserves structural metadata. |
| FR-5 | Chunks are embedded with a configurable embedding model and stored in a vector index. |
| FR-6 | Users can query the corpus in natural language and receive a grounded answer with citations. |
| FR-7 | Retrieval combines dense (embedding) and sparse (BM25) search, fused and reranked. |
| FR-8 | The system distinguishes supported claims from unsupported ones and abstains when evidence is insufficient. |
| FR-9 | Users can hold a multi-turn conversation; follow-up questions resolve against prior turns. |
| FR-10 | All retrieval and generation quality is measurable via an evaluation harness with a fixed dataset. |
| FR-11 | Document processing runs asynchronously; clients can poll job status. |
| FR-12 | The system exposes `/health` and `/ready` endpoints and Prometheus-style metrics. |

### 1.2 Non-Functional Requirements

| ID | Requirement |
|----|-------------|
| NFR-1 | p95 end-to-end query latency is measured and reported; regressions must be caught by benchmark tests. |
| NFR-2 | The vector store is accessed through an abstraction; swapping providers requires no changes above the repository layer. |
| NFR-3 | All secrets are supplied via environment variables; nothing sensitive is committed to source control. |
| NFR-4 | The system is horizontally scalable: API is stateless, ingestion runs on a separate worker pool. |
| NFR-5 | Every component that materially affects answer quality must have a baseline and a measured comparison before/after. |
| NFR-6 | The system must fail gracefully — corrupted files, empty documents, LLM timeouts, and vector-store outages must not crash the API. |
| NFR-7 | The full stack must start with a single `docker compose up`. |
| NFR-8 | CI must run lint, type-check, unit/integration/API tests, and a Docker build on every PR. |

## 2. System Architecture

```mermaid
flowchart TB
    subgraph Client
        UI[Web UI]
    end

    subgraph API["FastAPI Application (stateless)"]
        Upload[POST /documents/upload]
        Query[POST /query]
        Jobs[GET /jobs/id]
        Health[/health, /ready/]
    end

    subgraph Async["Async Processing"]
        Queue[(Job Queue - Redis)]
        Worker[Ingestion Worker]
    end

    subgraph AI["AI Services"]
        Extract[Extraction: text / OCR / tables / images]
        Chunk[Chunking]
        Embed[Embedding Model]
        Sparse[BM25 Index]
        Dense[Dense Vector Store]
        Rerank[Cross-Encoder Reranker]
        QueryProc[Query Rewriting / Decomposition]
        Ctx[Context Builder]
        Gen[LLM Generation]
        Cite[Citation Validator]
    end

    subgraph Data["Data Layer"]
        PG[(PostgreSQL - metadata, jobs, conversations)]
        Cache[(Redis - cache, semantic cache)]
        VDB[(Pinecone / pluggable vector DB)]
    end

    UI --> Upload
    UI --> Query
    UI --> Jobs

    Upload --> Queue
    Queue --> Worker
    Worker --> Extract --> Chunk --> Embed --> VDB
    Worker --> Sparse
    Worker --> PG

    Query --> QueryProc --> Dense --> VDB
    QueryProc --> Sparse
    Dense --> Rerank --> Ctx --> Gen --> Cite --> Query
    Query --> Cache
    Query --> PG
```

## 3. Data Flow (Ingestion)

```mermaid
sequenceDiagram
    participant U as User
    participant API as FastAPI
    participant Q as Redis Queue
    participant W as Worker
    participant EX as Extraction
    participant CH as Chunker
    participant EM as Embedder
    participant VDB as Vector Store
    participant PG as PostgreSQL

    U->>API: POST /documents/upload (file)
    API->>API: validate type, size, hash
    API->>PG: insert Document(status=UPLOADED)
    API->>Q: enqueue ingestion job
    API-->>U: 202 {document_id, job_id, status: UPLOADED}

    Q->>W: pop job
    W->>PG: status=PROCESSING
    W->>EX: classify + extract (text/tables/images/OCR)
    EX-->>W: unified representation
    W->>CH: chunk with structural metadata
    CH-->>W: chunks[]
    W->>EM: batch embed chunks
    EM-->>W: vectors[]
    W->>VDB: upsert(vectors, metadata)
    W->>PG: status=INDEXED, page_count, chunk_count
```

## 4. Data Flow (Query / Retrieval)

```mermaid
sequenceDiagram
    participant U as User
    participant API as FastAPI
    participant Cache as Redis
    participant QR as Query Rewriter
    participant D as Dense Retriever
    participant S as Sparse (BM25)
    participant F as Fusion
    participant R as Reranker
    participant CB as Context Builder
    participant L as LLM
    participant CV as Citation Validator
    participant PG as PostgreSQL

    U->>API: POST /query {question, conversation_id?}
    API->>Cache: lookup semantic cache
    alt cache hit
        Cache-->>API: cached answer
    else cache miss
        API->>QR: rewrite/decompose (uses conversation history)
        QR-->>API: resolved sub-queries
        par dense + sparse
            API->>D: embed + search top-N
            API->>S: BM25 search top-N
        end
        D-->>F: candidates
        S-->>F: candidates
        F->>R: fused candidate pool
        R-->>CB: top-K reranked
        CB->>CB: dedupe, order, trim to token budget
        CB->>L: grounded prompt (context + question)
        L-->>CV: draft answer + citations
        CV->>CV: verify citation supports claim
        CV-->>API: answer, citations, confidence
        API->>Cache: store
    end
    API->>PG: log request metrics, conversation turn
    API-->>U: {answer, sources[], confidence}
```

## 5. Deployment Architecture

```mermaid
flowchart LR
    subgraph Internet
        Client[Browser / API client]
    end

    subgraph Cloud["Cloud (single provider)"]
        LB[Load Balancer / Ingress]
        subgraph Compute
            APIsvc[API service - N replicas]
            Worker[Worker service - N replicas]
        end
        PG[(Managed PostgreSQL)]
        Redis[(Managed Redis)]
        Pinecone[(Pinecone - external SaaS)]
        Registry[Container Registry]
        Secrets[Secrets Manager]
    end

    Client --> LB --> APIsvc
    APIsvc --> PG
    APIsvc --> Redis
    APIsvc --> Pinecone
    Worker --> PG
    Worker --> Redis
    Worker --> Pinecone
    Registry -.image.-> APIsvc
    Registry -.image.-> Worker
    Secrets -.env.-> APIsvc
    Secrets -.env.-> Worker
```

## 6. Repository Layout

See root `README.md` and the tree under this repo. Key boundary: `app/api` (HTTP only) →
`app/services/*` (business/AI logic) → `app/repositories` (DB/vector-store access). Route
handlers never touch the database or vector store directly.

## 7. Vector Store Abstraction

`app/services/retrieval/vector_store.py` defines a `VectorStore` protocol
(`upsert`, `query`, `delete`, `delete_by_document`). Two implementations ship in Phase 1:

- `PineconeVectorStore` — production backend, selected when `VECTOR_STORE=pinecone` and
  `PINECONE_API_KEY` is set.
- `LocalVectorStore` — in-process cosine-similarity index persisted to disk as
  `.npz` + JSON sidecar metadata. Selected when `VECTOR_STORE=local` (the default for
  local dev and CI, since it requires no external account).

Both satisfy the same interface, so retrieval/reranking/generation code never branches
on backend.

## 8. Evaluation Strategy (summary — see `docs/evaluation.md`)

A versioned dataset under `evaluation/datasets/` drives all quality claims. Retrieval
metrics (Recall@K, Precision@K, MRR, nDCG) are computed against `expected_chunks`.
Generation metrics (faithfulness, citation correctness) combine a deterministic citation
checker with an LLM-as-judge pass, and both are labeled as such in reports — nothing is
reported as a "score" without stating how it was computed.

## 9. Deployment Strategy (summary — see `docs/deployment.md`)

Phase 1–20 target `docker compose up` for local/dev. Phase 24 adds a real cloud target
(documented, not assumed) — this repository will clearly mark whether a given README
claim reflects local-only or actually-deployed infrastructure.
