import os
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
class FakeSource:
    """
    纯内存 Source：
    - 根据 cursor 返回预设事件列表
    - 用于 Runner 端到端演示（不依赖真实网络平台）
    """

    _key: str
    events_by_cursor: dict[str | None, list[TrackerEvent]]
    cursor_after: str | None

    def key(self) -> str:
        return self._key

    def poll(self, cursor: str | None) -> PollResult:
        return PollResult(events=list(self.events_by_cursor.get(cursor, [])), new_cursor=self.cursor_after)


@dataclass
class FakeNotifier:
    """
    纯内存 Notifier：将发送过的 Alert 收集到列表中，便于断言。
    """

    sent: list[Alert]

    def channel(self) -> str:
        return "fake"

    def send(self, alert: Alert) -> None:
        self.sent.append(alert)


class TestRunnerE2E(unittest.TestCase):
    def test_runner_dedupe_and_cursor(self) -> None:
        """
        端到端演示：
        - 第一次 run_once 发送告警 + 写入 cursor
        - 第二次 run_once 由于 fingerprint 已 seen，不会重复告警
        """
        t = datetime(2026, 2, 10, 0, 0, tzinfo=UTC)
        e1 = TrackerEvent(
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
            notifier = FakeNotifier(sent=[])
            src = FakeSource(_key="s1", events_by_cursor={None: [e1], "c1": [e1]}, cursor_after="c1")

            runner = Runner(
                state=store,
                sources=(src,),
                matcher=RuleMatcher(keywords=("deepseek",)),
                notifiers=(notifier,),
            )

            runner.run_once()
            self.assertEqual(len(notifier.sent), 1)
            self.assertEqual(store.get_cursor("s1"), "c1")

            runner.run_once()
            self.assertEqual(len(notifier.sent), 1)
