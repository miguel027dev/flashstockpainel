import os
from pathlib import Path

os.environ.setdefault("DATA_DIR", str(Path(__file__).resolve().parents[1] / "data"))
os.environ.setdefault("SQLITE_PATH", str(Path(__file__).resolve().parents[1] / "data" / "test.sqlite3"))
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("ADMIN_PASSWORD", "test-admin")
os.environ.setdefault("AUTO_BACKUP_ENABLED", "0")
os.environ.setdefault("AUTO_CREATE_DB", "1")

from app import app


def test_healthz():
    client = app.test_client()
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.get_json()["ok"] is True


def test_public_home():
    client = app.test_client()
    response = client.get("/")
    assert response.status_code == 200
