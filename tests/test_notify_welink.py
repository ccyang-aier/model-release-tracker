import json
from unittest import mock

import pytest

from mrt.notify.welink import WeLinkNotifier


class _FakeResponse:
    """
    模拟 urllib.request.urlopen 返回的 response 对象。
    - 支持 context manager
    - 支持 .read() 与 .status
    """

    def __init__(self, *, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        return None


def test_build_payload_aligns_with_usecase_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    notifier = WeLinkNotifier(
        webhook_url="https://open.welink.huaweicloud.com/api/werobot/v1/webhook/send?token=x&channel=standard",
        http=object(),  # HttpClient 不参与 POST
        is_at=True,
        is_at_all=False,
        at_accounts=("u1@corp",),
    )

    monkeypatch.setattr("time.time", lambda: 100.0)
    monkeypatch.setattr("uuid.uuid4", lambda: mock.Mock(hex="abc"))
    payload = notifier._build_payload("hello")  # noqa: SLF001

    assert payload["messageType"] == "text"
    assert payload["uuid"] == "abc"
    assert payload["timeStamp"] == 100000
    assert payload["isAt"] is True
    assert payload["isAtAll"] is False
    assert payload["atAccounts"] == ["u1@corp"]
    assert "@u1@corp" in payload["content"]["text"]


def test_at_all_prefix_and_flags() -> None:
    notifier = WeLinkNotifier(
        webhook_url="https://open.welink.huaweicloud.com/api/werobot/v1/webhook/send?token=x&channel=standard",
        http=object(),
        is_at=False,
        is_at_all=True,
        at_accounts=(),
    )
    payload = notifier._build_payload("ping")  # noqa: SLF001
    assert payload["isAtAll"] is True
    assert payload["isAt"] is False
    assert payload["content"]["text"].startswith("@all ")


def test_send_checks_response_code(monkeypatch: pytest.MonkeyPatch) -> None:
    notifier = WeLinkNotifier(
        webhook_url="https://open.welink.huaweicloud.com/api/werobot/v1/webhook/send?token=x&channel=standard",
        http=object(),
    )
    ok_body = json.dumps({"code": "0", "data": "success", "message": "ok"}).encode("utf-8")
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _FakeResponse(status=200, body=ok_body))
    notifier.send(alert=mock.Mock(content="hi"))  # type: ignore[arg-type]

    bad_body = json.dumps({"code": "58601", "data": "", "message": "参数错误"}).encode("utf-8")
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _FakeResponse(status=200, body=bad_body))
    with pytest.raises(RuntimeError):
        notifier.send(alert=mock.Mock(content="hi"))  # type: ignore[arg-type]


def test_send_passes_ssl_context(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = {}

    def _fake_urlopen(*_a, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        ok_body = json.dumps({"code": "0", "data": "success", "message": "ok"}).encode("utf-8")
        return _FakeResponse(status=200, body=ok_body)

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    notifier = WeLinkNotifier(
        webhook_url="https://open.welink.huaweicloud.com/api/werobot/v1/webhook/send?token=x&channel=standard",
        http=object(),
    )
    notifier.send(alert=mock.Mock(content="hi"))  # type: ignore[arg-type]
    assert "context" in captured


def test_text_is_truncated_to_500_chars() -> None:
    notifier = WeLinkNotifier(
        webhook_url="https://open.welink.huaweicloud.com/api/werobot/v1/webhook/send?token=x&channel=standard",
        http=object(),
    )
    text = "x" * 1000
    payload = notifier._build_payload(text)  # noqa: SLF001
    assert len(payload["content"]["text"]) <= 500
