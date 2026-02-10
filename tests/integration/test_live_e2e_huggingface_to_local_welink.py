import json
import os
import socket
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
import urllib.error
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src")))


from mrt.http_utils import HttpClient  # noqa: E402
from mrt.notify.welink import WeLinkNotifier  # noqa: E402
from mrt.rules.matcher import RuleMatcher  # noqa: E402
from mrt.runner import Runner  # noqa: E402
from mrt.sources.huggingface import HuggingFaceOrgModelsSource  # noqa: E402
from mrt.state.sqlite_store import SqliteStateStore  # noqa: E402


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

    inner: HuggingFaceOrgModelsSource
    max_events: int

    def key(self) -> str:
        return self.inner.key()

    def poll(self, cursor: str | None):  # noqa: ANN001
        result = self.inner.poll(cursor)
        result.events = result.events[: self.max_events]
        return result


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


@unittest.skipUnless(
    os.environ.get("MRT_RUN_LIVE_TESTS") == "1",
    "Skip live integration tests unless MRT_RUN_LIVE_TESTS=1",
)
class TestLiveE2EHuggingFaceToLocalWeLink(unittest.TestCase):
    """
    真实端到端集成测试（联网 + 下游 HTTP POST）：

    - 上游：真实访问 HuggingFace Hub API
    - 归一：生成 TrackerEvent
    - 规则：关键词匹配（deepseek）
    - 幂等：SQLite state（cursor / seen / alerts）
    - 下游：真实 HTTP POST 到本地模拟 WeLink webhook server

    运行方式：
      MRT_RUN_LIVE_TESTS=1 python -m unittest -v tests.integration.test_live_e2e_huggingface_to_local_welink
    """

    def test_live_poll_generates_events_and_posts_to_welink(self) -> None:
        capture = _CaptureState()

        port = _find_free_port()
        handler = type("Handler", (_WeLinkHandler,), {"capture": capture})
        server = HTTPServer(("127.0.0.1", port), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            with tempfile.TemporaryDirectory() as td:
                db_path = os.path.join(td, "state.sqlite3")
                store = SqliteStateStore(db_path)
                store.ensure_schema()

                http = HttpClient(timeout_seconds=5.0, max_retries=0)
                live_source = HuggingFaceOrgModelsSource(org="deepseek-ai", http=http, token=None)

                sources = (_TruncatingSource(inner=live_source, max_events=2),)
                matcher = RuleMatcher(keywords=("deepseek",))

                webhook_url = (
                    f"http://127.0.0.1:{port}/api/werobot/v1/webhook/send?token=test&channel=standard"
                )
                notifiers = (
                    WeLinkNotifier(
                        webhook_url=webhook_url,
                        http=http,
                        is_at=True,
                        is_at_all=False,
                        at_accounts=("someone@corp",),
                    ),
                )

                runner = Runner(state=store, sources=sources, matcher=matcher, notifiers=notifiers)
                try:
                    runner.run_once()
                except (urllib.error.URLError, OSError) as e:
                    self.skipTest(f"Live network unreachable in this environment: {e}")

                conn = sqlite3.connect(db_path)
                try:
                    alert_count = int(conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0])
                    seen_count = int(conn.execute("SELECT COUNT(*) FROM seen_events").fetchone()[0])
                    cursor = conn.execute("SELECT cursor FROM cursors LIMIT 1").fetchone()
                finally:
                    conn.close()

                self.assertGreaterEqual(alert_count, 1)
                self.assertGreaterEqual(seen_count, alert_count)
                self.assertIsNotNone(cursor)

            with capture.lock:
                received = list(capture.requests)
            self.assertGreaterEqual(len(received), 1)

            payload = received[0]
            self.assertEqual(payload["messageType"], "text")
            self.assertIn("content", payload)
            self.assertIn("timeStamp", payload)
            self.assertIn("uuid", payload)

            text = payload["content"]["text"]
            self.assertIn("@someone@corp", text)
            self.assertTrue(payload.get("isAt"))
            self.assertEqual(payload.get("isAtAll"), False)
            self.assertEqual(payload.get("atAccounts"), ["someone@corp"])
        finally:
            server.shutdown()
            server.server_close()
