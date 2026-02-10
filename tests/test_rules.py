import os
import sys
import unittest
from datetime import UTC, datetime


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))


from mrt.models import TrackerEvent  # noqa: E402
from mrt.rules.matcher import RuleMatcher  # noqa: E402


class TestRules(unittest.TestCase):
    def test_keyword_match_is_case_insensitive(self) -> None:
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
        self.assertEqual({m.rule_id for m in matches}, {"keyword:deepseek", "keyword:qwen"})

