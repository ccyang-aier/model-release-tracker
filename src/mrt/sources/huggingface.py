from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from ..http_utils import HttpClient, parse_link_header, with_query_params
from ..models import TrackerEvent, parse_rfc3339_datetime, utc_now
from .base import PollResult


def _encode_cursor(updated_after: datetime) -> str:
    return json.dumps({"last_modified_after": updated_after.isoformat()}, ensure_ascii=False, separators=(",", ":"))


def _decode_cursor(cursor: str | None) -> datetime | None:
    if not cursor:
        return None
    try:
        obj = json.loads(cursor)
        if isinstance(obj, dict) and isinstance(obj.get("last_modified_after"), str):
            return parse_rfc3339_datetime(obj["last_modified_after"])
    except Exception:
        return None
    return None


@dataclass(slots=True)
class HuggingFaceOrgModelsSource:
    """
    监控 HuggingFace 某个组织/用户的模型列表变化。

    数据源：Hub API models endpoint。官方文档说明响应可通过 Link 头进行分页。
    """

    org: str
    http: HttpClient
    token: str | None = None

    def key(self) -> str:
        return f"huggingface:{self.org}:models"

    def _headers(self) -> Mapping[str, str]:
        headers: dict[str, str] = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def poll(self, cursor: str | None) -> PollResult:
        last_modified_after = _decode_cursor(cursor)

        url = with_query_params(
            "https://huggingface.co/api/models",
            {
                "author": self.org,
                "sort": "lastModified",
                "direction": "-1",
                "limit": "100",
                "full": "true",
            },
        )

        newest_last_modified: datetime | None = last_modified_after
        events: list[TrackerEvent] = []

        next_url: str | None = url
        while next_url:
            resp = self.http.get(next_url, headers=self._headers())
            data = resp.json()
            if not isinstance(data, list):
                raise ValueError(f"HuggingFace API expected list, got {type(data)}: {resp.url}")

            for it in data:
                if not isinstance(it, dict):
                    continue
                last_modified_s = it.get("lastModified") or it.get("last_modified")
                if not isinstance(last_modified_s, str):
                    continue
                last_modified = parse_rfc3339_datetime(last_modified_s)
                if last_modified_after is not None and last_modified <= last_modified_after:
                    continue

                if newest_last_modified is None or last_modified > newest_last_modified:
                    newest_last_modified = last_modified

                model_id = str(it.get("modelId") or it.get("id") or "")
                if not model_id:
                    continue

                title = model_id
                url = f"https://huggingface.co/{model_id}"
                sha = str(it.get("sha") or "")
                event_id = sha or model_id
                summary = str(it.get("pipeline_tag") or it.get("library_name") or "")

                events.append(
                    TrackerEvent(
                        source="huggingface",
                        resource_type="org_model",
                        resource_id=self.org,
                        event_type="model_updated",
                        event_id=event_id,
                        title=title,
                        summary=summary,
                        url=url,
                        occurred_at=last_modified,
                        observed_at=utc_now(),
                        raw=it,
                    )
                )

            link = resp.headers.get("Link") or resp.headers.get("link")
            if not link:
                break
            links = parse_link_header(link)
            next_url = links.get("next")

        new_cursor = _encode_cursor(newest_last_modified) if newest_last_modified is not None else cursor
        return PollResult(events=events, new_cursor=new_cursor)

