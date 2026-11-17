"""Inspect pgAdmin's SQLite database without creating or modifying it."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys


def database_state(path):
    if not path.exists() or path.stat().st_size == 0:
        return {"initialized": False}
    # A marker alone cannot detect a deleted database or interrupted bootstrap.
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if not {"version", "user"}.issubset(tables):
            raise RuntimeError(
                "The existing pgAdmin database is incomplete. Restore a valid "
                "backup or move it aside deliberately before bootstrapping."
            )
        version = connection.execute(
            "SELECT value FROM version WHERE name = 'ConfigDB'"
        ).fetchone()
        users = connection.execute('SELECT COUNT(*) FROM "user"').fetchone()[0]
        if version is None or not users:
            raise RuntimeError(
                "The existing pgAdmin database has no schema version or users. "
                "Inspect it before attempting recovery; it has not been changed."
            )
        return {"initialized": True, "schema_version": version[0]}


if __name__ == "__main__":
    print(json.dumps(database_state(Path(sys.argv[1]))))
