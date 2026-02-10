from __future__ import annotations

from typing import Protocol

from ..models import Alert


class Notifier(Protocol):
    """
    通知接口：向某个渠道发送告警消息。

    v0 约定：
    - send 失败抛异常，由 runner 统一捕获并记录 failure
    - channel() 用于配置选择与故障记录
    """

    def channel(self) -> str: ...

    def send(self, alert: Alert) -> None: ...

