from __future__ import annotations

from typing import Protocol

from ..models import Alert


class StateStore(Protocol):
    """
    状态与幂等层接口：
    - cursor：每个 source 的进度
    - seen_events：事件指纹去重集合
    - alerts：告警记录（便于审计与追踪）
    """

    def ensure_schema(self) -> None: ...

    def get_cursor(self, source_key: str) -> str | None: ...

    def set_cursor(self, source_key: str, cursor: str | None) -> None: ...

    def has_seen(self, fingerprint: str) -> bool: ...

    def mark_seen(self, fingerprint: str) -> None: ...

    def save_alert(self, alert: Alert) -> None: ...

    def record_notify_failure(self, *, fingerprint: str, channel: str, error: str) -> None: ...

