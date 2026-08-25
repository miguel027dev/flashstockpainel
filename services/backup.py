from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    import fcntl
except ImportError:  # pragma: no cover - Render/Linux possui fcntl
    fcntl = None


BACKUP_FORMAT_VERSION = 1
STATE_FILENAME = ".backup-state.json"
LOCK_FILENAME = ".backup.lock"


class BackupError(RuntimeError):
    pass


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def _safe_name(name: str) -> str:
    return "".join(c for c in name if c.isalnum() or c in "-_.")[:180]


class GlobalBackupManager:
    """Backup consistente do SQLite + arquivos persistentes.

    O banco contém usuários, funcionários, permissões, produtos, fotos em BLOB,
    pedidos, estoque, financeiro e configurações. Diretórios legados de uploads
    também entram no pacote para que o backup continue completo caso sejam usados.
    """

    def __init__(
        self,
        db_path: str | Path,
        backup_dir: str | Path,
        project_root: str | Path,
        interval_seconds: int = 1800,
        auto_keep: int = 336,
        manual_keep: int = 50,
        max_storage_mb: int = 4096,
    ):
        self.db_path = Path(db_path).resolve()
        self.backup_dir = Path(backup_dir).resolve()
        self.project_root = Path(project_root).resolve()
        self.interval_seconds = max(300, int(interval_seconds))
        self.auto_keep = max(4, int(auto_keep))
        self.manual_keep = max(2, int(manual_keep))
        self.max_storage_bytes = max(256, int(max_storage_mb)) * 1024 * 1024
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path = self.backup_dir / STATE_FILENAME
        self.lock_path = self.backup_dir / LOCK_FILENAME
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    # ---------------------------- locking/state ----------------------------
    def _lock(self):
        lock_fh = self.lock_path.open("a+b")
        if fcntl:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
        return lock_fh

    def _unlock(self, lock_fh):
        try:
            if fcntl:
                fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
        finally:
            lock_fh.close()

    def _load_state(self) -> dict:
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_state(self, state: dict) -> None:
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.state_path)

    # ---------------------------- snapshots ----------------------------
    def _sqlite_snapshot(self, target: Path) -> None:
        if not self.db_path.exists():
            raise BackupError(f"Banco SQLite não encontrado em {self.db_path}")
        source = sqlite3.connect(str(self.db_path), timeout=30)
        dest = sqlite3.connect(str(target), timeout=30)
        try:
            source.execute("PRAGMA busy_timeout=30000")
            source.backup(dest, pages=256, sleep=0.02)
            result = dest.execute("PRAGMA integrity_check").fetchone()
            if not result or result[0] != "ok":
                raise BackupError(f"Falha no integrity_check do snapshot: {result}")
            dest.commit()
        finally:
            dest.close()
            source.close()

    def _persistent_dirs(self) -> list[tuple[str, Path]]:
        candidates = [
            ("static_uploads", self.project_root / "static" / "uploads"),
            ("data_uploads", self.db_path.parent / "uploads"),
            ("documents", self.db_path.parent / "documents"),
        ]
        return [(name, path) for name, path in candidates if path.exists() and path.is_dir()]


    def _content_fingerprint(self, snapshot: Path) -> str:
        h = hashlib.sha256()
        h.update(_sha256_file(snapshot).encode("ascii"))
        for name, directory in sorted(self._persistent_dirs(), key=lambda x: x[0]):
            for file in sorted((p for p in directory.rglob("*") if p.is_file()), key=lambda x: x.as_posix()):
                h.update(name.encode("utf-8"))
                h.update(file.relative_to(directory).as_posix().encode("utf-8"))
                h.update(_sha256_file(file).encode("ascii"))
        return h.hexdigest()

    def _build_manifest(self, snapshot: Path, mode: str, note: str = "") -> dict:
        file_dirs = self._persistent_dirs()
        return {
            "format": "flashstock-global-backup",
            "format_version": BACKUP_FORMAT_VERSION,
            "created_at_utc": _utc_now_iso(),
            "mode": mode,
            "note": note[:500],
            "database": {
                "filename": "flashstock.sqlite3",
                "sha256": _sha256_file(snapshot),
                "size_bytes": snapshot.stat().st_size,
                "integrity_check": "ok",
            },
            "files": [
                {"name": name, "archive_path": f"files/{name}", "size_bytes": _dir_size(path)}
                for name, path in file_dirs
            ],
            "contains": [
                "usuarios e senhas criptografadas",
                "funcionarios",
                "perfis e privilegios",
                "clientes e fornecedores",
                "produtos e fotos",
                "estoque e movimentos",
                "pedidos e eventos",
                "compras",
                "financeiro e conciliacao",
                "CRM e solicitacoes do site",
                "logistica, servicos e montagens",
                "fiscal, contratos, configuracoes e auditoria",
            ],
        }

    def _write_zip(self, out_path: Path, snapshot: Path, manifest: dict) -> None:
        with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            zf.write(snapshot, "database/flashstock.sqlite3")
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            for name, directory in self._persistent_dirs():
                for file in directory.rglob("*"):
                    if file.is_file():
                        rel = file.relative_to(directory)
                        zf.write(file, f"files/{name}/{rel.as_posix()}")

    def _prune(self, mode: str, keep: int) -> None:
        files = sorted(self.backup_dir.glob(f"flashstock-{mode}-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[keep:]:
            try:
                old.unlink()
            except OSError:
                pass

    def _prune_storage_cap(self) -> None:
        """Evita que snapshots automáticos ocupem todo o disco persistente."""
        candidates = sorted(
            list(self.backup_dir.glob("flashstock-auto-*.zip")) + list(self.backup_dir.glob("flashstock-pre-restore-*.zip")),
            key=lambda p: p.stat().st_mtime,
        )
        def current_size():
            return sum(p.stat().st_size for p in self.backup_dir.glob("flashstock-*.zip") if p.is_file())
        while len(candidates) > 2 and current_size() > self.max_storage_bytes:
            old = candidates.pop(0)
            try:
                old.unlink()
            except OSError:
                break

    # ---------------------------- public API ----------------------------
    def create_backup(self, mode: str = "manual", note: str = "", skip_if_unchanged: bool = False) -> dict:
        if mode not in {"manual", "auto", "pre-restore"}:
            mode = "manual"
        lock_fh = self._lock()
        try:
            with tempfile.TemporaryDirectory(prefix="flashstock-backup-") as td:
                snapshot = Path(td) / "flashstock.sqlite3"
                self._sqlite_snapshot(snapshot)
                sha = _sha256_file(snapshot)
                content_sha = self._content_fingerprint(snapshot)
                state = self._load_state()

                if skip_if_unchanged and state.get("last_content_sha256") == content_sha:
                    state["last_check_at"] = time.time()
                    self._save_state(state)
                    return {"created": False, "reason": "unchanged", "sha256": sha, "content_sha256": content_sha}

                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                filename = _safe_name(f"flashstock-{mode}-{stamp}.zip")
                out_path = self.backup_dir / filename
                manifest = self._build_manifest(snapshot, mode, note)
                self._write_zip(out_path, snapshot, manifest)

                state.update({
                    "last_check_at": time.time(),
                    "last_backup_at": time.time(),
                    "last_database_sha256": sha,
                    "last_content_sha256": content_sha,
                    "last_backup_file": filename,
                    "last_backup_mode": mode,
                })
                self._save_state(state)

                if mode == "auto":
                    self._prune("auto", self.auto_keep)
                elif mode == "manual":
                    self._prune("manual", self.manual_keep)
                elif mode == "pre-restore":
                    self._prune("pre-restore", 10)
                self._prune_storage_cap()

                return {
                    "created": True,
                    "filename": filename,
                    "path": str(out_path),
                    "size_bytes": out_path.stat().st_size,
                    "sha256": sha,
                    "content_sha256": content_sha,
                    "manifest": manifest,
                }
        finally:
            self._unlock(lock_fh)

    def maybe_auto_backup(self) -> dict:
        lock_fh = self._lock()
        try:
            state = self._load_state()
            last_check = float(state.get("last_check_at") or 0)
            if time.time() - last_check < self.interval_seconds - 5:
                return {"created": False, "reason": "interval"}
        finally:
            self._unlock(lock_fh)
        return self.create_backup(mode="auto", note="Backup automático por alteração detectada.", skip_if_unchanged=True)

    def start_scheduler(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()

        def worker():
            # Primeira verificação após um pequeno atraso para não disputar startup/init-db.
            if self._stop.wait(20):
                return
            while not self._stop.is_set():
                try:
                    self.maybe_auto_backup()
                except Exception as exc:
                    print(f"[Flash Stock Backup] Erro no backup automático: {exc}", flush=True)
                self._stop.wait(min(60, max(15, self.interval_seconds // 6)))

        self._thread = threading.Thread(target=worker, name="flashstock-auto-backup", daemon=True)
        self._thread.start()

    def list_backups(self) -> list[dict]:
        rows = []
        for path in sorted(self.backup_dir.glob("flashstock-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                with zipfile.ZipFile(path, "r") as zf:
                    manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            except Exception:
                manifest = {}
            rows.append({
                "filename": path.name,
                "path": str(path),
                "size_bytes": path.stat().st_size,
                "mtime": datetime.fromtimestamp(path.stat().st_mtime),
                "mode": manifest.get("mode", "desconhecido"),
                "manifest": manifest,
            })
        return rows

    def resolve_backup(self, filename: str) -> Path:
        clean = Path(filename).name
        path = (self.backup_dir / clean).resolve()
        if path.parent != self.backup_dir or not path.exists() or path.suffix.lower() != ".zip":
            raise BackupError("Backup não encontrado.")
        return path

    def validate_backup(self, zip_path: str | Path) -> dict:
        zip_path = Path(zip_path)
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                names = set(zf.namelist())
                if "manifest.json" not in names or "database/flashstock.sqlite3" not in names:
                    raise BackupError("Arquivo não é um backup global válido da Flash Stock.")
                manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
                if manifest.get("format") != "flashstock-global-backup":
                    raise BackupError("Formato de backup incompatível.")
                if int(manifest.get("format_version", 0)) > BACKUP_FORMAT_VERSION:
                    raise BackupError("Backup foi criado por uma versão mais nova do sistema.")
                bad = zf.testzip()
                if bad:
                    raise BackupError(f"Arquivo ZIP corrompido em: {bad}")
                return manifest
        except zipfile.BadZipFile as exc:
            raise BackupError("ZIP inválido ou corrompido.") from exc

    def restore_backup(self, zip_path: str | Path) -> dict:
        zip_path = Path(zip_path)
        manifest = self.validate_backup(zip_path)
        lock_fh = self._lock()
        try:
            # Sempre gera um ponto de retorno antes da restauração.
            # O lock já está obtido, então fazemos o snapshot diretamente aqui.
            with tempfile.TemporaryDirectory(prefix="flashstock-restore-") as td:
                td_path = Path(td)
                incoming_db = td_path / "incoming.sqlite3"
                current_snapshot = td_path / "current.sqlite3"
                self._sqlite_snapshot(current_snapshot)
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                pre_path = self.backup_dir / f"flashstock-pre-restore-{stamp}.zip"
                pre_manifest = self._build_manifest(current_snapshot, "pre-restore", "Criado automaticamente antes de uma restauração.")
                self._write_zip(pre_path, current_snapshot, pre_manifest)

                with zipfile.ZipFile(zip_path, "r") as zf:
                    with zf.open("database/flashstock.sqlite3") as src, incoming_db.open("wb") as dst:
                        shutil.copyfileobj(src, dst)

                    # Extrai somente diretórios de dados conhecidos, impedindo path traversal.
                    extracted_files: dict[str, Path] = {}
                    for member in zf.infolist():
                        if not member.filename.startswith("files/") or member.is_dir():
                            continue
                        parts = Path(member.filename).parts
                        if len(parts) < 3 or parts[1] not in {"static_uploads", "data_uploads", "documents"}:
                            continue
                        rel = Path(*parts[2:])
                        if any(part in {"..", ""} for part in rel.parts):
                            continue
                        base = td_path / "files" / parts[1]
                        target = (base / rel).resolve()
                        if base.resolve() not in target.parents and target != base.resolve():
                            continue
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(member) as src, target.open("wb") as dst:
                            shutil.copyfileobj(src, dst)
                        extracted_files[parts[1]] = base

                conn = sqlite3.connect(str(incoming_db), timeout=30)
                try:
                    integrity = conn.execute("PRAGMA integrity_check").fetchone()
                    if not integrity or integrity[0] != "ok":
                        raise BackupError(f"Banco do backup falhou no integrity_check: {integrity}")
                finally:
                    conn.close()

                # Restauração transacional através da API de backup do SQLite.
                source = sqlite3.connect(str(incoming_db), timeout=30)
                destination = sqlite3.connect(str(self.db_path), timeout=30)
                try:
                    destination.execute("PRAGMA busy_timeout=30000")
                    source.backup(destination, pages=256, sleep=0.02)
                    destination.commit()
                finally:
                    destination.close()
                    source.close()

                destinations = {
                    "static_uploads": self.project_root / "static" / "uploads",
                    "data_uploads": self.db_path.parent / "uploads",
                    "documents": self.db_path.parent / "documents",
                }
                for name, temp_dir in extracted_files.items():
                    dest_dir = destinations[name]
                    if dest_dir.exists():
                        shutil.rmtree(dest_dir)
                    shutil.copytree(temp_dir, dest_dir)

                restored_sha = _sha256_file(incoming_db)
                restored_content_sha = self._content_fingerprint(incoming_db)
                self._save_state({
                    "last_check_at": time.time(),
                    "last_backup_at": time.time(),
                    "last_database_sha256": restored_sha,
                    "last_content_sha256": restored_content_sha,
                    "last_backup_file": Path(zip_path).name,
                    "last_backup_mode": "restore",
                })
                self._prune("pre-restore", 10)
                self._prune_storage_cap()
                return {
                    "restored": True,
                    "manifest": manifest,
                    "pre_restore_backup": pre_path.name,
                }
        finally:
            self._unlock(lock_fh)

    def delete_backup(self, filename: str) -> None:
        path = self.resolve_backup(filename)
        path.unlink()
