"""Vault-wide password health: reuse detection and the security report."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from . import strength
from .models import Entry


def reuse_counts(entries: list[Entry]) -> dict[str, int]:
    """entry id -> number of *other* entries sharing the same password."""
    by_password: dict[str, list[str]] = defaultdict(list)
    for e in entries:
        if e.password:
            by_password[e.password].append(e.id)
    counts: dict[str, int] = {}
    for ids in by_password.values():
        for entry_id in ids:
            counts[entry_id] = len(ids) - 1
    return counts


def rate_entry(entry: Entry, max_age_days: int, reused: int = 0) -> strength.StrengthReport:
    return strength.evaluate(
        entry.password,
        changed_at=entry.password_changed_at,
        max_age_days=max_age_days,
        reused_count=reused,
        user_inputs=(entry.username, entry.title),
    )


@dataclass
class SecurityReport:
    reports: dict[str, strength.StrengthReport] = field(default_factory=dict)
    weak: list[Entry] = field(default_factory=list)
    reused: list[Entry] = field(default_factory=list)
    old: list[Entry] = field(default_factory=list)
    without_2fa: list[Entry] = field(default_factory=list)
    overall: int = 100

    @property
    def issue_count(self) -> int:
        return len({e.id for e in self.weak + self.reused + self.old})


WEAK_THRESHOLD = 40  # below "Fair"


def build_report(entries: list[Entry], max_age_days: int) -> SecurityReport:
    report = SecurityReport()
    reuse = reuse_counts(entries)
    scores = []
    for e in entries:
        if not e.password:
            continue
        r = rate_entry(e, max_age_days, reuse.get(e.id, 0))
        report.reports[e.id] = r
        scores.append(r.score)
        if r.reused_count:
            report.reused.append(e)
        if r.quality < WEAK_THRESHOLD:
            report.weak.append(e)
        if max_age_days > 0 and r.age_days is not None and r.age_days >= max_age_days:
            report.old.append(e)
    for e in entries:
        if e.totp is None and (e.url or e.username):
            report.without_2fa.append(e)
    report.overall = round(sum(scores) / len(scores)) if scores else 100
    return report
