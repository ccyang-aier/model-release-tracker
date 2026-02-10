from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass

from ..http_utils import HttpClient
from ..models import Alert
from .base import Notifier


@dataclass(slots=True)
class WeLinkNotifier(Notifier):
    """
    WeLink 群机器人 webhook 通知。

    说明：
    - 对齐 docs/welink-webhook-usecase.md 的请求格式：messageType/content/timeStamp/uuid/isAt/isAtAll/atAccounts。
    - webhook_url 需要包含 token 与 channel 参数，例如：
      https://open.welink.huaweicloud.com/api/werobot/v1/webhook/send?token=xxx&channel=standard
    - content.text 长度范围 1~500，超出会被截断。
    """

    webhook_url: str
    http: HttpClient
    is_at: bool = False
    is_at_all: bool = False
    at_accounts: tuple[str, ...] = ()

    def channel(self) -> str:
        return "welink"

    def send(self, alert: Alert) -> None:
        payload = self._build_payload(alert.content)
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        # 使用 GET-only 的 HttpClient 不适合发 POST，这里用标准库直接发起。
        import urllib.request

        req = urllib.request.Request(
            url=self.webhook_url,
            data=data,
            headers={
                "Accept-Charset": "UTF-8",
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
            status = getattr(resp, "status", 200)
            body = resp.read()
            if status >= 400:
                raise RuntimeError(f"WeLink webhook failed: status={status}, body={body[:200]!r}")

        try:
            data = json.loads(body.decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"WeLink webhook invalid JSON response: {body[:200]!r}") from e

        code = data.get("code") if isinstance(data, dict) else None
        if str(code) != "0":
            raise RuntimeError(f"WeLink webhook returned error: {data!r}")

    def _build_payload(self, text: str) -> dict[str, object]:
        """
        生成 WeLink webhook payload（对齐 usecase 文档）。

        @ 提醒规则（文档原话）：
        - content.text 中包含 @userid 或 @all/@所有人 才能高亮
        - 要确保 userid 与 atAccounts 中包含此人员才能实现高亮
        """
        message_text = self._decorate_text(text)
        if not message_text:
            message_text = "-"
        if len(message_text) > 500:
            message_text = message_text[:499] + "…"

        payload: dict[str, object] = {
            "messageType": "text",
            "content": {"text": message_text},
            "timeStamp": int(time.time() * 1000),
            "uuid": uuid.uuid4().hex,
        }

        if self.is_at_all:
            payload["isAtAll"] = True
            payload["isAt"] = False
            return payload

        at_accounts = tuple(a for a in self.at_accounts if a)[:10]
        if self.is_at and at_accounts:
            payload["isAt"] = True
            payload["isAtAll"] = False
            payload["atAccounts"] = list(at_accounts)
            return payload

        payload["isAt"] = False
        payload["isAtAll"] = False
        return payload

    def _decorate_text(self, text: str) -> str:
        text = (text or "").strip()
        if self.is_at_all:
            if text.startswith("@all") or text.startswith("@所有人"):
                return text
            return "@all " + text

        if self.is_at and self.at_accounts:
            mentions = " ".join(f"@{a}" for a in self.at_accounts if a)[:400]
            if mentions and mentions not in text:
                return (mentions + " " + text).strip()
        return text
