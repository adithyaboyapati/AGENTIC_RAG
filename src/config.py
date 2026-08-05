"""Central configuration loaded from environment variables."""

from pathlib import Path

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

    # Vector store
    chroma_persist_dir: str = str(PROJECT_ROOT / "data" / "chroma_db")
    collection_name: str = "agentic_rag_docs"

    # Retrieval
    retrieval_top_k: int = 4

    # Agent
    max_retrieval_retries: int = 2
    grader_relevance_threshold: float = 0.5
    max_multi_hop_steps: int = 3

    # LangSmith Observability
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    langsmith_project: str = "agentic-rag"

    # API security
    api_key: str = ""
    require_api_key: bool = False
    cors_origins: str = "*"  # comma-separated origins, or * for all

    # Rate limits & cost guardrails
    max_queries_per_minute: int = 60  # process-wide backstop
    max_queries_per_minute_per_client: int = 20  # per API key / client IP
    max_tokens_per_query: int = 2000
    max_tokens_per_minute: int = 10000
    max_tokens_per_hour: int = 100000
    # Pricing defaults for gpt-4o-mini (USD per 1K tokens)
    cost_per_1k_input_usd: float = 0.00015
    cost_per_1k_output_usd: float = 0.0006

    # Request handling
    request_timeout_seconds: int = 120

    # Privacy
    redact_output_pii: bool = True
    block_output_pii: bool = False

    # API server
    api_workers: int = 1

    # Conversation memory (Supabase)
    memory_enabled: bool = True
    memory_max_turns: int = 6
    supabase_url: str = ""
    supabase_key: str = ""
    supabase_chat_table: str = "chat_messages"


settings = Settings()


def is_production() -> bool:
    return settings.environment.lower() == "production"
