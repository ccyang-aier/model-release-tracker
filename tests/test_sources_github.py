import json
from dataclasses import dataclass
from dataclasses import field

from mrt.http_utils import HttpResponse
from mrt.sources.github import GitHubRepoIssuesSource, GitHubRepoPullsSource


@dataclass
class FakeHttp:
    responses: dict[str, HttpResponse]
    last_url: str | None = None
    urls: list[str] = field(default_factory=list)

    def get(self, url: str, *, headers=None) -> HttpResponse:  # noqa: ANN001
        self.last_url = url
        self.urls.append(url)
        if url in self.responses:
            return self.responses[url]
        best_key = None
        for k in self.responses:
            if url.startswith(k) and (best_key is None or len(k) > len(best_key)):
                best_key = k
        if best_key is not None:
            return self.responses[best_key]
        raise KeyError(url)


def test_issues_source_filters_out_pull_requests() -> None:
    updated_at = "2026-02-10T00:00:00Z"
    payload = [
        {
            "id": 111,
            "title": "DeepSeek issue",
            "body": "something",
            "html_url": "https://github.com/a/b/issues/1",
            "updated_at": updated_at,
            "state": "open",
        },
        {
            "id": 222,
            "title": "PR should be filtered",
            "body": "something",
            "html_url": "https://github.com/a/b/pull/2",
            "updated_at": updated_at,
            "state": "open",
            "pull_request": {"url": "https://api.github.com/..."},
        },
    ]
    base = "https://api.github.com/repos/a/b/issues"
    resp = HttpResponse(status=200, url=base, headers={}, body=json.dumps(payload).encode("utf-8"))
    http = FakeHttp(responses={base: resp})

    src = GitHubRepoIssuesSource(repo="a/b", http=http, token=None)
    result = src.poll(cursor=None)

    assert len(result.events) == 1
    assert result.events[0].title == "DeepSeek issue"
    assert result.new_cursor is not None


def test_issues_source_respects_cursor_since() -> None:
    payload = [
        {
            "id": 1,
            "title": "old",
            "body": "",
            "html_url": "https://github.com/a/b/issues/1",
            "updated_at": "2026-02-10T00:00:00Z",
            "state": "open",
        },
        {
            "id": 2,
            "title": "new",
            "body": "",
            "html_url": "https://github.com/a/b/issues/2",
            "updated_at": "2026-02-10T00:00:01Z",
            "state": "open",
        },
    ]
    base = "https://api.github.com/repos/a/b/issues"
    resp = HttpResponse(status=200, url=base, headers={}, body=json.dumps(payload).encode("utf-8"))
    http = FakeHttp(responses={base: resp})

    src = GitHubRepoIssuesSource(repo="a/b", http=http, token=None)
    cursor = json.dumps({"updated_after": "2026-02-10T00:00:00Z"})
    result = src.poll(cursor=cursor)

    assert http.last_url is not None
    assert "since=2026-02-10T00%3A00%3A00Z" in http.last_url
    assert [e.title for e in result.events] == ["new"]


def test_pulls_source_stops_pagination_when_reaching_cursor() -> None:
    page2 = "https://api.github.com/repos/a/b/pulls?page=2"
    page1_payload = [
        {
            "id": 1,
            "title": "old",
            "body": "",
            "html_url": "https://github.com/a/b/pull/1",
            "updated_at": "2026-02-10T00:00:00Z",
            "state": "open",
            "merged_at": None,
        }
    ]
    page2_payload = [
        {
            "id": 2,
            "title": "should not be fetched",
            "body": "",
            "html_url": "https://github.com/a/b/pull/2",
            "updated_at": "2026-02-09T00:00:00Z",
            "state": "open",
            "merged_at": None,
        }
    ]
    base = "https://api.github.com/repos/a/b/pulls"
    resp1 = HttpResponse(
        status=200,
        url=base,
        headers={"Link": f'<{page2}>; rel="next"'},
        body=json.dumps(page1_payload).encode("utf-8"),
    )
    resp2 = HttpResponse(status=200, url=page2, headers={}, body=json.dumps(page2_payload).encode("utf-8"))
    http = FakeHttp(responses={base: resp1, page2: resp2})

    src = GitHubRepoPullsSource(repo="a/b", http=http, token=None)
    cursor = json.dumps({"updated_after": "2026-02-10T00:00:00Z"})
    result = src.poll(cursor=cursor)

    assert result.events == []
    assert len(http.urls) == 1
    assert not any(u.endswith("page=2") for u in http.urls)


def test_pulls_source_bootstrap_fetches_only_first_page() -> None:
    page2 = "https://api.github.com/repos/a/b/pulls?page=2"
    page1_payload = [
        {
            "id": 1,
            "title": "recent",
            "body": "",
            "html_url": "https://github.com/a/b/pull/1",
            "updated_at": "2026-02-10T00:00:00Z",
            "state": "open",
            "merged_at": None,
        }
    ]
    page2_payload = [
        {
            "id": 2,
            "title": "older",
            "body": "",
            "html_url": "https://github.com/a/b/pull/2",
            "updated_at": "2026-02-09T00:00:00Z",
            "state": "open",
            "merged_at": None,
        }
    ]
    base = "https://api.github.com/repos/a/b/pulls"
    resp1 = HttpResponse(
        status=200,
        url=base,
        headers={"Link": f'<{page2}>; rel="next"'},
        body=json.dumps(page1_payload).encode("utf-8"),
    )
    resp2 = HttpResponse(status=200, url=page2, headers={}, body=json.dumps(page2_payload).encode("utf-8"))
    http = FakeHttp(responses={base: resp1, page2: resp2})

    src = GitHubRepoPullsSource(repo="a/b", http=http, token=None)
    result = src.poll(cursor=None)

    assert result.new_cursor is not None
    assert len(http.urls) == 1
