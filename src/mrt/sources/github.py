from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from ..http_utils import HttpClient, parse_link_header, with_query_params
from ..models import TrackerEvent, parse_rfc3339_datetime, utc_now
from .base import PollResult


def _truncate(text: str, limit: int = 400) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _encode_cursor(updated_after: datetime) -> str:
    return json.dumps({"updated_after": updated_after.isoformat()}, ensure_ascii=False, separators=(",", ":"))


def _decode_cursor(cursor: str | None) -> datetime | None:
    if not cursor:
        return None
    try:
        obj = json.loads(cursor)
        if isinstance(obj, dict) and isinstance(obj.get("updated_after"), str):
            return parse_rfc3339_datetime(obj["updated_after"])
    except Exception:
        return None
    return None


@dataclass(slots=True)
class _GitHubBase:
    repo: str
    http: HttpClient
    token: str | None = None

    def _headers(self) -> Mapping[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _get_json_pages(self, url: str) -> list[tuple[list[Mapping[str, Any]], Mapping[str, str]]]:
        pages: list[tuple[list[Mapping[str, Any]], Mapping[str, str]]] = []
        next_url: str | None = url
        while next_url:
            resp = self.http.get(next_url, headers=self._headers())
            data = resp.json()
            if not isinstance(data, list):
                raise ValueError(f"GitHub API expected list, got {type(data)}: {resp.url}")
            items: list[Mapping[str, Any]] = [x for x in data if isinstance(x, dict)]
            pages.append((items, resp.headers))
            link = resp.headers.get("Link") or resp.headers.get("link")
            if not link:
                break
            links = parse_link_header(link)
            next_url = links.get("next")
        return pages


@dataclass(slots=True)
class GitHubRepoIssuesSource(_GitHubBase):
    """
    监控某个 GitHub Repo 的 Issues（不含 PR）。

    cursor 语义：updated_after（RFC3339）
    """

    def key(self) -> str:
        return f"github:{self.repo}:issues"

    def poll(self, cursor: str | None) -> PollResult:
        updated_after = _decode_cursor(cursor)
        base_url = f"https://api.github.com/repos/{self.repo}/issues"
        params = {
            "state": "all",
            "sort": "updated",
            "direction": "desc",
            "per_page": "100",
        }
        if updated_after is not None:
            params["since"] = updated_after.isoformat().replace("+00:00", "Z")
        url = with_query_params(base_url, params)

        newest_updated_at: datetime | None = updated_after
        events: list[TrackerEvent] = []

        for items, _headers in self._get_json_pages(url):
            for it in items:
                if "pull_request" in it:
                    continue
                updated_at_s = it.get("updated_at")
                if not isinstance(updated_at_s, str):
                    continue
                updated_at = parse_rfc3339_datetime(updated_at_s)
                if updated_after is not None and updated_at <= updated_after:
                    continue
                if newest_updated_at is None or updated_at > newest_updated_at:
                    newest_updated_at = updated_at

                issue_id = str(it.get("id") or it.get("number") or it.get("url") or "")
                title = str(it.get("title") or "")
                body = str(it.get("body") or "")
                html_url = str(it.get("html_url") or it.get("url") or "")
                state = str(it.get("state") or "")
                event_type = "issue_updated" if state else "issue_event"

                events.append(
                    TrackerEvent(
                        source="github",
                        resource_type="repo_issue",
                        resource_id=self.repo,
                        event_type=event_type,
                        event_id=issue_id,
                        title=title,
                        summary=_truncate(body),
                        url=html_url,
                        occurred_at=updated_at,
                        observed_at=utc_now(),
                        raw=it,
                    )
                )

        new_cursor = _encode_cursor(newest_updated_at) if newest_updated_at is not None else cursor
        return PollResult(events=events, new_cursor=new_cursor)


@dataclass(slots=True)
class GitHubRepoPullsSource(_GitHubBase):
    """
    监控某个 GitHub Repo 的 Pull Requests。

    cursor 语义：updated_after（RFC3339）
    """

    def key(self) -> str:
        return f"github:{self.repo}:pulls"

    def poll(self, cursor: str | None) -> PollResult:
        updated_after = _decode_cursor(cursor)
        base_url = f"https://api.github.com/repos/{self.repo}/pulls"
        url = with_query_params(
            base_url,
            {
                "state": "all",
                "sort": "updated",
                "direction": "desc",
                "per_page": "100",
            },
        )

        newest_updated_at: datetime | None = updated_after
        events: list[TrackerEvent] = []

        for items, _headers in self._get_json_pages(url):
            for it in items:
                updated_at_s = it.get("updated_at")
                if not isinstance(updated_at_s, str):
                    continue
                updated_at = parse_rfc3339_datetime(updated_at_s)
                if updated_after is not None and updated_at <= updated_after:
                    continue
                if newest_updated_at is None or updated_at > newest_updated_at:
                    newest_updated_at = updated_at

                pr_id = str(it.get("id") or it.get("number") or it.get("url") or "")
                title = str(it.get("title") or "")
                body = str(it.get("body") or "")
                html_url = str(it.get("html_url") or it.get("url") or "")
                merged_at = it.get("merged_at")
                if isinstance(merged_at, str) and merged_at:
                    event_type = "pr_merged"
                    occurred_at = parse_rfc3339_datetime(merged_at)
                else:
                    event_type = "pr_updated"
                    occurred_at = updated_at

                events.append(
                    TrackerEvent(
                        source="github",
                        resource_type="repo_pr",
                        resource_id=self.repo,
                        event_type=event_type,
                        event_id=pr_id,
                        title=title,
                        summary=_truncate(body),
                        url=html_url,
                        occurred_at=occurred_at,
                        observed_at=utc_now(),
                        raw=it,
                    )
                )

        new_cursor = _encode_cursor(newest_updated_at) if newest_updated_at is not None else cursor
        return PollResult(events=events, new_cursor=new_cursor)

