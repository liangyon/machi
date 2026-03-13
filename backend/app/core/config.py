"""Application configuration via pydantic-settings."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────
    APP_NAME: str = "Machi"
    DEBUG: bool = False

    # ── Database ─────────────────────────────────────────
    DATABASE_URL: str = "sqlite:///./machi.db"

    # ── CORS ─────────────────────────────────────────────
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    # ── Auth ─────────────────────────────────────────────
    SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080  # 7 days

    # ── OAuth — Google ───────────────────────────────────
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""

    # ── OAuth — Discord ──────────────────────────────────
    DISCORD_CLIENT_ID: str = ""
    DISCORD_CLIENT_SECRET: str = ""

    # ── Frontend ─────────────────────────────────────────
    FRONTEND_URL: str = "http://localhost:3000"

    # ── MAL API ──────────────────────────────────────────
    MAL_CLIENT_ID: str = ""

    # ── OpenAI ───────────────────────────────────────────
    OPENAI_API_KEY: str = ""
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"

    # ── OpenAI Chat (LLM for recommendations) ───────────
    # gpt-4.1-nano: cheapest/fastest, good for simple tasks
    # gpt-4.1-mini: best value (smart + cheap) — our default
    # gpt-4.1: most capable, higher cost
    OPENAI_CHAT_MODEL: str = "gpt-4.1-mini"
    # Temperature: 0.0 = deterministic, 1.0 = creative.
    # 0.7 is a good balance — varied enough to not repeat itself,
    # but focused enough to stay on-topic and give coherent reasoning.
    OPENAI_CHAT_TEMPERATURE: float = 0.7
    # Max tokens for the LLM response.  A single recommendation with
    # reasoning is ~150 tokens, so 10 recs ≈ 1500.  2000 gives headroom.
    OPENAI_CHAT_MAX_TOKENS: int = 2000

    # ── Vector Store (ChromaDB) ──────────────────────────
    # Where ChromaDB persists its data on disk.
    # In production this would be replaced by pgvector.
    CHROMA_PERSIST_DIR: str = "./chroma_data"
    CHROMA_COLLECTION_NAME: str = "anime_catalog"


settings = Settings()
