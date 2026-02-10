import os
import sys
import unittest


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))


from mrt.http_utils import parse_link_header, with_query_params  # noqa: E402


class TestHttpUtils(unittest.TestCase):
    def test_parse_link_header(self) -> None:
        link = '<https://a?page=2>; rel="next", <https://a?page=9>; rel="last"'
        parsed = parse_link_header(link)
        self.assertEqual(parsed["next"], "https://a?page=2")
        self.assertEqual(parsed["last"], "https://a?page=9")

    def test_with_query_params_merges(self) -> None:
        base = "https://example.com/api?x=1"
        url = with_query_params(base, {"x": "2", "y": "3"})
        self.assertIn("x=2", url)
        self.assertIn("y=3", url)

