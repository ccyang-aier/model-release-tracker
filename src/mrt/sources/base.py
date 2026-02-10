from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..models import TrackerEvent


@dataclass(frozen=True, slots=True)
class PollResult:
    events: list[TrackerEvent]
    new_cursor: str | None


class Source(Protocol):
    """
    平台适配器接口：从平台拉取“自 cursor 以来”的增量更新，输出事件与新 cursor。
    """

    def key(self) -> str: ...

    def poll(self, cursor: str | None) -> PollResult: ...

