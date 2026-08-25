import sqlite3
from pathlib import Path

from services.backup import GlobalBackupManager


def test_backup_change_detection_and_restore(tmp_path: Path):
    db_path = tmp_path / "flashstock.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO sample(value) VALUES ('original')")
    conn.commit()
    conn.close()

    manager = GlobalBackupManager(db_path, tmp_path / "backups", tmp_path, interval_seconds=300)
    manual = manager.create_backup("manual")
    assert manual["created"] is True

    unchanged = manager.create_backup("auto", skip_if_unchanged=True)
    assert unchanged["created"] is False

    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO sample(value) VALUES ('novo')")
    conn.commit()
    conn.close()
    changed = manager.create_backup("auto", skip_if_unchanged=True)
    assert changed["created"] is True

    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM sample")
    conn.commit()
    conn.close()

    manager.restore_backup(manual["path"])
    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM sample").fetchone()[0]
    conn.close()
    assert count == 1
