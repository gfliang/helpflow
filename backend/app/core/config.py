from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "HelpFlow API"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "postgresql+psycopg://helpflow:helpflow_dev_password@localhost:5433/helpflow"
    redis_url: str = "redis://localhost:6379/0"
    frontend_origins: str = "http://localhost:5173"
    jwt_secret: str = "change-this-before-any-non-local-use"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    refresh_token_days: int = 7
    knowledge_chunk_size: int = 180
    knowledge_chunk_overlap: int = 30
    upload_dir: Path = Path("data/uploads")

    # Chat provider: auto picks the first configured real LLM (LLM_API_KEY → OpenRouter).
    # Explicit values: auto | openrouter | openai.
    llm_provider: str = "auto"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    openrouter_api_key: str = ""
    openrouter_model: str = "openrouter/free"
    llm_timeout_seconds: float = 30.0
    chat_confidence_threshold: float = 0.4
    chat_context_limit: int = 4
    chat_history_limit: int = 6
    # Multi-turn: rewrite a follow-up into a standalone query before retrieval.
    chat_contextualize_enabled: bool = True

    # Retrieval: local BGE embeddings (fastembed, 512 dims) with an offline hash fallback.
    embedding_backend: str = "auto"  # auto | bge | hash
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_dimensions: int = 512
    embedding_batch_size: int = 32
    embedding_cache_dir: str = ""
    rag_multi_query_enabled: bool = True
    rag_multi_query_count: int = 3
    rag_candidate_limit: int = 24

    # LangGraph agent: business tool calling with human approval for refunds.
    agent_enabled: bool = True
    agent_use_llm: bool = True
    agent_max_steps: int = 4
    agent_checkpoint_backend: str = "postgres"  # postgres | memory

    # Observability: disabled by default so local runs never depend on Langfuse.
    langfuse_enabled: bool = False
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "http://localhost:3030"

    # Evaluation: heuristic scoring by default; enable the LLM judge explicitly.
    eval_judge_enabled: bool = False
    sensitive_words: str = "傻逼,傻b,操你妈,去死,垃圾客服,骗子,fuck,shit"
    handoff_keywords: str = "转人工,人工客服,真人客服,找客服,要人工,人工服务,投诉,紧急,经理"
    rate_limit_enabled: bool = True
    public_chat_limit_per_minute: int = 30
    login_limit_per_minute: int = 12

    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.frontend_origins.split(",") if origin.strip()]

    @property
    def sensitive_word_list(self) -> list[str]:
        return [word.strip().lower() for word in self.sensitive_words.split(",") if word.strip()]

    @property
    def handoff_keyword_list(self) -> list[str]:
        return [word.strip().lower() for word in self.handoff_keywords.split(",") if word.strip()]

    @property
    def langgraph_database_url(self) -> str:
        """psycopg accepts ``postgresql://`` but not the SQLAlchemy ``+psycopg`` suffix."""
        return self.database_url.replace("postgresql+psycopg://", "postgresql://")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
