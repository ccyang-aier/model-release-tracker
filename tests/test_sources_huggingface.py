import json
from dataclasses import dataclass

from mrt.http_utils import HttpResponse
from mrt.sources.huggingface import HuggingFaceOrgModelsSource


@dataclass
class FakeHttp:
    responses: dict[str, HttpResponse]
    calls: list[str] | None = None

    def get(self, url: str, *, headers=None) -> HttpResponse:  # noqa: ANN001
        if self.calls is not None:
            self.calls.append(url)
        if url in self.responses:
            return self.responses[url]
        raise KeyError(url)


def test_pagination_and_cursor() -> None:
    url1 = "https://huggingface.co/api/models?author=deepseek-ai&sort=lastModified&direction=-1&limit=100&full=true"
    url2 = "https://huggingface.co/api/models?page=2"
    payload1 = [{"modelId": "deepseek-ai/DeepSeek-R1", "lastModified": "2026-02-10T00:00:10Z", "sha": "sha1"}]
    payload2 = [{"modelId": "deepseek-ai/Old", "lastModified": "2026-02-09T00:00:00Z", "sha": "sha2"}]
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
    assert len(result.events) == 2
    assert result.new_cursor is not None


def test_cursor_filters_out_old_models() -> None:
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
    assert [e.title for e in result.events] == ["deepseek-ai/New"]


def test_accepts_wrapped_models_list() -> None:
    url1 = "https://huggingface.co/api/models?author=deepseek-ai&sort=lastModified&direction=-1&limit=100&full=true"
    payload = {
        "models": [
            {"modelId": "deepseek-ai/DeepSeek-R1", "lastModified": "2026-02-10T00:00:10Z", "sha": "sha1"},
        ]
    }
    resp = HttpResponse(status=200, url=url1, headers={}, body=json.dumps(payload).encode("utf-8"))
    http = FakeHttp(responses={url1: resp})

    src = HuggingFaceOrgModelsSource(org="deepseek-ai", http=http, token=None)
    result = src.poll(cursor=None)
    assert [e.title for e in result.events] == ["deepseek-ai/DeepSeek-R1"]


def test_stops_paging_when_reaching_cursor_cutoff() -> None:
    url1 = "https://huggingface.co/api/models?author=deepseek-ai&sort=lastModified&direction=-1&limit=100&full=true"
    url2 = "https://huggingface.co/api/models?cursor=next"
    payload1 = [
        {"modelId": "deepseek-ai/New", "lastModified": "2026-02-10T00:00:01Z", "sha": "s1"},
        {"modelId": "deepseek-ai/Old", "lastModified": "2026-02-10T00:00:00Z", "sha": "s2"},
    ]
    resp1 = HttpResponse(
        status=200,
        url=url1,
        headers={"Link": f'<{url2}>; rel="next"'},
        body=json.dumps(payload1).encode("utf-8"),
    )
    http = FakeHttp(responses={url1: resp1}, calls=[])

    src = HuggingFaceOrgModelsSource(org="deepseek-ai", http=http, token=None)
    cursor = json.dumps({"last_modified_after": "2026-02-10T00:00:00Z"})
    result = src.poll(cursor=cursor)
    assert [e.title for e in result.events] == ["deepseek-ai/New"]
    assert http.calls == [url1]
