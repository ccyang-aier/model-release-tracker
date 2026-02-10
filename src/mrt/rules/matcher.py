from __future__ import annotations

from dataclasses import dataclass

from ..models import RuleMatch, TrackerEvent


@dataclass(frozen=True, slots=True)
class RuleMatcher:
    """
    v0 规则最小集：关键词匹配（大小写不敏感）。

    命中规则输出为多条 RuleMatch，便于通知时给出“命中原因”。
    """

    keywords: tuple[str, ...]
    source_allowlist: tuple[str, ...] | None = None

    def match(self, event: TrackerEvent) -> tuple[RuleMatch, ...]:
        if self.source_allowlist and event.source not in self.source_allowlist:
            return ()

        haystack = f"{event.title}\n{event.summary}".lower()
        matches: list[RuleMatch] = []
        for kw in self.keywords:
            k = (kw or "").strip().lower()
            if not k:
                continue
            if k in haystack:
                matches.append(RuleMatch(rule_id=f"keyword:{k}", reason=f"matched keyword '{k}'"))
        return tuple(matches)

