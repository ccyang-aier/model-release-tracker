from datetime import UTC, datetime

from mrt.models import TrackerEvent


def test_fingerprint_is_stable() -> None:
    """
    fingerprint 只由稳定字段组成，因此 title/summary/url/raw 的变化不应影响幂等键。
    """
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
    assert e1.fingerprint() == e2.fingerprint()
