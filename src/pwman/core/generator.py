"""Password and passphrase generation using the OS cryptographic RNG."""

from __future__ import annotations

import math
import secrets
import string
from dataclasses import asdict, dataclass, fields
from functools import lru_cache
from importlib import resources

LOWER = string.ascii_lowercase
UPPER = string.ascii_uppercase
DIGITS = string.digits
DEFAULT_SYMBOLS = "!@#$%^&*()-_=+[]{};:,.<>?/~"
AMBIGUOUS = set("Il1O0o|`'\"")

MIN_LENGTH = 4
MAX_LENGTH = 128

_rng = secrets.SystemRandom()


@dataclass
class GeneratorOptions:
    length: int = 20
    use_lower: bool = True
    use_upper: bool = True
    use_digits: bool = True
    use_symbols: bool = True
    min_lower: int = 1
    min_upper: int = 1
    min_digits: int = 2
    min_symbols: int = 2
    exclude_ambiguous: bool = False
    symbols: str = DEFAULT_SYMBOLS
    exclude_chars: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "GeneratorOptions":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (data or {}).items() if k in names})

    def pools(self) -> dict[str, tuple[str, int]]:
        """Enabled character classes -> (allowed characters, minimum count)."""
        excluded = set(self.exclude_chars)
        if self.exclude_ambiguous:
            excluded |= AMBIGUOUS
        classes = {
            "lower": (self.use_lower, LOWER, self.min_lower),
            "upper": (self.use_upper, UPPER, self.min_upper),
            "digits": (self.use_digits, DIGITS, self.min_digits),
            "symbols": (self.use_symbols, self.symbols, self.min_symbols),
        }
        result = {}
        for name, (enabled, chars, minimum) in classes.items():
            if enabled:
                allowed = "".join(dict.fromkeys(c for c in chars if c not in excluded and not c.isspace()))
                result[name] = (allowed, max(0, int(minimum)))
        return result

    def validate(self) -> list[str]:
        """Return a list of problems (empty if the options are usable)."""
        problems = []
        pools = self.pools()
        if not pools:
            problems.append("Select at least one character type.")
        if not (MIN_LENGTH <= self.length <= MAX_LENGTH):
            problems.append(f"Length must be between {MIN_LENGTH} and {MAX_LENGTH}.")
        for name, (chars, _) in pools.items():
            if not chars:
                problems.append(f"No {name} characters left after exclusions.")
        total_min = sum(minimum for _, minimum in pools.values())
        if total_min > self.length:
            problems.append(
                f"The minimum counts add up to {total_min}, more than the length ({self.length})."
            )
        return problems

    def entropy_bits(self) -> float:
        pool = "".join(chars for chars, _ in self.pools().values())
        if not pool:
            return 0.0
        return self.length * math.log2(len(set(pool)))


def generate_password(options: GeneratorOptions) -> str:
    problems = options.validate()
    if problems:
        raise ValueError(" ".join(problems))
    pools = options.pools()
    chars: list[str] = []
    for allowed, minimum in pools.values():
        chars.extend(secrets.choice(allowed) for _ in range(minimum))
    everything = "".join(dict.fromkeys("".join(allowed for allowed, _ in pools.values())))
    chars.extend(secrets.choice(everything) for _ in range(options.length - len(chars)))
    _rng.shuffle(chars)
    return "".join(chars)


# --------------------------------------------------------------------------- passphrases


@lru_cache(maxsize=1)
def wordlist() -> tuple[str, ...]:
    """EFF large wordlist (7776 words, ~12.9 bits each). CC BY 3.0, see THIRD_PARTY_NOTICES."""
    text = resources.files("pwman.assets").joinpath("eff_large_wordlist.txt").read_text("utf-8")
    words = tuple(w.strip() for w in text.splitlines() if w.strip())
    if len(words) < 7000:
        raise RuntimeError("Passphrase wordlist is missing or damaged.")
    return words


@dataclass
class PassphraseOptions:
    words: int = 5
    separator: str = "-"
    capitalize: bool = True
    include_number: bool = True

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "PassphraseOptions":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in (data or {}).items() if k in names})

    def entropy_bits(self) -> float:
        bits = self.words * math.log2(len(wordlist()))
        if self.include_number:
            bits += math.log2(10 * self.words)
        return bits


def generate_passphrase(options: PassphraseOptions) -> str:
    if not (3 <= options.words <= 20):
        raise ValueError("Use between 3 and 20 words.")
    words = [secrets.choice(wordlist()) for _ in range(options.words)]
    if options.capitalize:
        words = [w.capitalize() for w in words]
    if options.include_number:
        idx = secrets.randbelow(len(words))
        words[idx] = words[idx] + str(secrets.randbelow(10))
    return options.separator.join(words)
