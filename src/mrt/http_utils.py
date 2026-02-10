from __future__ import annotations

import json
import random
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    url: str
    headers: Mapping[str, str]
    body: bytes

    def text(self, encoding: str = "utf-8") -> str:
        return self.body.decode(encoding, errors="replace")

    def json(self) -> Any:
        return json.loads(self.body.decode("utf-8"))


class HttpClient:
    """
    轻量 HTTP 客户端（仅依赖标准库），用于 Sources 拉取接口。

    v0 策略：
    - 对 429/5xx 做有限次退避重试
    - 统一超时、User-Agent
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = 20.0,
        user_agent: str = "model-release-tracker/0",
        max_retries: int = 3,
        base_backoff_seconds: float = 0.8,
        verify_ssl: bool = True,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._user_agent = user_agent
        self._max_retries = max_retries
        self._base_backoff_seconds = base_backoff_seconds
        self._ssl_context = ssl.create_default_context() if verify_ssl else ssl._create_unverified_context()

    def get(self, url: str, *, headers: Mapping[str, str] | None = None) -> HttpResponse:
        request_headers = {"User-Agent": self._user_agent}
        if headers:
            request_headers.update(dict(headers))

        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                req = urllib.request.Request(url=url, headers=request_headers, method="GET")
                with urllib.request.urlopen(req, timeout=self._timeout_seconds, context=self._ssl_context) as resp:
                    resp_headers = {k: v for k, v in resp.headers.items()}
                    return HttpResponse(
                        status=getattr(resp, "status", 200),
                        url=resp.geturl(),
                        headers=resp_headers,
                        body=resp.read(),
                    )
            except urllib.error.HTTPError as e:
                last_error = e
                retry = e.code in (429, 500, 502, 503, 504)
                if (not retry) or attempt >= self._max_retries:
                    raise
            except (urllib.error.URLError, TimeoutError) as e:
                last_error = e
                if attempt >= self._max_retries:
                    raise

            backoff = self._base_backoff_seconds * (2**attempt)
            jitter = random.random() * 0.25 * backoff
            time.sleep(backoff + jitter)

        assert last_error is not None
        raise last_error


def parse_link_header(link_value: str) -> dict[str, str]:
    """
    解析 RFC5988 Link 头，返回 rel -> url 映射。

    示例：
    <https://...>; rel="next", <https://...>; rel="last"
    """
    result: dict[str, str] = {}
    for part in link_value.split(","):
        part = part.strip()
        if not part.startswith("<") or ">;" not in part:
            continue
        url = part[1 : part.index(">")]
        params = part[part.index(">") + 1 :].split(";")
        rel = None
        for p in params:
            p = p.strip()
            if p.startswith("rel="):
                rel = p.split("=", 1)[1].strip().strip('"')
        if rel:
            result[rel] = url
    return result


def with_query_params(url: str, params: Mapping[str, str]) -> str:
    parsed = urllib.parse.urlparse(url)
    q = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    q.update({k: v for k, v in params.items() if v is not None})
    new_query = urllib.parse.urlencode(q)
    return urllib.parse.urlunparse(parsed._replace(query=new_query))
