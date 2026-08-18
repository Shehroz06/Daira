from app.legal_ranker import (
    _CURRENT_YEAR,
    _date_score,
    _domain_score,
    _jurisdiction_score,
    _status_score,
    authority_rank,
)


def test_jurisdiction_score_no_filter_is_neutral():
    assert _jurisdiction_score({"jurisdiction": "Pakistan"}, None, None) == 0.5


def test_jurisdiction_score_unknown_doc_metadata_is_neutral():
    assert _jurisdiction_score({}, "Pakistan", None) == 0.5


def test_jurisdiction_score_known_mismatch_is_zero():
    assert _jurisdiction_score({"jurisdiction": "India"}, "Pakistan", None) == 0.0


def test_jurisdiction_score_country_match_no_province_filter():
    assert _jurisdiction_score({"jurisdiction": "Pakistan"}, "Pakistan", None) == 1.0


def test_jurisdiction_score_province_match():
    doc = {"jurisdiction": "Pakistan", "province_or_state": "Punjab"}
    assert _jurisdiction_score(doc, "Pakistan", "Punjab") == 1.0


def test_jurisdiction_score_province_mismatch_partial_credit():
    doc = {"jurisdiction": "Pakistan", "province_or_state": "Sindh"}
    assert _jurisdiction_score(doc, "Pakistan", "Punjab") == 0.3


def test_jurisdiction_score_country_match_province_unknown():
    doc = {"jurisdiction": "Pakistan"}
    assert _jurisdiction_score(doc, "Pakistan", "Punjab") == 0.8


def test_domain_score_match_mismatch_and_unknown():
    assert _domain_score({"legal_domain": "employment"}, "employment") == 1.0
    assert _domain_score({"legal_domain": "contract_law"}, "employment") == 0.2
    assert _domain_score({}, "employment") == 0.5
    assert _domain_score({"legal_domain": "employment"}, None) == 0.5


def test_status_score():
    assert _status_score({"status": "active"}) == 1.0
    assert _status_score({}) == 1.0  # missing status defaults to active
    assert _status_score({"status": "amended"}) == 0.7
    assert _status_score({"status": "repealed"}) == 0.3


def test_date_score_current_year_is_full_score():
    assert _date_score({"year": _CURRENT_YEAR}) == 1.0


def test_date_score_unknown_year_is_neutral():
    assert _date_score({}) == 0.5


def test_date_score_older_documents_decay_but_stay_positive():
    old = _date_score({"year": _CURRENT_YEAR - 50})
    recent = _date_score({"year": _CURRENT_YEAR - 5})
    assert 0 < old < recent < 1.0


def test_authority_rank_empty_candidates():
    assert authority_rank([], []) == []


def test_authority_rank_prefers_higher_authority_at_equal_fused_score():
    docs = [
        {"authority_level": "constitutional"},
        {"authority_level": "web"},
    ]
    ranked = authority_rank([(0, 1.0), (1, 1.0)], docs)
    assert ranked[0][0] == 0
    assert ranked[0][1] > ranked[1][1]


def test_authority_rank_jurisdiction_mismatch_demotes_doc():
    docs = [
        {"authority_level": "primary", "jurisdiction": "Pakistan"},
        {"authority_level": "primary", "jurisdiction": "India"},
    ]
    ranked = authority_rank([(0, 1.0), (1, 1.0)], docs, jurisdiction="Pakistan")
    assert ranked[0][0] == 0


def test_authority_rank_repealed_doc_is_demoted_not_dropped():
    docs = [
        {"authority_level": "primary", "status": "active"},
        {"authority_level": "primary", "status": "repealed"},
    ]
    ranked = authority_rank([(0, 1.0), (1, 1.0)], docs)
    assert {idx for idx, _ in ranked} == {0, 1}
    assert ranked[0][0] == 0
    assert ranked[0][1] > ranked[1][1]
