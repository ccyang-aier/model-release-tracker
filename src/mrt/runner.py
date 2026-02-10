from __future__ import annotations

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


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


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

    def run_once(self) -> None:
        """
        执行一个轮询周期（单次）。

        执行顺序：
        - 对每个 source 读取 cursor
        - 拉取增量 events 与 new_cursor
        - 逐条事件：去重 -> 规则匹配 ->（命中则通知）-> 持久化 seen
        - 最后持久化 cursor
        """
        self.state.ensure_schema()

        for source in self.sources:
            source_key = source.key()
            cursor = self.state.get_cursor(source_key)

            result = source.poll(cursor)
            events = list(result.events)

            # 排序保证通知顺序稳定（避免同一批事件在不同运行中顺序抖动）。
            events.sort(key=lambda e: (e.occurred_at or e.observed_at, e.fingerprint()))
            for event in events:
                self._process_event(event)

            if result.new_cursor is not None:
                self.state.set_cursor(source_key, result.new_cursor)

    def _process_event(self, event: TrackerEvent) -> None:
        fp = event.fingerprint()
        if self.state.has_seen(fp):
            return

        matches = self.matcher.match(event)
        if not matches:
            if self.record_unmatched_as_seen:
                self.state.mark_seen(fp)
            return

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

        for notifier in self.notifiers:
            channel = notifier.channel()
            if channel not in alert.channels:
                continue
            try:
                notifier.send(alert)
            except Exception as e:  # noqa: BLE001
                self.state.record_notify_failure(fingerprint=fp, channel=channel, error=str(e))

        self.state.mark_seen(fp)


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
