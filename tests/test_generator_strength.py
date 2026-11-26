from datetime import datetime, timedelta, timezone

import pytest

from pwman.core import analysis, generator, strength
from pwman.core.generator import GeneratorOptions, PassphraseOptions
from pwman.core.models import Entry


@pytest.mark.parametrize("length,min_digits,min_symbols", [(8, 2, 2), (20, 5, 5), (12, 0, 12), (64, 10, 3)])
def test_generator_respects_minimums(length, min_digits, min_symbols):
    opts = GeneratorOptions(length=length, min_digits=min_digits, min_symbols=min_symbols,
                            min_upper=0, min_lower=0)
    for _ in range(200):
        pw = generator.generate_password(opts)
        assert len(pw) == length
        assert sum(c.isdigit() for c in pw) >= min_digits
        assert sum(c in opts.symbols for c in pw) >= min_symbols


def test_generator_character_sets():
    opts = GeneratorOptions(length=30, use_upper=False, use_symbols=False, min_upper=0, min_symbols=0)
    for _ in range(50):
        pw = generator.generate_password(opts)
        assert pw.isalnum() and pw == pw.lower()


def test_generator_excludes_ambiguous_and_custom():
    opts = GeneratorOptions(length=100, exclude_ambiguous=True, exclude_chars="abc#")
    pw = "".join(generator.generate_password(opts) for _ in range(20))
    assert not (set(pw) & (generator.AMBIGUOUS | set("abc#")))


def test_generator_invalid_options():
    with pytest.raises(ValueError, match="add up"):
        generator.generate_password(GeneratorOptions(length=6, min_digits=4, min_symbols=4))
    with pytest.raises(ValueError, match="at least one"):
        generator.generate_password(GeneratorOptions(use_lower=False, use_upper=False,
                                                     use_digits=False, use_symbols=False))


def test_generator_uses_whole_alphabet():
    opts = GeneratorOptions(length=128, min_digits=0, min_symbols=0, min_lower=0, min_upper=0)
    seen = set("".join(generator.generate_password(opts) for _ in range(40)))
    assert seen == set(generator.LOWER + generator.UPPER + generator.DIGITS + opts.symbols)


def test_passphrase():
    opts = PassphraseOptions(words=6, separator=".", capitalize=True, include_number=True)
    phrase = generator.generate_passphrase(opts)
    parts = phrase.split(".")
    assert len(parts) == 6 and all(p[0].isupper() for p in parts)
    assert sum(any(c.isdigit() for c in p) for p in parts) == 1
    assert opts.entropy_bits() > 77
    assert len(generator.wordlist()) == 7776


def test_generated_passwords_rate_strong():
    pw = generator.generate_password(GeneratorOptions(length=20))
    assert strength.evaluate(pw).label == "Strong"


@pytest.mark.parametrize("pw,labels", [
    ("password", {"Very weak"}),
    ("Password123!", {"Very weak", "Weak"}),
    ("Summer2024!", {"Weak", "Fair"}),
    ("x7#Kp9!qLm2@", {"Good", "Strong"}),
])
def test_strength_labels(pw, labels):
    assert strength.evaluate(pw).label in labels


def test_age_reduces_score():
    pw = "Gd8#kL2!vQ9@zX4%tP6^"
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    fresh = strength.evaluate(pw, changed_at=(now - timedelta(days=10)).isoformat(), now=now)
    old = strength.evaluate(pw, changed_at=(now - timedelta(days=400)).isoformat(), now=now)
    ancient = strength.evaluate(pw, changed_at=(now - timedelta(days=1000)).isoformat(), now=now)
    assert fresh.score > old.score > ancient.score
    assert fresh.age_days == 10 and fresh.age_score == 100
    assert any("days old" in f for f in old.feedback)


def test_length_and_variety_subscores():
    assert strength.length_score("a" * 20) == 100 and strength.length_score("") == 0
    assert strength.variety_score("abc") < strength.variety_score("aB3$")
    assert strength.variety_score("aaaaaaaB3$") < strength.variety_score("qwmzxkaB3$")


def test_reuse_detection_and_report():
    entries = [
        Entry(title="a", password="Shared-Passw0rd-123!", url="a.com"),
        Entry(title="b", password="Shared-Passw0rd-123!"),
        Entry(title="c", password="password", username="x"),
        Entry(title="d", password=generator.generate_password(GeneratorOptions()),
              password_changed_at="2015-01-01T00:00:00+00:00"),
    ]
    counts = analysis.reuse_counts(entries)
    assert counts[entries[0].id] == 1 and counts[entries[2].id] == 0
    report = analysis.build_report(entries, max_age_days=365)
    assert {e.title for e in report.reused} == {"a", "b"}
    assert {e.title for e in report.weak} == {"c"}
    assert {e.title for e in report.old} == {"d"}
    assert report.reports[entries[0].id].score <= 35
    assert {e.title for e in report.without_2fa} == {"a", "c"}


def test_cache_clear():
    strength.evaluate("something-unique-123")
    assert strength._cache
    strength.clear_cache()
    assert not strength._cache
