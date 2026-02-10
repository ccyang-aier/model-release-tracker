import json
import os
import sys
import unittest
from dataclasses import dataclass


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))


from mrt.http_utils import HttpResponse  # noqa: E402
from mrt.sources.huggingface import HuggingFaceOrgModelsSource  # noqa: E402


@dataclass
class FakeHttp:
    responses: dict[str, HttpResponse]

    def get(self, url: str, *, headers=None) -> HttpResponse:  # noqa: ANN001
        if url in self.responses:
            return self.responses[url]
        raise KeyError(url)


class TestHuggingFaceSource(unittest.TestCase):
    def test_pagination_and_cursor(self) -> None:
        url1 = "https://huggingface.co/api/models?author=deepseek-ai&sort=lastModified&direction=-1&limit=100&full=true"
        url2 = "https://huggingface.co/api/models?page=2"
        payload1 = [
            {"modelId": "deepseek-ai/DeepSeek-R1", "lastModified": "2026-02-10T00:00:10Z", "sha": "sha1"}
        ]
        payload2 = [
            {"modelId": "deepseek-ai/Old", "lastModified": "2026-02-09T00:00:00Z", "sha": "sha2"}
        ]
        resp1 = HttpResponse(
            status=200,
            url=url1,
            headers={"Link": f'<{url2}>; rel="next"'},
            body=json.dumps(payload1).encode("utf-8"),
        )
        resp2 = HttpResponse(status=200, url=url2, headers={}, body=json.dumps(payload2).encode("utf-8"))
        http = FakeHttp(responses={url1: resp1, url2: resp2})

        src = HuggingFaceOrgModelsSource(org="deepseek-ai", http=http, token=None)
        result = src.poll(cursor=None)
        self.assertEqual(len(result.events), 2)
        self.assertIsNotNone(result.new_cursor)

    def test_cursor_filters_out_old_models(self) -> None:
        url1 = "https://huggingface.co/api/models?author=deepseek-ai&sort=lastModified&direction=-1&limit=100&full=true"
        payload = [
            {"modelId": "deepseek-ai/New", "lastModified": "2026-02-10T00:00:01Z", "sha": "s1"},
            {"modelId": "deepseek-ai/Old", "lastModified": "2026-02-10T00:00:00Z", "sha": "s2"},
        ]
        resp = HttpResponse(status=200, url=url1, headers={}, body=json.dumps(payload).encode("utf-8"))
        http = FakeHttp(responses={url1: resp})

        src = HuggingFaceOrgModelsSource(org="deepseek-ai", http=http, token=None)
        cursor = json.dumps({"last_modified_after": "2026-02-10T00:00:00Z"})
        result = src.poll(cursor=cursor)
        self.assertEqual([e.title for e in result.events], ["deepseek-ai/New"])
