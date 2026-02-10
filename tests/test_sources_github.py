import json
import os
import sys
import unittest
from dataclasses import dataclass
from datetime import UTC, datetime


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))


from mrt.http_utils import HttpResponse  # noqa: E402
from mrt.sources.github import GitHubRepoIssuesSource  # noqa: E402


@dataclass
class FakeHttp:
    responses: dict[str, HttpResponse]
    last_url: str | None = None

    def get(self, url: str, *, headers=None) -> HttpResponse:  # noqa: ANN001
        self.last_url = url
        for k, v in self.responses.items():
            if url.startswith(k):
                return v
        raise KeyError(url)


class TestGitHubSource(unittest.TestCase):
    def test_issues_source_filters_out_pull_requests(self) -> None:
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

        self.assertEqual(len(result.events), 1)
        self.assertEqual(result.events[0].title, "DeepSeek issue")
        self.assertIsNotNone(result.new_cursor)

    def test_issues_source_respects_cursor_since(self) -> None:
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
        self.assertIn("since=2026-02-10T00%3A00%3A00Z", http.last_url)
        self.assertEqual([e.title for e in result.events], ["new"])
