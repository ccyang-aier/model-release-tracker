from mrt.state.sqlite_store import SqliteStateStore


def test_seen_dedupe(tmp_path) -> None:  # noqa: ANN001
    db = tmp_path / "state.sqlite3"
    store = SqliteStateStore(str(db))
    store.ensure_schema()

    fp = "abc"
    assert store.has_seen(fp) is False
    store.mark_seen(fp)
    assert store.has_seen(fp) is True

    store.mark_seen(fp)
    assert store.has_seen(fp) is True


def test_cursor_roundtrip(tmp_path) -> None:  # noqa: ANN001
    db = tmp_path / "state.sqlite3"
    store = SqliteStateStore(str(db))
    store.ensure_schema()

    assert store.get_cursor("s1") is None
    store.set_cursor("s1", '{"x":1}')
    assert store.get_cursor("s1") == '{"x":1}'
