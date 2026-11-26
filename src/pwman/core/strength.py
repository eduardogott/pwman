"""Password health rating.

The overall score (0-100) combines four sub-scores:

* **Strength** - how many guesses an attacker would need, estimated with
  zxcvbn (detects dictionary words, names, keyboard patterns, dates, l33t
  substitutions, repeats and sequences, plus the most common leaked passwords).
* **Length** - longer is better; 16+ characters is ideal.
* **Variety** - lower case, upper case, digits and symbols, plus how many
  characters are unique.
* **Age** - days since the password was last changed, relative to your
  configured maximum age.

A password reused across several entries is capped at "Weak", because one
breached site exposes all of them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from zxcvbn import zxcvbn

from .models import age_in_days

LABELS = [(80, "Strong"), (60, "Good"), (40, "Fair"), (20, "Weak"), (0, "Very weak")]
_ZXCVBN_MAX = 72  # zxcvbn refuses longer input (and gets slow)
_cache: dict[tuple[str, tuple[str, ...]], dict] = {}


@dataclass
class StrengthReport:
    score: int  # overall, including age and reuse penalties
    label: str
    quality: int  # the password itself (strength, length, variety) - ignores age/reuse
    strength_score: int
    length_score: int
    variety_score: int
    age_score: int | None
    age_days: int | None
    reused_count: int = 0
    crack_time: str = ""
    feedback: list[str] = field(default_factory=list)


def label_for(score: int) -> str:
    return next(label for threshold, label in LABELS if score >= threshold)


def clear_cache() -> None:
    """Drop cached analyses (they reference plaintext passwords). Call on lock."""
    _cache.clear()


def _interp(x: float, points: list[tuple[float, float]]) -> float:
    if x <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return points[-1][1]


def _analyse(password: str, user_inputs: tuple[str, ...]) -> dict:
    key = (password, user_inputs)
    if key not in _cache:
        if len(_cache) > 5000:
            _cache.clear()
        _cache[key] = zxcvbn(password[:_ZXCVBN_MAX], user_inputs=list(user_inputs))
    return _cache[key]


def length_score(password: str) -> int:
    points = [(0, 0), (4, 5), (6, 15), (8, 30), (10, 50), (12, 65), (14, 78), (16, 88), (20, 100)]
    return round(_interp(len(password), points))


def character_classes(password: str) -> dict[str, bool]:
    return {
        "lower": any(c.islower() for c in password),
        "upper": any(c.isupper() for c in password),
        "digits": any(c.isdigit() for c in password),
        "symbols": any(not c.isalnum() for c in password),
    }


def variety_score(password: str) -> int:
    if not password:
        return 0
    classes = sum(character_classes(password).values())
    base = {0: 0, 1: 20, 2: 50, 3: 80, 4: 100}[classes]
    unique_ratio = len(set(password)) / len(password)
    # Heavily repeated characters ("aaaaaa1!") reduce variety.
    factor = min(1.0, 0.4 + unique_ratio)
    return round(base * factor)


def strength_score(guesses_log10: float) -> int:
    # 10^4 guesses (instant) ~ 5, 10^8 (minutes offline) = 30, 10^16 (centuries) = 100.
    points = [(0, 0), (4, 5), (6, 15), (8, 30), (10, 55), (12, 75), (14, 90), (16, 100)]
    return round(_interp(guesses_log10, points))


def age_score(days: int | None, max_age_days: int) -> int | None:
    if days is None or max_age_days <= 0:
        return None
    half = max_age_days / 2
    points = [(0, 100), (half, 100), (max_age_days, 50), (max_age_days * 2, 0)]
    return round(_interp(days, points))


def evaluate(
    password: str,
    changed_at: str | None = None,
    max_age_days: int = 365,
    reused_count: int = 0,
    user_inputs: tuple[str, ...] = (),
    now: datetime | None = None,
) -> StrengthReport:
    """Rate a password. ``reused_count`` = number of *other* entries using it."""
    if not password:
        return StrengthReport(0, "Empty", 0, 0, 0, 0, None, None, reused_count, "",
                              ["No password set."])

    result = _analyse(password, tuple(u for u in user_inputs if u))
    s_strength = strength_score(result["guesses_log10"])
    s_length = length_score(password)
    s_variety = variety_score(password)
    days = age_in_days(changed_at, now)
    s_age = age_score(days, max_age_days)

    quality = 0.5 * s_strength + 0.3 * s_length + 0.2 * s_variety
    quality = min(quality, s_strength + 10)  # a guessable password can't be rescued by length
    age_factor = 1.0 if s_age is None else 0.5 + 0.5 * (s_age / 100)
    score = quality * age_factor
    if reused_count:
        score = min(score, 35)
    score = int(round(max(0, min(100, score))))

    feedback: list[str] = []
    zx = result.get("feedback") or {}
    if zx.get("warning"):
        feedback.append(zx["warning"].rstrip(".") + ".")
    if reused_count:
        others = "entry" if reused_count == 1 else "entries"
        feedback.append(f"Reused in {reused_count} other {others} - use a unique password per site.")
    if len(password) < 12:
        feedback.append("Use at least 12 characters (16+ is better).")
    classes = character_classes(password)
    missing = [name for name, present in classes.items() if not present]
    if missing and s_strength < 90:
        feedback.append("Add " + ", ".join(
            {"lower": "lower-case letters", "upper": "upper-case letters",
             "digits": "numbers", "symbols": "symbols"}[m] for m in missing) + ".")
    if s_age is not None and days is not None and days > max_age_days / 2:
        if days >= max_age_days:
            feedback.append(f"Password is {days} days old - time to change it.")
        else:
            feedback.append(f"Password is {days} days old - consider changing it soon.")
    for suggestion in zx.get("suggestions") or []:
        if s_strength < 80 and suggestion not in feedback:
            feedback.append(suggestion)

    crack = result.get("crack_times_display", {}).get("offline_slow_hashing_1e4_per_second", "")
    return StrengthReport(
        score=score,
        label=label_for(score),
        quality=int(round(quality)),
        strength_score=s_strength,
        length_score=s_length,
        variety_score=s_variety,
        age_score=s_age,
        age_days=days,
        reused_count=reused_count,
        crack_time=crack,
        feedback=feedback,
    )
