import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

import logging

from mrt.models import Alert, TrackerEvent
from mrt.rules.matcher import RuleMatcher
from mrt.runner import Runner
from mrt.sources.base import PollResult
from mrt.state.sqlite_store import SqliteStateStore


@dataclass
class _OneShotSource:
    event: TrackerEvent

    def key(self) -> str:
        return "s1"

    def poll(self, cursor: str | None) -> PollResult:
        return PollResult(events=[self.event] if cursor is None else [], new_cursor="c1")


@dataclass
class _FailingNotifier:
    def channel(self) -> str:
        return "fail"

    def send(self, alert: Alert) -> None:  # noqa: ARG002
        raise RuntimeError("boom")

def test_notify_failure_is_recorded(tmp_path, caplog) -> None:  # noqa: ANN001
    t = datetime(2026, 2, 10, 0, 0, tzinfo=UTC)
    event = TrackerEvent(
        source="github",
        resource_type="repo_issue",
        resource_id="a/b",
        event_type="issue_updated",
        event_id="1",
        title="DeepSeek update",
        summary="",
        url="https://example.com/1",
        occurred_at=t,
        observed_at=t,
        raw=None,
    )

    db = tmp_path / "state.sqlite3"
    store = SqliteStateStore(str(db))
    runner = Runner(
        state=store,
        sources=(_OneShotSource(event=event),),
        matcher=RuleMatcher(keywords=("deepseek",)),
        notifiers=(_FailingNotifier(),),
    )

    caplog.set_level(logging.ERROR)
    report = runner.run_once()
    assert report.notify_failures == 1
    assert "notify failed" in caplog.text

    conn = sqlite3.connect(str(db))
    try:
        row = conn.execute("SELECT COUNT(*) FROM notify_failures").fetchone()
    finally:
        conn.close()

    assert row[0] == 1
