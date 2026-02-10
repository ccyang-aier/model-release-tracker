from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from ..http_utils import HttpClient, with_query_params
from ..models import TrackerEvent, parse_rfc3339_datetime, utc_now
from .base import PollResult


def _decode_cursor(cursor: str | None) -> set[str]:
    if not cursor:
        return set()
    try:
        obj = json.loads(cursor)
        if isinstance(obj, dict) and isinstance(obj.get("known_model_ids"), list):
            return {str(x) for x in obj["known_model_ids"] if isinstance(x, str)}
        if isinstance(obj, dict) and isinstance(obj.get("known_model_paths"), list):
            ids: set[str] = set()
            for p in obj["known_model_paths"]:
                if not isinstance(p, str):
                    continue
                if "/models/" in p:
                    ids.add(p.split("/models/", 1)[-1].strip("/"))
            return ids
    except Exception:
        return set()
    return set()


def _encode_cursor(known_model_ids: set[str]) -> str:
    payload = {"known_model_ids": sorted(known_model_ids)}
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
        known_ids = _decode_cursor(cursor)

        page_number = 1
        page_size = 50
        max_items = 3000
        found_ids: set[str] = set()
        models: dict[str, Mapping[str, Any]] = {}

        while page_number * page_size <= max_items:
            url = with_query_params(
                "https://modelscope.cn/openapi/v1/models",
                {
                    "owner": self.org,
                    "sort": "last_modified",
                    "page_number": str(page_number),
                    "page_size": str(page_size),
                },
            )
            resp = self.http.get(url, headers={"Accept": "application/json"})
            try:
                data = resp.json()
            except Exception as e:  # noqa: BLE001
                body_prefix = resp.text()[:400]
                raise ValueError(
                    f"ModelScope OpenAPI invalid JSON: status={resp.status} url={resp.url} body_prefix={body_prefix!r}"
                ) from e

            if not isinstance(data, dict):
                body_prefix = resp.text()[:400]
                raise ValueError(
                    f"ModelScope OpenAPI expected object, got {type(data)}: status={resp.status} url={resp.url} body_prefix={body_prefix!r}"
                )

            data_obj = data.get("data")
            if not (isinstance(data.get("success"), bool) and isinstance(data_obj, dict)):
                body_prefix = resp.text()[:400]
                raise ValueError(
                    f"ModelScope OpenAPI unexpected payload: status={resp.status} url={resp.url} body_prefix={body_prefix!r}"
                )

            items = data_obj.get("models")
            if not isinstance(items, list):
                body_prefix = resp.text()[:400]
                raise ValueError(
                    f"ModelScope OpenAPI expected data.models list, got {type(items)}: status={resp.status} url={resp.url} body_prefix={body_prefix!r}"
                )

            for it in items:
                if not isinstance(it, dict):
                    continue
                model_id = it.get("id")
                if not isinstance(model_id, str) or not model_id:
                    continue
                found_ids.add(model_id)
                models[model_id] = it

            total_count = data_obj.get("total_count")
            if isinstance(total_count, int) and total_count <= page_number * page_size:
                break
            if not items:
                break
            page_number += 1

        new_ids = sorted(mid for mid in found_ids if mid not in known_ids)

        events: list[TrackerEvent] = []
        now = utc_now()
        newest_last_modified: datetime | None = None
        for model_id in new_ids:
            raw = models.get(model_id) or {}
            last_modified_s = raw.get("last_modified")
            occurred_at = parse_rfc3339_datetime(last_modified_s) if isinstance(last_modified_s, str) else None
            if occurred_at and (newest_last_modified is None or occurred_at > newest_last_modified):
                newest_last_modified = occurred_at
            tasks = raw.get("tasks")
            summary = ",".join(str(x) for x in tasks if isinstance(x, str)) if isinstance(tasks, list) else ""
            full_url = f"https://modelscope.cn/models/{model_id}"
            events.append(
                TrackerEvent(
                    source="modelscope",
                    resource_type="org_model",
                    resource_id=self.org,
                    event_type="model_added",
                    event_id=model_id,
                    title=model_id,
                    summary=summary,
                    url=full_url,
                    occurred_at=occurred_at,
                    observed_at=now,
                    raw=raw,
                )
            )

        new_cursor = _encode_cursor(known_ids | found_ids)
        return PollResult(events=events, new_cursor=new_cursor)
