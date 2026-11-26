"""Regression checks for safe bootstrap decisions; no running services required."""

import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest


spec = importlib.util.spec_from_file_location(
    "database_state", Path(__file__).resolve().parents[1] / "files/database_state.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class DatabaseStateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "pgadmin4.db"

    def create_database(self, with_user=True):
        with sqlite3.connect(self.path) as connection:
            connection.executescript(
                'CREATE TABLE version (name TEXT, value INTEGER);'
                "INSERT INTO version VALUES ('ConfigDB', 53);"
                'CREATE TABLE "user" (id INTEGER, email TEXT);'
            )
            if with_user:
                connection.execute(
                    'INSERT INTO "user" VALUES (1, ?)', ("admin@example.org",)
                )

    def test_missing_database_is_not_created_even_with_success_marker(self):
        (self.path.parent / ".ansible-web-configured").touch()
        self.assertFalse(module.database_state(self.path)["initialized"])
        self.assertFalse(self.path.exists())

    def test_empty_database_can_be_bootstrapped_without_modification(self):
        self.path.touch()
        self.assertFalse(module.database_state(self.path)["initialized"])
        self.assertEqual(self.path.stat().st_size, 0)

    def test_initialized_database_is_read_without_modification(self):
        self.create_database()
        before = self.path.read_bytes()
        modified = self.path.stat().st_mtime_ns
        self.assertEqual(
            module.database_state(self.path),
            {"initialized": True, "schema_version": 53},
        )
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.path.stat().st_mtime_ns, modified)

    def test_nonempty_incomplete_database_is_preserved(self):
        with sqlite3.connect(self.path) as connection:
            connection.execute("CREATE TABLE existing_customer_data (value TEXT)")
        before = self.path.read_bytes()
        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            module.database_state(self.path)
        self.assertEqual(self.path.read_bytes(), before)

    def test_database_without_users_requires_explicit_recovery(self):
        self.create_database(with_user=False)
        with self.assertRaisesRegex(RuntimeError, "no schema version or users"):
            module.database_state(self.path)

    def test_corrupt_database_is_preserved(self):
        self.path.write_bytes(b"Do not replace this damaged customer database")
        before = self.path.read_bytes()
        with self.assertRaises(sqlite3.DatabaseError):
            module.database_state(self.path)
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
