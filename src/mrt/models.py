from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Mapping


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def parse_rfc3339_datetime(value: str) -> datetime:
    """
    解析常见的 RFC3339/ISO8601 时间串为带 tzinfo 的 datetime。

    兼容：
    - 2026-02-10T12:34:56Z
    - 2026-02-10T12:34:56+00:00
    - 2026-02-10T12:34:56.123Z
    """
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


@dataclass(frozen=True, slots=True)
class TrackerEvent:
    """
    统一事件模型：任何平台的变化，都归一到该结构。

    设计目标：
    - 下游 Rules/Notify/State 不依赖平台私有字段
    - fingerprint 稳定可重建，用于幂等与去重
    """

    source: str
    resource_type: str
    resource_id: str
    event_type: str
    event_id: str
    title: str
    summary: str
    url: str
    occurred_at: datetime | None
    observed_at: datetime
    raw: Mapping[str, Any] | None = None

    def fingerprint(self) -> str:
        """
        事件指纹（幂等键）。

        只使用稳定字段生成：
        - source/resource_type/resource_id/event_type/event_id
        这样即使 title/summary/url/raw 变化，也不会导致重复告警。
        """
        stable = {
            "source": self.source,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "event_type": self.event_type,
            "event_id": self.event_id,
        }
        payload = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_json_dict(self) -> dict[str, Any]:
        """
        将事件序列化为 JSON 友好的 dict（datetime 使用 ISO8601 字符串）。
        """
        return {
            "source": self.source,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "event_type": self.event_type,
            "event_id": self.event_id,
            "title": self.title,
            "summary": self.summary,
            "url": self.url,
            "occurred_at": self.occurred_at.isoformat() if self.occurred_at else None,
            "observed_at": self.observed_at.isoformat(),
            "raw": self.raw,
        }


@dataclass(frozen=True, slots=True)
class RuleMatch:
    rule_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class Alert:
    """
    告警对象：由事件触发，包含命中规则、需要发送渠道、以及格式化后的内容。
    """

    fingerprint: str
    event: TrackerEvent
    matched_rules: tuple[RuleMatch, ...]
    channels: tuple[str, ...]
    content: str
    created_at: datetime

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "event": self.event.to_json_dict(),
            "matched_rules": [dataclasses.asdict(m) for m in self.matched_rules],
            "channels": list(self.channels),
            "content": self.content,
            "created_at": self.created_at.isoformat(),
        }
