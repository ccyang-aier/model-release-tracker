from dataclasses import dataclass

from mrt.http_utils import HttpResponse
from mrt.sources.modelscope import ModelScopeOrgModelsSource


@dataclass
class FakeHttp:
    responses: dict[str, HttpResponse]

    def get(self, url: str, *, headers=None) -> HttpResponse:  # noqa: ANN001
        if url in self.responses:
            return self.responses[url]
        raise KeyError(url)


def test_detects_new_models_via_openapi_list() -> None:
    url = (
        "https://modelscope.cn/openapi/v1/models?owner=deepseek-ai&sort=last_modified&page_number=1&page_size=50"
    )
    body = (
        '{"success":true,"request_id":"r","data":{"models":['
        '{"id":"deepseek-ai/DeepSeek-R1","tasks":["text-generation"],"last_modified":"2026-02-10T00:00:10Z"},'
        '{"id":"deepseek-ai/DeepSeek-V2","tasks":[],"last_modified":"2026-02-10T00:00:11Z"}'
        '],"total_count":2,"page_number":1,"page_size":50}}'
    )
    http = FakeHttp(responses={url: HttpResponse(status=200, url=url, headers={}, body=body.encode("utf-8"))})
    src = ModelScopeOrgModelsSource(org="deepseek-ai", http=http)

    r1 = src.poll(cursor=None)
    assert len(r1.events) == 2
    assert r1.new_cursor is not None

    r2 = src.poll(cursor=r1.new_cursor)
    assert len(r2.events) == 0
