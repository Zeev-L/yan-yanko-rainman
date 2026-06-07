"""
Semantic retrieval tests.

Cover the zero-dependency semantic layer added on top of exact keyword
matching: stemming (plurals/verb forms), punctuation-robust tokenization,
and curated synonym expansion — while keeping precision (no false matches).
"""

import os
import time
import pytest

from rainman.core.models import Memory
from rainman.core.scoring import keyword_score
from rainman.core.text import tokenize, stem, normalize_terms, token_relevance
from rainman.core.engine import RainmanEngine


def _mem(content, **kwargs):
    defaults = {
        "id": f"rm_test_{id(content)}",
        "content": content,
        "timestamp": time.time(),
        "importance": 0.5,
    }
    defaults.update(kwargs)
    return Memory(**defaults)


@pytest.fixture
def engine(tmp_path):
    project = str(tmp_path / "project")
    global_dir = str(tmp_path / "global")
    os.makedirs(project)
    os.makedirs(global_dir)
    e = RainmanEngine(project_dir=project, global_dir=global_dir)
    e.store.init_project(project)
    e.store.init_global()
    return e


@pytest.mark.unit
class TestTokenizer:

    def test_strips_punctuation(self):
        assert tokenize("Fixed the bug.") == ["fixed", "bug"]

    def test_splits_hyphens_and_slashes(self):
        assert tokenize("services/api/auth.py") == ["services", "api", "auth", "py"]

    def test_drops_stopwords(self):
        assert "the" not in tokenize("the database is on the server")

    def test_stem_plurals_and_verbs(self):
        assert stem("tokens") == stem("token")
        assert stem("migrations") == "migration"
        assert stem("running") == "runn" or stem("running") == "run"


@pytest.mark.unit
class TestSynonymMatching:
    """The headline fix: paraphrases match even with no shared words."""

    def test_electoral_skew_matches_voting_bias(self):
        m = _mem("systematic voting bias in the prediction model")
        # No literal word overlap with the query at all.
        assert keyword_score(m, ["electoral", "skew"]) > 0.0

    def test_db_matches_database(self):
        m = _mem("the database connection pool leaks under load")
        assert keyword_score(m, ["db", "leak"]) > 0.0

    def test_auth_matches_authentication(self):
        m = _mem("login flow validates the session")
        assert keyword_score(m, ["authentication"]) > 0.0


@pytest.mark.unit
class TestStemMatching:

    def test_plural_query_matches_singular_memory(self):
        m = _mem("JWT token validation logic")
        assert keyword_score(m, ["tokens"]) > 0.0

    def test_verb_form_matches(self):
        m = _mem("database migrations were applied cleanly")
        assert keyword_score(m, ["migration"]) > 0.0


@pytest.mark.unit
class TestPrecisionPreserved:
    """Semantic expansion must not invent matches between unrelated terms."""

    def test_unrelated_terms_score_zero(self):
        m = _mem("database migration script")
        assert keyword_score(m, ["caching", "redis"]) == 0.0

    def test_completely_unrelated_zero(self):
        m = _mem("css dark mode toggle styling")
        assert keyword_score(m, ["kubernetes", "helm"]) == 0.0

    def test_empty_query_zero(self):
        assert keyword_score(_mem("anything"), []) == 0.0


@pytest.mark.unit
class TestEndToEndRecall:

    def test_recall_finds_paraphrased_memory(self, engine):
        engine.add("political identity assignment causes voting bias", category="failure")
        engine.add("css dark mode toggle fix", category="solution")
        results = engine.recall("electoral skew problem")
        assert results
        assert "voting bias" in results[0].memory.content
