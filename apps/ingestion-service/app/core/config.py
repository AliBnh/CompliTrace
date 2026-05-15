import os
from pathlib import Path


def _default_uploads_dir() -> Path:
    configured = os.getenv("UPLOADS_DIR")
    if configured:
        return Path(configured)

    container_default = Path("/app/storage/uploads")
    try:
        container_default.mkdir(parents=True, exist_ok=True)
        return container_default
    except OSError:
        fallback = Path.cwd() / ".complitrace" / "uploads"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


class Settings:
    service_name: str = "CompliTrace Ingestion Service"
    database_url: str = os.getenv("DATABASE_URL", "postgresql+psycopg://postgres:postgres@postgres:5432/complitrace")
    uploads_dir: Path = _default_uploads_dir()
    cors_allowed_origins: list[str] = [
        origin.strip()
        for origin in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
        if origin.strip()
    ]


settings = Settings()
