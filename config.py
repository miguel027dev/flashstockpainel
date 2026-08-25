import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _default_data_dir():
    # No Render, monte um Persistent Disk em /var/data/flashstock.
    if os.getenv("RENDER"):
        return Path(os.getenv("DATA_DIR", "/var/data/flashstock"))
    return Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))


DATA_DIR = _default_data_dir().resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = Path(os.getenv("SQLITE_PATH", str(DATA_DIR / "flashstock.sqlite3"))).resolve()
BACKUP_DIR = Path(os.getenv("BACKUP_DIR", str(DATA_DIR / "backups"))).resolve()
BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def required_secret(name, dev_default):
    value = os.getenv(name, "").strip()
    if value:
        return value
    if not os.getenv("RENDER"):
        return dev_default
    raise RuntimeError(f"{name} não configurada. Defina a variável no servidor antes de iniciar o ERP.")


class Config:
    SECRET_KEY = required_secret("SECRET_KEY", "flashstock-local-dev-change-me")
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{DB_PATH.as_posix()}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "connect_args": {
            "check_same_thread": False,
            "timeout": int(os.getenv("SQLITE_BUSY_TIMEOUT", "30")),
        },
        "pool_pre_ping": True,
    }
    COMPANY_NAME = os.getenv("COMPANY_NAME", "Flash Stock")
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@flashstock.local")
    ADMIN_PASSWORD = required_secret("ADMIN_PASSWORD", "flashstock123")
    MAX_CONTENT_LENGTH = 150 * 1024 * 1024  # restauração de backup + imagens
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "1" if os.getenv("RENDER") else "0") == "1"
    PREFERRED_URL_SCHEME = "https" if os.getenv("RENDER") else "http"
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 12

    DATA_DIR = str(DATA_DIR)
    SQLITE_PATH = str(DB_PATH)
    BACKUP_DIR = str(BACKUP_DIR)
    AUTO_BACKUP_ENABLED = os.getenv("AUTO_BACKUP_ENABLED", "1") == "1"
    AUTO_BACKUP_INTERVAL_SECONDS = max(300, int(os.getenv("AUTO_BACKUP_INTERVAL_SECONDS", "1800")))
    AUTO_BACKUP_KEEP = max(4, int(os.getenv("AUTO_BACKUP_KEEP", "96")))
    MANUAL_BACKUP_KEEP = max(2, int(os.getenv("MANUAL_BACKUP_KEEP", "30")))
    BACKUP_MAX_STORAGE_MB = max(256, int(os.getenv("BACKUP_MAX_STORAGE_MB", "4096")))
