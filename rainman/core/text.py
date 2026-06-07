"""
Text Normalization & Semantic Expansion
========================================

Shared text layer for retrieval. Turns raw strings into normalized tokens,
strips inflection with lightweight stemming, and expands queries with a
curated synonym map so paraphrases match ("electoral skew" -> "voting bias").

Design constraints (same as the rest of Rainman):
- Zero external dependencies — stdlib only (re).
- Zero LLM calls — pure deterministic compute.

Matching strategy used by the scorer:
- exact token match            -> full weight (1.0)
- shared stem (plural/verb)    -> full weight (1.0)
- shared synonym group         -> partial weight (SYNONYM_WEIGHT)
"""

import re
from typing import Dict, FrozenSet, List, Set


# Weight given to a synonym-group match relative to an exact/stem match.
SYNONYM_WEIGHT = 0.6

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Common English fillers + a few dev-doc fillers. Removed before scoring so
# they don't dilute the overlap ratio.
STOPWORDS: FrozenSet[str] = frozenset({
    "the", "a", "an", "and", "or", "but", "if", "then", "else", "for", "of",
    "to", "in", "on", "at", "by", "is", "are", "was", "were", "be", "been",
    "it", "its", "this", "that", "these", "those", "with", "as", "from",
    "into", "out", "up", "down", "we", "you", "they", "he", "she", "i",
    "do", "does", "did", "has", "have", "had", "not", "no", "so", "than",
    "via", "about", "over", "after", "before", "when", "while", "use", "using",
})

# Synonym groups — every word in a group is treated as semantically equal.
# Matched on STEMS, so "migrations" still maps through "migration".
# Keep groups tight: spurious cross-links hurt precision.
_SYNONYM_GROUPS: List[Set[str]] = [
    {"bias", "skew", "lean", "slant", "tilt", "imbalance", "skewed", "biased"},
    {"bug", "error", "defect", "issue", "fault", "broken", "crash", "failure"},
    {"fix", "fixed", "patch", "resolve", "resolved", "repair", "solution", "remedy"},
    {"auth", "authentication", "authenticate", "login", "signin", "credential", "credentials"},
    {"db", "database", "datastore", "rdbms"},
    {"migration", "migrate", "migrations"},
    {"cache", "caching", "cached", "memoize", "memoization"},
    {"election", "electoral", "voting", "vote", "voter", "ballot", "poll", "polling"},
    {"performance", "perf", "latency", "throughput", "slow", "speedup"},
    {"config", "configuration", "settings", "configure"},
    {"deploy", "deployment", "release", "rollout", "ship", "shipped"},
    {"endpoint", "route", "handler", "api"},
    {"timeout", "deadline", "expiry", "expire", "expired", "ttl"},
    {"concurrency", "async", "asyncio", "parallel", "threading", "thread"},
    {"validate", "validation", "verify", "verification", "check"},
    {"refactor", "refactoring", "cleanup", "restructure"},
    {"docs", "documentation", "readme", "doc"},
    {"rate-limit", "ratelimit", "throttle", "throttling"},
]


def tokenize(text: str) -> List[str]:
    """Lowercase, split on non-alphanumeric, drop stopwords and 1-char tokens."""
    if not text:
        return []
    return [
        t for t in _TOKEN_RE.findall(text.lower())
        if len(t) > 1 and t not in STOPWORDS
    ]


def stem(word: str) -> str:
    """
    Lightweight inflectional stemmer (handles plurals + common verb endings).
    Intentionally conservative — derivational variants are handled by synonyms.
    """
    w = word
    if len(w) > 4:
        if w.endswith("ing"):
            w = w[:-3]
        elif w.endswith("ed"):
            w = w[:-2]
    if len(w) > 3:
        if w.endswith("ies"):
            w = w[:-3] + "y"
        elif w.endswith("es"):
            w = w[:-2]
        elif w.endswith("s"):
            w = w[:-1]
    return w


def _build_synonym_index() -> Dict[str, FrozenSet[str]]:
    """Map each member's stem -> frozenset of all stems in its group."""
    index: Dict[str, FrozenSet[str]] = {}
    for group in _SYNONYM_GROUPS:
        # Stem every member so "migrations"/"migrate" share the group.
        group_stems = frozenset(stem(w) for member in group for w in _TOKEN_RE.findall(member.lower()))
        for member in group:
            for w in _TOKEN_RE.findall(member.lower()):
                index[stem(w)] = group_stems
    return index


_SYNONYM_INDEX: Dict[str, FrozenSet[str]] = _build_synonym_index()


def normalize_terms(words: List[str]) -> List[str]:
    """Re-tokenize an incoming word list into clean, de-duplicated tokens."""
    seen: Set[str] = set()
    out: List[str] = []
    for word in words:
        for tok in tokenize(word):
            if tok not in seen:
                seen.add(tok)
                out.append(tok)
    return out


def token_relevance(query_token: str, mem_tokens: Set[str], mem_stems: Set[str]) -> float:
    """
    How well a single query token matches a memory's token/stem sets.
    Returns 1.0 (exact or stem), SYNONYM_WEIGHT (synonym group), or 0.0.
    """
    if query_token in mem_tokens:
        return 1.0
    qs = stem(query_token)
    if qs in mem_stems:
        return 1.0
    group = _SYNONYM_INDEX.get(qs)
    if group and (group & mem_stems):
        return SYNONYM_WEIGHT
    return 0.0


def stems_of(tokens: List[str]) -> Set[str]:
    """Stem set for a list of tokens."""
    return {stem(t) for t in tokens}
