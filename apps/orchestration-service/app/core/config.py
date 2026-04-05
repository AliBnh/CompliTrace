from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=("settings_",),
    )

    database_url: str = Field(default="postgresql+psycopg://postgres:postgres@postgres:5432/complitrace", alias="DATABASE_URL")

    ingestion_service_url: str = Field(default="http://ingestion-service:8001", alias="INGESTION_SERVICE_URL")
    knowledge_service_url: str = Field(default="http://knowledge-service:8002", alias="KNOWLEDGE_SERVICE_URL")

    groq_api_key: str | None = Field(default=None, alias="GROQ_API_KEY")
    gemini_api_key: str | None = Field(default=None, alias="GEMINI_API_KEY")

    model_provider: str = Field(default="groq", alias="MODEL_PROVIDER")
    model_name: str = Field(default="openai/gpt-oss-120b", alias="MODEL_NAME")
    model_temperature: float = Field(default=0.1, alias="MODEL_TEMPERATURE")

    fallback_model_provider: str = Field(default="gemini", alias="FALLBACK_MODEL_PROVIDER")
    fallback_model_name: str = Field(default="gemini-2.5-flash", alias="FALLBACK_MODEL_NAME")

    embedding_model: str = Field(default="sentence-transformers/all-MiniLM-L6-v2", alias="EMBEDDING_MODEL")
    corpus_version: str = Field(default="gdpr-2016-679-v1", alias="CORPUS_VERSION")
    prompt_template_version: str = Field(default="v1.0", alias="PROMPT_TEMPLATE_VERSION")

    reports_dir: Path = Field(default=Path("/app/storage/reports"), alias="REPORTS_DIR")


settings = Settings()
settings.reports_dir.mkdir(parents=True, exist_ok=True)
