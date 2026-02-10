from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Mapping

from ..http_utils import HttpClient
from ..models import TrackerEvent, utc_now
from .base import PollResult


_MODEL_PATH_RE = re.compile(r'href="(/models/[^"?#]+)"')


def _decode_cursor(cursor: str | None) -> set[str]:
    if not cursor:
        return set()
    try:
        obj = json.loads(cursor)
        if isinstance(obj, dict) and isinstance(obj.get("known_model_paths"), list):
            return {str(x) for x in obj["known_model_paths"] if isinstance(x, str)}
    except Exception:
        return set()
    return set()


def _encode_cursor(known_model_paths: set[str]) -> str:
    payload = {"known_model_paths": sorted(known_model_paths)}
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


@dataclass(slots=True)
class ModelScopeOrgModelsSource:
    """
    监控 ModelScope 某个组织的模型列表变化（v0：以“新增模型”为主要信号）。

    说明：
    - ModelScope 的页面与接口存在演进可能，v0 采用“尽力而为”的 HTML 解析。
    - 仅用标准库实现，不引入第三方 HTML 解析依赖。
    - cursor 记录该组织已见过的模型路径集合，用于去重与断点续跑。
    """

    org: str
    http: HttpClient

    def key(self) -> str:
        return f"modelscope:{self.org}:models"

    def poll(self, cursor: str | None) -> PollResult:
        known = _decode_cursor(cursor)

        url = f"https://modelscope.cn/organization/{self.org}?tab=model"
        resp = self.http.get(url, headers={"Accept": "text/html"})
        html = resp.text()

        found_paths = set(_MODEL_PATH_RE.findall(html))
        new_paths = sorted(p for p in found_paths if p not in known)

        events: list[TrackerEvent] = []
        now = utc_now()
        for path in new_paths:
            model_id = path.split("/models/", 1)[-1].strip("/")
            if not model_id:
                continue
            full_url = f"https://modelscope.cn{path}"
            events.append(
                TrackerEvent(
                    source="modelscope",
                    resource_type="org_model",
                    resource_id=self.org,
                    event_type="model_added",
                    event_id=model_id,
                    title=model_id,
                    summary="",
                    url=full_url,
                    occurred_at=None,
                    observed_at=now,
                    raw={"path": path},
                )
            )

        new_cursor = _encode_cursor(known | found_paths)
        return PollResult(events=events, new_cursor=new_cursor)

