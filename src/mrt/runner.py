from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from .config import AppConfig
from .http_utils import HttpClient
from .models import Alert, TrackerEvent
from .notify.email import EmailNotifier
from .notify.formatter import format_alert_text
from .notify.welink import WeLinkNotifier
from .rules.matcher import RuleMatcher
from .sources.github import GitHubRepoIssuesSource, GitHubRepoPullsSource
from .sources.huggingface import HuggingFaceOrgModelsSource
from .sources.modelscope import ModelScopeOrgModelsSource
from .state.sqlite_store import SqliteStateStore


logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


@dataclass(slots=True)
class SourceRunReport:
    source_key: str
    source_type: str
    cursor_before: str | None
    cursor_after: str | None
    events_fetched: int
    events_processed: int
    events_skipped_seen: int
    events_matched: int
    alerts_created: int
    notify_attempts: int
    notify_successes: int
    notify_failures: int
    error: str | None
    duration_ms: int


@dataclass(slots=True)
class RunOnceReport:
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    sources: tuple[SourceRunReport, ...]
    events_fetched: int
    events_processed: int
    events_skipped_seen: int
    events_matched: int
    alerts_created: int
    notify_attempts: int
    notify_successes: int
    notify_failures: int
    source_errors: int


@dataclass(slots=True)
class _ProcessEventReport:
    processed: bool
    skipped_seen: bool
    matched: bool
    alert_created: bool
    notify_attempts: int
    notify_successes: int
    notify_failures: int


@dataclass(slots=True)
class Runner:
    """
    核心执行器：负责一次轮询周期内的完整数据流闭环：
    Source -> Rules -> State(dedupe) -> Notify -> State(persist)
    """

    state: SqliteStateStore
    sources: tuple[object, ...]
    matcher: RuleMatcher
    notifiers: tuple[object, ...]
    record_unmatched_as_seen: bool = True

    def run_once(self) -> RunOnceReport:
        """
        执行一个轮询周期（单次）。

        执行顺序：
        - 对每个 source 读取 cursor
        - 拉取增量 events 与 new_cursor
        - 逐条事件：去重 -> 规则匹配 ->（命中则通知）-> 持久化 seen
        - 最后持久化 cursor
        """
        started_at = _utc_now()
        start_t = time.monotonic()

        self.state.ensure_schema()

        source_reports: list[SourceRunReport] = []
        totals = {
            "events_fetched": 0,
            "events_processed": 0,
            "events_skipped_seen": 0,
            "events_matched": 0,
            "alerts_created": 0,
            "notify_attempts": 0,
            "notify_successes": 0,
            "notify_failures": 0,
            "source_errors": 0,
        }

        for source in self.sources:
            source_key = source.key()
            cursor = self.state.get_cursor(source_key)

            source_start_t = time.monotonic()
            error: str | None = None
            cursor_after: str | None = cursor
            events_fetched = 0
            events_processed = 0
            events_skipped_seen = 0
            events_matched = 0
            alerts_created = 0
            notify_attempts = 0
            notify_successes = 0
            notify_failures = 0

            try:
                result = source.poll(cursor)
                events = list(result.events)
                events_fetched = len(events)
                cursor_after = result.new_cursor if result.new_cursor is not None else cursor
            except Exception as e:  # noqa: BLE001
                error = f"{type(e).__name__}: {e}"
                totals["source_errors"] += 1
                logger.exception(
                    "source poll failed: source_key=%s source_type=%s cursor=%r",
                    source_key,
                    type(source).__name__,
                    cursor,
                )
                source_reports.append(
                    SourceRunReport(
                        source_key=source_key,
                        source_type=type(source).__name__,
                        cursor_before=cursor,
                        cursor_after=cursor_after,
                        events_fetched=0,
                        events_processed=0,
                        events_skipped_seen=0,
                        events_matched=0,
                        alerts_created=0,
                        notify_attempts=0,
                        notify_successes=0,
                        notify_failures=0,
                        error=error,
                        duration_ms=int((time.monotonic() - source_start_t) * 1000),
                    )
                )
                continue

            # 排序保证通知顺序稳定（避免同一批事件在不同运行中顺序抖动）。
            events.sort(key=lambda e: (e.occurred_at or e.observed_at, e.fingerprint()))
            for event in events:
                r = self._process_event(event)
                if not r.processed:
                    continue
                events_processed += 1
                if r.skipped_seen:
                    events_skipped_seen += 1
                if r.matched:
                    events_matched += 1
                if r.alert_created:
                    alerts_created += 1
                notify_attempts += r.notify_attempts
                notify_successes += r.notify_successes
                notify_failures += r.notify_failures

            if result.new_cursor is not None:
                self.state.set_cursor(source_key, result.new_cursor)

            source_reports.append(
                SourceRunReport(
                    source_key=source_key,
                    source_type=type(source).__name__,
                    cursor_before=cursor,
                    cursor_after=cursor_after,
                    events_fetched=events_fetched,
                    events_processed=events_processed,
                    events_skipped_seen=events_skipped_seen,
                    events_matched=events_matched,
                    alerts_created=alerts_created,
                    notify_attempts=notify_attempts,
                    notify_successes=notify_successes,
                    notify_failures=notify_failures,
                    error=error,
                    duration_ms=int((time.monotonic() - source_start_t) * 1000),
                )
            )

            totals["events_fetched"] += events_fetched
            totals["events_processed"] += events_processed
            totals["events_skipped_seen"] += events_skipped_seen
            totals["events_matched"] += events_matched
            totals["alerts_created"] += alerts_created
            totals["notify_attempts"] += notify_attempts
            totals["notify_successes"] += notify_successes
            totals["notify_failures"] += notify_failures

        finished_at = _utc_now()
        duration_ms = int((time.monotonic() - start_t) * 1000)
        return RunOnceReport(
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            sources=tuple(source_reports),
            events_fetched=totals["events_fetched"],
            events_processed=totals["events_processed"],
            events_skipped_seen=totals["events_skipped_seen"],
            events_matched=totals["events_matched"],
            alerts_created=totals["alerts_created"],
            notify_attempts=totals["notify_attempts"],
            notify_successes=totals["notify_successes"],
            notify_failures=totals["notify_failures"],
            source_errors=totals["source_errors"],
        )

    def _process_event(self, event: TrackerEvent) -> _ProcessEventReport:
        fp = event.fingerprint()
        if self.state.has_seen(fp):
            return _ProcessEventReport(
                processed=True,
                skipped_seen=True,
                matched=False,
                alert_created=False,
                notify_attempts=0,
                notify_successes=0,
                notify_failures=0,
            )

        matches = self.matcher.match(event)
        if not matches:
            if self.record_unmatched_as_seen:
                self.state.mark_seen(fp)
            return _ProcessEventReport(
                processed=True,
                skipped_seen=False,
                matched=False,
                alert_created=False,
                notify_attempts=0,
                notify_successes=0,
                notify_failures=0,
            )

        channels = tuple(n.channel() for n in self.notifiers)
        alert = Alert(
            fingerprint=fp,
            event=event,
            matched_rules=matches,
            channels=channels,
            content="",
            created_at=_utc_now(),
        )
        alert = Alert(
            fingerprint=alert.fingerprint,
            event=alert.event,
            matched_rules=alert.matched_rules,
            channels=alert.channels,
            content=format_alert_text(alert),
            created_at=alert.created_at,
        )

        self.state.save_alert(alert)

        notify_attempts = 0
        notify_successes = 0
        notify_failures = 0
        for notifier in self.notifiers:
            channel = notifier.channel()
            if channel not in alert.channels:
                continue
            notify_attempts += 1
            try:
                notifier.send(alert)
                notify_successes += 1
            except Exception as e:  # noqa: BLE001
                notify_failures += 1
                self.state.record_notify_failure(
                    fingerprint=fp,
                    channel=channel,
                    error=f"{type(e).__name__}: {e}",
                )
                logger.exception(
                    "notify failed: channel=%s notifier_type=%s fingerprint=%s event_source=%s event_type=%s url=%s",
                    channel,
                    type(notifier).__name__,
                    fp,
                    event.source,
                    event.event_type,
                    event.url,
                )

        self.state.mark_seen(fp)
        return _ProcessEventReport(
            processed=True,
            skipped_seen=False,
            matched=True,
            alert_created=True,
            notify_attempts=notify_attempts,
            notify_successes=notify_successes,
            notify_failures=notify_failures,
        )


def build_runner(config: AppConfig) -> Runner:
    """
    根据配置构建可运行的 Runner。

    设计取舍（v0）：
    - 统一在这里做“配置 -> 实例”的装配，Runner 内只关注流程编排
    - 对 secret/token 只通过环境变量读取，避免落盘
    """
    http = HttpClient()
    state = SqliteStateStore(config.sqlite_path)

    sources: list[object] = []
    if config.github and config.github.repos:
        gh_token = config.resolve_env(config.github.token_env)
        for repo in config.github.repos:
            if config.github.monitor_issues:
                sources.append(GitHubRepoIssuesSource(repo=repo, http=http, token=gh_token))
            if config.github.monitor_pulls:
                sources.append(GitHubRepoPullsSource(repo=repo, http=http, token=gh_token))

    if config.huggingface and config.huggingface.orgs:
        hf_token = config.resolve_env(config.huggingface.token_env)
        for org in config.huggingface.orgs:
            sources.append(HuggingFaceOrgModelsSource(org=org, http=http, token=hf_token))

    if config.modelscope and config.modelscope.orgs:
        for org in config.modelscope.orgs:
            sources.append(ModelScopeOrgModelsSource(org=org, http=http))

    matcher = RuleMatcher(keywords=config.watch_keywords)

    notifiers: list[object] = []
    if config.welink:
        webhook_url = config.resolve_env(config.welink.webhook_env)
        if webhook_url:
            notifiers.append(
                WeLinkNotifier(
                    webhook_url=webhook_url,
                    http=http,
                    is_at=config.welink.is_at,
                    is_at_all=config.welink.is_at_all,
                    at_accounts=config.welink.at_accounts,
                )
            )

    if config.email:
        username = config.resolve_env(config.email.user_env) or ""
        password = config.resolve_env(config.email.password_env) or ""
        if config.email.smtp_host and config.email.to_list:
            notifiers.append(
                EmailNotifier(
                    smtp_host=config.email.smtp_host,
                    smtp_port=config.email.smtp_port,
                    username=username,
                    password=password,
                    to_list=config.email.to_list,
                    use_tls=config.email.use_tls,
                )
            )

    return Runner(
        state=state,
        sources=tuple(sources),
        matcher=matcher,
        notifiers=tuple(notifiers),
    )
