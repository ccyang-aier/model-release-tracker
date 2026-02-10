import os
import sys
import unittest
from datetime import UTC, datetime


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))


from mrt.models import TrackerEvent  # noqa: E402


class TestModels(unittest.TestCase):
    def test_fingerprint_is_stable(self) -> None:
        t = datetime(2026, 2, 10, 0, 0, tzinfo=UTC)
        e1 = TrackerEvent(
            source="github",
            resource_type="repo_issue",
            resource_id="a/b",
            event_type="issue_updated",
            event_id="123",
            title="DeepSeek update",
            summary="body",
            url="https://example.com",
            occurred_at=t,
            observed_at=t,
            raw=None,
        )
        e2 = TrackerEvent(
            source="github",
            resource_type="repo_issue",
            resource_id="a/b",
            event_type="issue_updated",
            event_id="123",
            title="different title does not affect fingerprint",
            summary="different summary",
            url="https://example.com/other",
            occurred_at=None,
            observed_at=t,
            raw={"x": 1},
        )
        self.assertEqual(e1.fingerprint(), e2.fingerprint())

