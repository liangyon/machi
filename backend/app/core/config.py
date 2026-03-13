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

    # ── Vector Store (ChromaDB) ──────────────────────────
    # Where ChromaDB persists its data on disk.
    # In production this would be replaced by pgvector.
    CHROMA_PERSIST_DIR: str = "./chroma_data"
    CHROMA_COLLECTION_NAME: str = "anime_catalog"


settings = Settings()
