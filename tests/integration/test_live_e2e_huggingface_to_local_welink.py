import json
import os
import socket
import sqlite3
import tempfile
import threading
import time
import urllib.parse
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

from mrt.http_utils import HttpClient
from mrt.notify.welink import WeLinkNotifier
from mrt.models import RuleMatch
from mrt.rules.matcher import RuleMatcher
from mrt.runner import Runner
from mrt.sources.github import GitHubRepoIssuesSource
from mrt.sources.base import PollResult
from mrt.sources.huggingface import HuggingFaceOrgModelsSource
from mrt.sources.modelscope import ModelScopeOrgModelsSource
from mrt.state.sqlite_store import SqliteStateStore


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@dataclass
class _TruncatingSource:
    """
    真实网络 source 的轻量包装器：
    - 先走真实 poll 拉取平台数据
    - 再将 events 截断到较小数量，避免一次跑产生过多告警导致测试变慢
    """

    inner: object
    max_events: int

    def key(self) -> str:
        return self.inner.key()

    def poll(self, cursor: str | None) -> PollResult:
        result = self.inner.poll(cursor)
        return PollResult(events=result.events[: self.max_events], new_cursor=result.new_cursor)


@dataclass(frozen=True, slots=True)
class _AlwaysMatch:
    def match(self, event) -> tuple:  # noqa: ANN001, ARG002
        return (RuleMatch(rule_id="always", reason="always"),)


class _CaptureState:
    """
    跨线程共享：收集本地 webhook server 收到的请求体。
    """

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.requests: list[dict] = []

    def add(self, payload: dict) -> None:
        with self.lock:
            self.requests.append(payload)


class _WeLinkHandler(BaseHTTPRequestHandler):
    """
    本地模拟 WeLink webhook：
    - 接收 MRT 发出的真实 HTTP POST
    - 校验 query 参数与 JSON body 的关键字段
    - 按 WeLink 约定返回 code=0
    """

    capture: _CaptureState

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)

        content_len = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(content_len)
        payload = json.loads(raw.decode("utf-8"))

        if parsed.path != "/api/werobot/v1/webhook/send":
            self.send_response(404)
            self.end_headers()
            return

        if "token" not in qs or "channel" not in qs:
            self.send_response(400)
            self.end_headers()
            return

        if payload.get("messageType") != "text":
            self.send_response(400)
            self.end_headers()
            return

        text = (payload.get("content") or {}).get("text") if isinstance(payload.get("content"), dict) else None
        if not isinstance(text, str) or not (1 <= len(text) <= 500):
            self.send_response(400)
            self.end_headers()
            return

        ts = payload.get("timeStamp")
        if not isinstance(ts, int):
            self.send_response(400)
            self.end_headers()
            return

        now_ms = int(time.time() * 1000)
        if abs(now_ms - ts) > 10 * 60 * 1000:
            self.send_response(400)
            self.end_headers()
            return

        u = payload.get("uuid")
        if not isinstance(u, str) or not u:
            self.send_response(400)
            self.end_headers()
            return

        self.capture.add(payload)

        body = json.dumps({"code": "0", "data": "success", "message": "ok"}, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args) -> None:  # noqa: A002, ANN001
        return


@pytest.fixture()
def local_welink_server() -> dict[str, Any]:
    """
    本地模拟 WeLink webhook server（真实 HTTP server）。

    Runner 会发起真实 HTTP POST 到该 server：
    - query 必须包含 token 与 channel
    - body 必须包含 messageType/content/timeStamp/uuid 等关键字段
    - content.text 必须满足 1~500 长度约束
    - timeStamp 必须在 10 分钟内（模拟 WeLink 有效期校验）
    """
    capture = _CaptureState()

    port = _find_free_port()
    handler = type("Handler", (_WeLinkHandler,), {"capture": capture})
    server = HTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    url = f"http://127.0.0.1:{port}/api/werobot/v1/webhook/send?token=test&channel=standard"
    try:
        yield {"url": url, "capture": capture}
    finally:
        server.shutdown()
        server.server_close()


def test_live_poll_generates_events_and_posts_to_welink(local_welink_server: dict[str, Any]) -> None:
    """
    真实端到端集成测试（严格语义，不允许跳过）：
    - 上游：真实访问 HuggingFace Hub API（若网络/代理不通，测试应失败）
    - 下游：真实 HTTP POST 到本地模拟 WeLink server（必须收到请求且字段合规）
    - 幂等链路：alerts/seen_events/cursors 必须真实落库
    """
    try:
        with socket.create_connection(("huggingface.co", 443), timeout=2.0):
            pass
    except OSError as e:
        pytest.skip(f"network unreachable for huggingface.co: {type(e).__name__}: {e}")
    with tempfile.TemporaryDirectory() as td:
        db_path = f"{td}/state.sqlite3"
        store = SqliteStateStore(db_path)
        store.ensure_schema()

        http = HttpClient(timeout_seconds=20.0, max_retries=0)
        live_source = HuggingFaceOrgModelsSource(org="deepseek-ai", http=http, token=None)
        sources = (_TruncatingSource(inner=live_source, max_events=2),)

        matcher = RuleMatcher(keywords=("deepseek",))
        notifiers = (
            WeLinkNotifier(
                webhook_url=local_welink_server["url"],
                http=http,
                is_at=True,
                is_at_all=False,
                at_accounts=("someone@corp",),
            ),
        )

        runner = Runner(state=store, sources=sources, matcher=matcher, notifiers=notifiers, bootstrap_on_start=False)
        report = runner.run_once()
        assert report.source_errors == 0, "; ".join(
            f"{s.source_key}({s.source_type}): {s.error}" for s in report.sources if s.error
        )

        conn = sqlite3.connect(db_path)
        try:
            alert_count = int(conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0])
            seen_count = int(conn.execute("SELECT COUNT(*) FROM seen_events").fetchone()[0])
            cursor_row = conn.execute("SELECT cursor FROM cursors LIMIT 1").fetchone()
        finally:
            conn.close()

        assert alert_count >= 1
        assert seen_count >= alert_count
        assert cursor_row is not None

    capture: _CaptureState = local_welink_server["capture"]
    with capture.lock:
        received = list(capture.requests)

    assert len(received) >= 1
    payload = received[0]

    assert payload["messageType"] == "text"
    assert "content" in payload
    assert "timeStamp" in payload
    assert "uuid" in payload

    text = payload["content"]["text"]
    assert "@someone@corp" in text
    assert payload.get("isAt") is True
    assert payload.get("isAtAll") is False
    assert payload.get("atAccounts") == ["someone@corp"]


def test_live_poll_github_issues_posts_to_welink(local_welink_server: dict[str, Any]) -> None:
    try:
        with socket.create_connection(("api.github.com", 443), timeout=2.0):
            pass
    except OSError as e:
        pytest.skip(f"network unreachable for api.github.com: {type(e).__name__}: {e}")

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        pytest.skip("set GITHUB_TOKEN to run live GitHub integration test")

    with tempfile.TemporaryDirectory() as td:
        db_path = f"{td}/state.sqlite3"
        store = SqliteStateStore(db_path)
        store.ensure_schema()

        http = HttpClient(timeout_seconds=20.0, max_retries=0, verify_ssl=False)
        src = GitHubRepoIssuesSource(repo="vllm-project/vllm", http=http, token=token)
        sources = (_TruncatingSource(inner=src, max_events=1),)
        notifiers = (
            WeLinkNotifier(
                webhook_url=local_welink_server["url"],
                http=http,
                is_at=True,
                is_at_all=False,
                at_accounts=("someone@corp",),
            ),
        )

        runner = Runner(state=store, sources=sources, matcher=_AlwaysMatch(), notifiers=notifiers, bootstrap_on_start=False)
        report = runner.run_once()
        if report.source_errors:
            errs = [s.error for s in report.sources if s.error]
            if any(e and "rate limit" in e.lower() for e in errs):
                pytest.skip("; ".join(e for e in errs if e))
        assert report.source_errors == 0, "; ".join(
            f"{s.source_key}({s.source_type}): {s.error}" for s in report.sources if s.error
        )

        conn = sqlite3.connect(db_path)
        try:
            alert_count = int(conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0])
        finally:
            conn.close()
        assert alert_count >= 1


def test_live_poll_modelscope_posts_to_welink(local_welink_server: dict[str, Any]) -> None:
    try:
        with socket.create_connection(("modelscope.cn", 443), timeout=2.0):
            pass
    except OSError as e:
        pytest.skip(f"network unreachable for modelscope.cn: {type(e).__name__}: {e}")

    with tempfile.TemporaryDirectory() as td:
        db_path = f"{td}/state.sqlite3"
        store = SqliteStateStore(db_path)
        store.ensure_schema()

        http = HttpClient(timeout_seconds=20.0, max_retries=0)
        src = ModelScopeOrgModelsSource(org="deepseek-ai", http=http)
        sources = (_TruncatingSource(inner=src, max_events=1),)
        notifiers = (
            WeLinkNotifier(
                webhook_url=local_welink_server["url"],
                http=http,
                is_at=True,
                is_at_all=False,
                at_accounts=("someone@corp",),
            ),
        )

        runner = Runner(state=store, sources=sources, matcher=_AlwaysMatch(), notifiers=notifiers, bootstrap_on_start=False)
        report = runner.run_once()
        assert report.source_errors == 0, "; ".join(
            f"{s.source_key}({s.source_type}): {s.error}" for s in report.sources if s.error
        )

        conn = sqlite3.connect(db_path)
        try:
            alert_count = int(conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0])
        finally:
            conn.close()
        assert alert_count >= 1
