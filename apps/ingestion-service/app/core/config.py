import os
from pathlib import Path


class Settings:
    service_name: str = "CompliTrace Ingestion Service"
    database_url: str = os.getenv("DATABASE_URL", "postgresql+psycopg://postgres:postgres@postgres:5432/complitrace")
    uploads_dir: Path = Path(os.getenv("UPLOADS_DIR", "/app/storage/uploads"))


settings = Settings()
settings.uploads_dir.mkdir(parents=True, exist_ok=True)
