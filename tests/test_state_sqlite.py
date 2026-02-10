import os
import sys
import tempfile
import unittest


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))


from mrt.state.sqlite_store import SqliteStateStore  # noqa: E402


class TestSqliteStateStore(unittest.TestCase):
    def test_seen_dedupe(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "state.sqlite3")
            store = SqliteStateStore(db)
            store.ensure_schema()

            fp = "abc"
            self.assertFalse(store.has_seen(fp))
            store.mark_seen(fp)
            self.assertTrue(store.has_seen(fp))

            store.mark_seen(fp)
            self.assertTrue(store.has_seen(fp))

    def test_cursor_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "state.sqlite3")
            store = SqliteStateStore(db)
            store.ensure_schema()

            self.assertIsNone(store.get_cursor("s1"))
            store.set_cursor("s1", '{"x":1}')
            self.assertEqual(store.get_cursor("s1"), '{"x":1}')

