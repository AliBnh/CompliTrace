import os
from pathlib import Path


class Settings:
    service_name: str = "CompliTrace Ingestion Service"
    database_url: str = os.getenv("DATABASE_URL", "postgresql+psycopg://postgres:postgres@postgres:5432/complitrace")
    uploads_dir: Path = Path(os.getenv("UPLOADS_DIR", "/app/storage/uploads"))
    cors_allowed_origins: list[str] = [
        origin.strip()
        for origin in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
        if origin.strip()
    ]


settings = Settings()
settings.uploads_dir.mkdir(parents=True, exist_ok=True)
