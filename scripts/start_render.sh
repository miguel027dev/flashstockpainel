#!/usr/bin/env bash
set -euo pipefail

mkdir -p "${DATA_DIR:-/var/data/flashstock}" "${BACKUP_DIR:-/var/data/flashstock/backups}"

echo "[Flash Stock] Preparando SQLite persistente..."
python scripts/check_models.py
python -m flask --app app init-db

echo "[Flash Stock] Banco: ${SQLITE_PATH:-${DATA_DIR:-/var/data/flashstock}/flashstock.sqlite3}"
echo "[Flash Stock] Backup automático: a cada ${AUTO_BACKUP_INTERVAL_SECONDS:-1800}s quando houver alteração."
echo "[Flash Stock] Iniciando Gunicorn na porta ${PORT:-10000}..."
exec gunicorn --config gunicorn.conf.py wsgi:app
