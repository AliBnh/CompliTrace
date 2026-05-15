import os
import sys
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite:///./ingestion_test.db"
os.environ["UPLOADS_DIR"] = "./ingestion_test_uploads"

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_missing_file_returns_422_not_500():
    resp = client.post("/documents", data={"foo": "bar"})
    assert resp.status_code == 422
    assert "Missing file upload" in resp.text
