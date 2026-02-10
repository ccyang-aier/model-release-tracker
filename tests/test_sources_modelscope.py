import os
import sys
import unittest
from dataclasses import dataclass


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))


from mrt.http_utils import HttpResponse  # noqa: E402
from mrt.sources.modelscope import ModelScopeOrgModelsSource  # noqa: E402


@dataclass
class FakeHttp:
    html: str

    def get(self, url: str, *, headers=None) -> HttpResponse:  # noqa: ANN001
        return HttpResponse(status=200, url=url, headers={}, body=self.html.encode("utf-8"))


class TestModelScopeSource(unittest.TestCase):
    def test_detects_new_models_by_href(self) -> None:
        html = """
        <html>
          <a href="/models/deepseek-ai/DeepSeek-R1">x</a>
          <a href="/models/deepseek-ai/DeepSeek-V2">y</a>
        </html>
        """
        src = ModelScopeOrgModelsSource(org="deepseek-ai", http=FakeHttp(html=html))

        r1 = src.poll(cursor=None)
        self.assertEqual(len(r1.events), 2)
        self.assertIsNotNone(r1.new_cursor)

        r2 = src.poll(cursor=r1.new_cursor)
        self.assertEqual(len(r2.events), 0)

