from dataclasses import dataclass
from datetime import UTC, datetime

import logging

from mrt.models import Alert, TrackerEvent
from mrt.rules.matcher import RuleMatcher
from mrt.runner import Runner
from mrt.sources.base import PollResult
from mrt.state.sqlite_store import SqliteStateStore


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


def test_runner_dedupe_and_cursor(tmp_path) -> None:  # noqa: ANN001
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

    db = tmp_path / "state.sqlite3"
    store = SqliteStateStore(str(db))
    notifier = FakeNotifier(sent=[])
    src = FakeSource(_key="s1", events_by_cursor={None: [e1], "c1": [e1]}, cursor_after="c1")

    runner = Runner(
        state=store,
        sources=(src,),
        matcher=RuleMatcher(keywords=("deepseek",)),
        notifiers=(notifier,),
    )

    report1 = runner.run_once()
    assert len(notifier.sent) == 1
    assert store.get_cursor("s1") == "c1"
    assert report1.events_fetched == 1
    assert report1.events_processed == 1
    assert report1.events_matched == 1
    assert report1.alerts_created == 1
    assert report1.notify_attempts == 1
    assert report1.notify_successes == 1
    assert report1.notify_failures == 0

    report2 = runner.run_once()
    assert len(notifier.sent) == 1
    assert report2.events_fetched == 1
    assert report2.events_processed == 1
    assert report2.events_skipped_seen == 1
    assert report2.alerts_created == 0


@dataclass
class _FailingSource:
    def key(self) -> str:
        return "boom"

    def poll(self, cursor: str | None) -> PollResult:  # noqa: ARG002
        raise RuntimeError("poll failed")


def test_runner_source_poll_exception_is_caught(tmp_path, caplog) -> None:  # noqa: ANN001
    db = tmp_path / "state.sqlite3"
    store = SqliteStateStore(str(db))
    runner = Runner(
        state=store,
        sources=(_FailingSource(),),
        matcher=RuleMatcher(keywords=("deepseek",)),
        notifiers=(),
    )

    caplog.set_level(logging.ERROR)
    report = runner.run_once()
    assert report.source_errors == 1
    assert "source poll failed" in caplog.text
