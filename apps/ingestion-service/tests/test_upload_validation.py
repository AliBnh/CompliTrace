import os
from pathlib import Path
import sys

os.environ["DATABASE_URL"] = "sqlite:///./ingestion_test.db"
os.environ["UPLOADS_DIR"] = "./ingestion_test_uploads"

sys.path.append(str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from app.main import app


client = TestClient(app)


def test_missing_file_returns_422_not_500():
    resp = client.post("/documents", data={"foo": "bar"})
    assert resp.status_code == 422
    assert "Missing file upload" in resp.text
