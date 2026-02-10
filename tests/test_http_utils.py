from mrt.http_utils import parse_link_header, with_query_params


def test_parse_link_header() -> None:
    link = '<https://a?page=2>; rel="next", <https://a?page=9>; rel="last"'
    parsed = parse_link_header(link)
    assert parsed["next"] == "https://a?page=2"
    assert parsed["last"] == "https://a?page=9"


def test_with_query_params_merges() -> None:
    base = "https://example.com/api?x=1"
    url = with_query_params(base, {"x": "2", "y": "3"})
    assert "x=2" in url
    assert "y=3" in url
