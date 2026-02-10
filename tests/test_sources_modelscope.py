from dataclasses import dataclass

from mrt.http_utils import HttpResponse
from mrt.sources.modelscope import ModelScopeOrgModelsSource


@dataclass
class FakeHttp:
    html: str

    def get(self, url: str, *, headers=None) -> HttpResponse:  # noqa: ANN001
        return HttpResponse(status=200, url=url, headers={}, body=self.html.encode("utf-8"))


def test_detects_new_models_by_href() -> None:
    html = """
    <html>
      <a href="/models/deepseek-ai/DeepSeek-R1">x</a>
      <a href="/models/deepseek-ai/DeepSeek-V2">y</a>
    </html>
    """
    src = ModelScopeOrgModelsSource(org="deepseek-ai", http=FakeHttp(html=html))

    r1 = src.poll(cursor=None)
    assert len(r1.events) == 2
    assert r1.new_cursor is not None

    r2 = src.poll(cursor=r1.new_cursor)
    assert len(r2.events) == 0
