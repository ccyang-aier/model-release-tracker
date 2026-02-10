import os
import sqlite3
import sys
import tempfile
import unittest
from dataclasses import dataclass
from datetime import UTC, datetime


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))


from mrt.models import Alert, TrackerEvent  # noqa: E402
from mrt.rules.matcher import RuleMatcher  # noqa: E402
from mrt.runner import Runner  # noqa: E402
from mrt.sources.base import PollResult  # noqa: E402
from mrt.state.sqlite_store import SqliteStateStore  # noqa: E402


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


class TestNotifyFailures(unittest.TestCase):
    def test_notify_failure_is_recorded(self) -> None:
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

        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "state.sqlite3")
            store = SqliteStateStore(db)
            runner = Runner(
                state=store,
                sources=(_OneShotSource(event=event),),
                matcher=RuleMatcher(keywords=("deepseek",)),
                notifiers=(_FailingNotifier(),),
            )

            runner.run_once()

            conn = sqlite3.connect(db)
            try:
                row = conn.execute("SELECT COUNT(*) FROM notify_failures").fetchone()
            finally:
                conn.close()

        self.assertEqual(row[0], 1)

