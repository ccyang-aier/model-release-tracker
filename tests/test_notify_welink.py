import json
import os
import sys
import unittest
from unittest import mock


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))


from mrt.notify.welink import WeLinkNotifier  # noqa: E402


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


class TestWeLinkNotifier(unittest.TestCase):
    def test_build_payload_aligns_with_usecase_spec(self) -> None:
        notifier = WeLinkNotifier(
            webhook_url="https://open.welink.huaweicloud.com/api/werobot/v1/webhook/send?token=x&channel=standard",
            http=object(),  # HttpClient 不参与 POST
            is_at=True,
            is_at_all=False,
            at_accounts=("u1@corp",),
        )

        with mock.patch("time.time", return_value=100.0), mock.patch("uuid.uuid4") as m_uuid:
            m_uuid.return_value.hex = "abc"
            payload = notifier._build_payload("hello")  # noqa: SLF001

        self.assertEqual(payload["messageType"], "text")
        self.assertEqual(payload["uuid"], "abc")
        self.assertEqual(payload["timeStamp"], 100000)
        self.assertEqual(payload["isAt"], True)
        self.assertEqual(payload["isAtAll"], False)
        self.assertEqual(payload["atAccounts"], ["u1@corp"])
        self.assertIn("@u1@corp", payload["content"]["text"])

    def test_at_all_prefix_and_flags(self) -> None:
        notifier = WeLinkNotifier(
            webhook_url="https://open.welink.huaweicloud.com/api/werobot/v1/webhook/send?token=x&channel=standard",
            http=object(),
            is_at=False,
            is_at_all=True,
            at_accounts=(),
        )
        payload = notifier._build_payload("ping")  # noqa: SLF001
        self.assertEqual(payload["isAtAll"], True)
        self.assertEqual(payload["isAt"], False)
        self.assertTrue(payload["content"]["text"].startswith("@all "))

    def test_send_checks_response_code(self) -> None:
        notifier = WeLinkNotifier(
            webhook_url="https://open.welink.huaweicloud.com/api/werobot/v1/webhook/send?token=x&channel=standard",
            http=object(),
        )
        ok_body = json.dumps({"code": "0", "data": "success", "message": "ok"}).encode("utf-8")
        with mock.patch("urllib.request.urlopen", return_value=_FakeResponse(status=200, body=ok_body)):
            notifier.send(alert=mock.Mock(content="hi"))  # type: ignore[arg-type]

        bad_body = json.dumps({"code": "58601", "data": "", "message": "参数错误"}).encode("utf-8")
        with mock.patch("urllib.request.urlopen", return_value=_FakeResponse(status=200, body=bad_body)):
            with self.assertRaises(RuntimeError):
                notifier.send(alert=mock.Mock(content="hi"))  # type: ignore[arg-type]

    def test_text_is_truncated_to_500_chars(self) -> None:
        notifier = WeLinkNotifier(
            webhook_url="https://open.welink.huaweicloud.com/api/werobot/v1/webhook/send?token=x&channel=standard",
            http=object(),
        )
        text = "x" * 1000
        payload = notifier._build_payload(text)  # noqa: SLF001
        self.assertLessEqual(len(payload["content"]["text"]), 500)
