from __future__ import annotations

from ..models import Alert


def format_alert_text(alert: Alert) -> str:
    """
    v0：统一的文本消息格式，尽量兼容 IM webhook 与邮件正文。
    """
    event = alert.event
    rules = ", ".join(m.rule_id for m in alert.matched_rules) or "-"
    occurred = event.occurred_at.isoformat() if event.occurred_at else "-"
    observed = event.observed_at.isoformat()

    lines = [
        "Model Release Tracker Alert",
        f"source: {event.source}",
        f"resource: {event.resource_type} {event.resource_id}",
        f"type: {event.event_type}",
        f"title: {event.title}",
        f"url: {event.url}",
        f"occurred_at: {occurred}",
        f"observed_at: {observed}",
        f"matched_rules: {rules}",
    ]
    if event.summary:
        lines.append("")
        lines.append(event.summary)
    return "\n".join(lines)

