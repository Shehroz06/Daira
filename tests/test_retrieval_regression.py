"""Live regression test for the specific PPC ranking failures the forensic
audit diagnosed (see audit/retrieval_evaluation.md, audit/error_analysis.md,
audit/recommendations.md #12.2): lay-phrased criminal queries retrieving
PPC's General Part (Sections 1-120: generic "whoever commits an offence"
language) instead of the specific offence section actually asked about.

Unlike the rest of tests/, this hits the real corpus + real Ollama
embeddings (no mocking) — the bug is a property of the actual PPC content
and ranking formula, not something a small synthetic fixture would
reproduce. Skips gracefully (not a failure) if the real index or Ollama
isn't available, so `pytest tests/` stays hermetic/network-free by default;
run explicitly (`pytest tests/test_retrieval_regression.py`) with Ollama
running to actually exercise it.
"""

import pytest

from app import legal_query
from app.rag import LegalIndex


@pytest.fixture(scope="module")
def index():
    idx = LegalIndex()
    idx.load()
    if not idx.docs or not idx.embed_ok:
        pytest.skip("Real corpus/embeddings not available (Ollama not running?)")
    return idx


CASES = [
    # (query, must-contain-in-top-5, must-NOT-outrank-correct wrong answer)
    ("What is the punishment for theft?", "ppc-section-379", None),
    ("I did a murder what happens to me?", "ppc-section-302", "ppc-section-324"),
    ("Not attempt, completed murder.", "ppc-section-302", "ppc-section-396"),
    ("Qatl-i-amd punishment", "ppc-section-302", None),
    ("Attempt to commit murder", "ppc-section-324", None),
    ("Dacoity with murder", "ppc-section-396", None),
    ("Robbery punishment", "ppc-section-390", None),
]


@pytest.mark.parametrize("query,expected_id,must_not_outrank", CASES)
def test_specific_offence_beats_general_part(index, query, expected_id, must_not_outrank):
    lq = legal_query.understand(query, context_summary=None)
    out = index.retrieve(
        lq.retrieval_query,
        jurisdiction=lq.jurisdiction,
        province_or_state=lq.province_or_state,
        legal_domain=lq.legal_domain,
        k=5,
    )
    got_ids = [d["id"] for d in out["sources"]]
    assert expected_id in got_ids, (
        f"{query!r}: expected {expected_id} in top-5, got {got_ids}"
    )
    if must_not_outrank and must_not_outrank in got_ids:
        assert got_ids.index(expected_id) < got_ids.index(must_not_outrank), (
            f"{query!r}: {must_not_outrank} outranked {expected_id} — "
            f"got {got_ids}"
        )


def test_semantically_similar_but_legally_different_not_confused(index):
    """Symptom-4-style check: a query about a completed, simple murder should
    not be dominated by dacoity-with-murder (a much rarer, aggravated,
    multi-offender variant) even though both mention murder."""
    lq = legal_query.understand("Not attempt, completed murder.", context_summary=None)
    out = index.retrieve(
        lq.retrieval_query,
        jurisdiction=lq.jurisdiction,
        province_or_state=lq.province_or_state,
        legal_domain=lq.legal_domain,
        k=5,
    )
    got_ids = [d["id"] for d in out["sources"]]
    assert "ppc-section-302" in got_ids
    if "ppc-section-396" in got_ids:
        assert got_ids.index("ppc-section-302") < got_ids.index("ppc-section-396")
