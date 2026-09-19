"""Central application configuration, sourced entirely from environment variables.

Never hard-code secrets or environment-specific values elsewhere in the codebase —
import `settings` from here instead.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App ---
    app_name: str = "multimodal-rag-platform"
    environment: str = Field(default="development")  # development | test | production
    log_level: str = Field(default="INFO")
    log_json: bool = Field(default=False)

    # --- Storage paths ---
    data_dir: Path = Field(default=Path("./data"))
    upload_dir: Path = Field(default=Path("./data/uploads"))
    local_vector_store_dir: Path = Field(default=Path("./data/vector_store"))

    # --- Database ---
    database_url: str = Field(default="sqlite:///./data/dev.db")

    # --- Redis / cache ---
    redis_url: str | None = Field(default=None)
    cache_enabled: bool = Field(default=False)
    cache_ttl_seconds: int = Field(default=3600)

    # --- Uploads ---
    max_upload_size_bytes: int = Field(default=25 * 1024 * 1024)  # 25 MB
    allowed_file_types: tuple[str, ...] = Field(
        default=("pdf", "txt", "md", "markdown", "docx", "html", "image")
    )

    # --- Embeddings ---
    embedding_provider: str = Field(default="local")  # local | anthropic
    embedding_model: str = Field(default="sentence-transformers/all-MiniLM-L6-v2")
    embedding_batch_size: int = Field(default=32)

    # --- Chunking ---
    chunking_strategy: str = Field(default="recursive")  # fixed | recursive | semantic
    chunk_size_tokens: int = Field(default=400)
    chunk_overlap_tokens: int = Field(default=60)
    semantic_chunk_similarity_threshold: float = Field(default=0.5)

    # --- Vector store ---
    vector_store: str = Field(default="local")  # local | pinecone
    pinecone_api_key: str | None = Field(default=None)
    pinecone_index: str = Field(default="multimodal-rag")
    pinecone_cloud: str = Field(default="aws")
    pinecone_region: str = Field(default="us-east-1")

    # --- Retrieval ---
    default_top_k: int = Field(default=5)
    retrieval_candidate_pool: int = Field(default=20)

    # --- LLM / generation ---
    llm_provider: str = Field(default="anthropic")
    llm_model: str = Field(default="claude-sonnet-5")
    anthropic_api_key: str | None = Field(default=None)
    llm_max_tokens: int = Field(default=1024)
    llm_temperature: float = Field(default=0.0)
    grounding_confidence_threshold: float = Field(default=0.35)

    # --- API security (Phase 18 groundwork) ---
    api_key: str | None = Field(default=None)  # if set, required via X-API-Key header
    cors_allow_origins: tuple[str, ...] = Field(default=("http://localhost:3000",))

    # --- OCR / multimodal (Phase 4) ---
    ocr_enabled: bool = Field(default=True)
    # Explicit binary paths, not PATH-lookup: Tesseract/Poppler are system installs
    # whose location varies by OS/installer, and requiring a shell restart after
    # install to pick up a PATH change is a bad first-run experience. None means
    # "search PATH" (the normal case on Linux CI/Docker, where apt puts them there).
    ocr_tesseract_cmd: str | None = Field(default=None)
    ocr_poppler_path: str | None = Field(default=None)
    vision_description_enabled: bool = Field(default=True)  # still requires an LLM to be configured
    min_ocr_text_length: int = Field(default=10)  # below this, treat OCR as "found nothing"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.local_vector_store_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
