"""
Model Release Tracker (mrt)

v0 的目标是通过轮询方式监控多个平台（GitHub / HuggingFace / ModelScope 等）
的更新动态，并将不同平台的事件归一为统一事件模型后进行规则匹配与告警通知。
"""

from .models import Alert, TrackerEvent

__all__ = [
    "Alert",
    "TrackerEvent",
]

