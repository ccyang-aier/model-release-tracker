from datetime import UTC, datetime

from mrt.models import TrackerEvent
from mrt.rules.matcher import RuleMatcher


def test_keyword_match_is_case_insensitive() -> None:
    t = datetime(2026, 2, 10, 0, 0, tzinfo=UTC)
    event = TrackerEvent(
        source="github",
        resource_type="repo_issue",
        resource_id="a/b",
        event_type="issue_updated",
        event_id="1",
        title="DeepSeek release",
        summary="QWEN is also mentioned",
        url="https://example.com",
        occurred_at=t,
        observed_at=t,
        raw=None,
    )
    matcher = RuleMatcher(keywords=("deepseek", "qwen"))
    matches = matcher.match(event)
    assert {m.rule_id for m in matches} == {"keyword:deepseek", "keyword:qwen"}
