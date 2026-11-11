"""Small text utilities for memory keywords and similarity."""

from __future__ import annotations

import re

STOPWORDS = frozenset(
    """
    a about above after again against all also am an and any are as at be because been
    before being below between both but by can could did do does doing down during each
    few for from further had has have having he her here hers herself him himself his how
    i if in into is it its itself just kimi me more most my myself no nor not now of off
    on once only or other our ours ourselves out over own same she should so some still
    such than that the their theirs them themselves then there these they this those
    through to too under until up very was we were what when where which while who whom
    why will with would you your yours yourself yourselves today little bit felt feel
    really quite went got get one thing things something lot lots maybe like just ever
    """.split()
)

_WORD = re.compile(r"[a-zA-Z][a-zA-Z'\-]{1,}")


def _stem(word: str) -> str:
    for suffix in ("'s", "ies", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            if suffix == "ies":
                return word[: -3] + "y"
            if suffix == "es" and not word.endswith(("ses", "xes", "ches", "shes")):
                return word[:-1]
            return word[: -len(suffix)]
    return word


def keywords(text: str, limit: int = 14) -> list[str]:
    seen: dict[str, None] = {}
    for match in _WORD.finditer(text or ""):
        word = match.group(0).lower().strip("'-")
        if len(word) < 3 or word in STOPWORDS:
            continue
        stem = _stem(word)
        if stem in STOPWORDS:
            continue
        seen.setdefault(stem, None)
        if len(seen) >= limit:
            break
    return list(seen)


def keyword_string(text: str, limit: int = 14) -> str:
    return " ".join(keywords(text, limit))


def jaccard(a: set[str] | list[str], b: set[str] | list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def overlap(query: set[str] | list[str], target: set[str] | list[str]) -> float:
    """Fraction of query keywords present in target."""
    sq, st = set(query), set(target)
    if not sq:
        return 0.0
    return len(sq & st) / len(sq)
