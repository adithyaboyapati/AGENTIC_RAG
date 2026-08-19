"""Central configuration loaded from environment variables."""

from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Environment
    environment: str = "development"  # development | production

    # LLM
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    openai_timeout_seconds: int = 60  # hard cap per LLM call
    openai_max_retries: int = 2
    max_output_tokens: int = 1024  # cap completion size per LLM call

    # Optional secondary chat provider (used when primary OpenAI call fails —
    # e.g. rate limit / insufficient quota). Embeddings stay on OpenAI.
    llm_fallback_enabled: bool = True
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    groq_timeout_seconds: int = 60
    groq_max_retries: int = 2
    # Rough Llama-3.3-70B on Groq pricing (USD per 1K tokens) — adjust as needed
    groq_cost_per_1k_input_usd: float = 0.00059
    groq_cost_per_1k_output_usd: float = 0.00079

    # Vector store
    # persistent — local SQLite under chroma_persist_dir (local/dev default)
    # http — Chroma server (docker-compose default)
    chroma_mode: str = "persistent"
    chroma_persist_dir: str = str(PROJECT_ROOT / "data" / "chroma_db")
    chroma_host: str = "localhost"
    chroma_port: int = 8000
    chroma_ssl: bool = False
    collection_name: str = "agentic_rag_docs"

    # Ingestion / chunking
    # section_parent_child — TOC/heading parents + small child chunks (best for rag.pdf)
    # fixed — legacy RecursiveCharacterTextSplitter over pages
    chunking_strategy: str = "section_parent_child"
    chunk_size: int = 1000  # used only for strategy=fixed
    chunk_overlap: int = 150
    child_chunk_size: int = 500
    child_chunk_overlap: int = 80
    parent_max_chars: int = 3500  # truncate expanded parents in the LLM context
    expand_to_parent: bool = True  # retrieve children, return parent sections
    parent_store_path: str = str(PROJECT_ROOT / "data" / "parent_store.json")

    # Ingestion cleansing (headers / footers / irrelevant sections)
    cleanse_enabled: bool = True
    cleanse_headers_footers: bool = True
    cleanse_top_margin_ratio: float = 0.06
    cleanse_bottom_margin_ratio: float = 0.06
    cleanse_min_repeat_pages: int = 3
    cleanse_drop_page_numbers: bool = True
    cleanse_drop_boilerplate: bool = True
    cleanse_fix_hyphenation: bool = True
    cleanse_drop_irrelevant_sections: bool = True
    cleanse_drop_table_scaffold: bool = True
    # Comma-separated exact section titles to drop (overrides defaults when set)
    drop_section_titles: str = ""

    # Retrieval
    retrieval_top_k: int = 6  # final chunks passed to the LLM
    retrieval_candidate_k: int = 20  # over-fetch before hybrid/MMR/rerank
    # similarity | mmr | hybrid (dense + BM25 fused with RRF)
    retrieval_search_type: str = "hybrid"
    retrieval_mmr_lambda: float = 0.5
    retrieval_rrf_k: int = 60

    # Cross-encoder reranking — after candidate retrieval, before top_k
    rerank_enabled: bool = True
    # nvidia (NeMo Retriever API) | flashrank (local ONNX)
    rerank_provider: str = "nvidia"
    # nvidia: nvidia/llama-nemotron-rerank-vl-1b-v2 (or nv-rerankqa-mistral-4b-v3)
    # flashrank: ms-marco-MiniLM-L-12-v2 | ms-marco-TinyBERT-L-2-v2
    rerank_model: str = "nvidia/llama-nemotron-rerank-vl-1b-v2"
    rerank_cache_dir: str = str(PROJECT_ROOT / "data" / "flashrank_cache")
    rerank_max_length: int = 512  # truncate long passages before scoring

    # NVIDIA NIM / build.nvidia.com rerank API
    nvidia_api_key: str = ""
    nvidia_api_base: str = "https://ai.api.nvidia.com/v1"
    # Optional full URL override; empty → built from nvidia_api_base + model slug
    nvidia_rerank_url: str = ""
    nvidia_rerank_truncate: str = "END"  # NONE | END (NVIDIA max context ~512 tokens)
    nvidia_rerank_timeout_seconds: float = 30.0

    # Agent
    max_retrieval_retries: int = 2
    grader_relevance_threshold: float = 0.5
    max_multi_hop_steps: int = 3

    # Optional online quality checks (extra LLM calls — off by default)
    quality_guardrails_enabled: bool = False

    # LangSmith Observability
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    langsmith_project: str = "agentic-rag"

    # API security
    api_key: str = ""
    require_api_key: bool = False
    cors_origins: str = "*"  # comma-separated origins, or * for all
    # /metrics and /health/ready expose topology (indexed doc counts, Chroma
    # host/port, which providers are wired). Gate them behind the API key by
    # default; set false only when the network layer already restricts them.
    protect_metrics_endpoint: bool = True
    protect_readiness_endpoint: bool = True

    # Rate limits & cost guardrails
    max_queries_per_minute: int = 60  # process-wide backstop
    max_queries_per_minute_per_client: int = 20  # per API key / client IP
    max_tokens_per_query: int = 2000
    max_tokens_per_minute: int = 30000
    max_tokens_per_hour: int = 100000
    # Pricing defaults for gpt-4o-mini (USD per 1K tokens)
    cost_per_1k_input_usd: float = 0.00015
    cost_per_1k_output_usd: float = 0.0006
    # auto — Redis if reachable, else memory | redis | memory
    rate_limit_backend: str = "auto"
    # Honor X-Forwarded-For first hop only when behind a trusted proxy
    trust_proxy_headers: bool = False
    # Comma-separated hosts for TrustedHostMiddleware; empty = disabled
    trusted_hosts: str = ""
    # Idempotency-Key response TTL (POST /query)
    idempotency_ttl_seconds: int = 86400

    # Circuit breakers (NVIDIA rerank / web search)
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_recovery_seconds: int = 60

    # Request handling
    request_timeout_seconds: int = 120
    # Total wall-clock budget for an SSE run. request_timeout_seconds only
    # bounds the gap between events, so a slow-but-steady stream needs its own
    # deadline or it never ends.
    stream_timeout_seconds: int = 300
    # Hard ceiling on agent runs executing at once. Without this, requests queue
    # behind the default thread pool and concurrent LLM spend is unbounded.
    max_concurrent_queries: int = 8
    # Wait this long for a concurrency slot before returning 503 + Retry-After.
    concurrency_acquire_timeout_seconds: float = 5.0

    # Privacy — PII/PHI handling. off | redact | block, per direction.
    #   off    — pass text through untouched
    #   redact — mask the sensitive span and continue (default)
    #   block  — reject the request/response
    privacy_input_mode: str = "redact"
    privacy_output_mode: str = "redact"
    # PHI is a separate risk class from PII: a topic mention ("what is
    # diabetes?") is not a disclosure. Enable only for clinical corpora.
    privacy_detect_phi: bool = False
    privacy_retention_days: int = 30

    # Security — Jailbreak & Prompt Injection Defense
    # injection_guardrails_mode: block | warn | off
    injection_guardrails_enabled: bool = True
    injection_guardrails_mode: str = "block"  # block | warn | off
    indirect_injection_protection_enabled: bool = True
    prompt_leakage_detection_enabled: bool = True

    # Deprecated pre-PRIVACY_*_MODE flags. Still honoured for one release so
    # existing .env files do not silently change behaviour; see
    # deprecation_warnings, surfaced at startup.
    redact_output_pii: bool | None = None
    block_output_pii: bool | None = None

    # API server
    api_workers: int = 1

    # Response cache (optional Redis — identical question+mode hits)
    cache_enabled: bool = False
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl_seconds: int = 3600  # 1 hour

    # Phase 10: Vector-Based Semantic Cache & Multi-Tenant RBAC
    semantic_cache_enabled: bool = True
    semantic_cache_similarity_threshold: float = 0.94
    semantic_cache_max_entries: int = 1000
    rbac_enabled: bool = True
    default_tenant_id: str = "default"

    # Phase 11: Multimodal Ingestion & Dynamic Context Compression
    multimodal_tables_enabled: bool = True
    multimodal_figures_enabled: bool = True
    context_compression_enabled: bool = True
    context_compression_ratio: float = 0.65  # Retain top 65% most informative tokens

    # Phase 12: Asynchronous Ingestion Job Queue & Webhooks
    ingest_max_concurrent_jobs: int = 2
    ingest_job_retention_seconds: int = 86400  # 24 hours
    webhook_secret: str = ""

    # Phase 15: Multi-Agent Consensus & Adversarial Debate
    consensus_agent_enabled: bool = True
    consensus_max_rounds: int = 1
    consensus_min_confidence: float = 0.80

    # Conversation memory (Supabase + compact prompt packing)
    memory_enabled: bool = True
    memory_max_turns: int = 6  # soft bound used when packing history
    memory_recent_exchanges: int = 3  # full Q + truncated A for these
    memory_answer_max_chars: int = 500  # truncate each recent answer
    memory_max_older_queries: int = 10  # older turns: questions only
    supabase_url: str = ""
    supabase_key: str = ""
    supabase_chat_table: str = "chat_messages"

    # Populated by validators; emitted once at startup rather than at import
    # time (logging is not configured yet when Settings is constructed).
    deprecation_warnings: list[str] = []

    @model_validator(mode="after")
    def _migrate_privacy_flags(self) -> "Settings":
        """Map the retired REDACT_OUTPUT_PII / BLOCK_OUTPUT_PII booleans."""
        warnings: list[str] = list(self.deprecation_warnings)

        if self.block_output_pii is not None:
            warnings.append(
                "BLOCK_OUTPUT_PII is deprecated — use PRIVACY_OUTPUT_MODE=block"
            )
            if self.block_output_pii:
                self.privacy_output_mode = "block"
        if self.redact_output_pii is not None:
            warnings.append(
                "REDACT_OUTPUT_PII is deprecated — use PRIVACY_OUTPUT_MODE="
                "redact|off (PHI now needs PRIVACY_DETECT_PHI=true)"
            )
            if self.block_output_pii is None:
                self.privacy_output_mode = "redact" if self.redact_output_pii else "off"

        valid_modes = {"off", "redact", "block"}
        for field_name in ("privacy_input_mode", "privacy_output_mode"):
            value = (getattr(self, field_name) or "").strip().lower()
            if value not in valid_modes:
                warnings.append(
                    f"{field_name.upper()}={value!r} is not one of "
                    f"{sorted(valid_modes)} — falling back to 'redact'"
                )
                value = "redact"
            setattr(self, field_name, value)

        self.deprecation_warnings = warnings
        return self


settings = Settings()


def is_production() -> bool:
    return settings.environment.lower() == "production"
