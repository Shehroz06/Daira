from app.legal_query import (
    _detect_domain,
    _detect_jurisdiction,
    _heuristic_query,
    _validate,
    is_complex,
)


def test_detect_jurisdiction_explicit_country():
    assert _detect_jurisdiction("I live in Pakistan") == ("Pakistan", None)


def test_detect_jurisdiction_country_and_province():
    assert _detect_jurisdiction("I live in Punjab, Pakistan") == ("Pakistan", "Punjab")


def test_detect_jurisdiction_province_without_country_infers_from_city():
    country, province = _detect_jurisdiction("My landlord in Lahore, Punjab kept my deposit")
    assert country == "Pakistan"
    assert province == "Punjab"


def test_detect_jurisdiction_province_alone_is_ambiguous():
    country, province = _detect_jurisdiction("I live in Punjab")
    assert country is None
    assert province == "Punjab"


def test_detect_jurisdiction_india():
    assert _detect_jurisdiction("I live in Punjab, India") == ("India", "Punjab")


def test_detect_jurisdiction_none_when_absent():
    assert _detect_jurisdiction("What is a contract?") == (None, None)


def test_detect_domain_landlord_tenant():
    assert _detect_domain("My landlord won't return my rent deposit") == "landlord_tenant"


def test_detect_domain_employment():
    assert _detect_domain("My employer fired me and won't pay my wages") == "employment"


def test_detect_domain_none_for_unrelated_text():
    assert _detect_domain("How do I bake a cake?") is None


def test_detect_domain_recognizes_ppc_abbreviation():
    # "PPC" alone (no words like "criminal" or "murder") must still resolve
    # to criminal_law, otherwise "Section 302 PPC" queries get no domain
    # boost and can be outranked by an unrelated Act's identically numbered
    # section.
    assert _detect_domain("What does section 302 PPC say?") == "criminal_law"


def test_is_complex_simple_question_is_not_complex():
    assert is_complex("What is a contract?", has_context=False) is False


def test_is_complex_pronoun_with_context_is_complex():
    assert is_complex("Can I challenge this?", has_context=True) is True


def test_is_complex_pronoun_without_context_is_not_forced_complex():
    assert is_complex("Can I challenge this?", has_context=False) is False


def test_is_complex_comparison_hint_needs_multiple_sentences_or_length():
    # A comparison hint alone isn't enough — is_complex also requires either
    # >=2 sentences or a long single question, to avoid spending an LLM call
    # on short queries.
    short_q = "What is the difference between rent and lease?"
    assert is_complex(short_q, has_context=False) is False

    two_sentence_q = ("What is the difference between a void contract and a "
                       "voidable contract? Which one applies to my situation?")
    assert is_complex(two_sentence_q, has_context=False) is True


def test_validate_accepts_known_fields_and_drops_unknown():
    raw = {
        "jurisdiction": "Pakistan",
        "province_or_state": "Punjab",
        "legal_domain": "landlord_tenant",
        "issue": "security_deposit",
        "facts": ["landlord kept deposit"],
        "question_type": "legal_rights",
        "requires_jurisdiction": True,
        "retrieval_query": "tenant security deposit rights Punjab Pakistan",
        "malicious_field": "should be dropped",
    }
    lq = _validate(raw, "My landlord kept my deposit")
    assert lq is not None
    assert lq.jurisdiction == "Pakistan"
    assert lq.province_or_state == "Punjab"
    assert lq.legal_domain == "landlord_tenant"
    assert lq.facts == ["landlord kept deposit"]
    assert lq.requires_jurisdiction is True
    assert not hasattr(lq, "malicious_field")


def test_validate_coerces_unknown_domain_and_question_type_to_other():
    raw = {"legal_domain": "not_a_real_domain", "question_type": "not_a_real_type"}
    lq = _validate(raw, "question")
    assert lq.legal_domain == "other"
    assert lq.question_type == "other"


def test_validate_rejects_non_dict():
    assert _validate(["not", "a", "dict"], "question") is None
    assert _validate(None, "question") is None


def test_validate_falls_back_to_question_when_retrieval_query_missing():
    lq = _validate({}, "raw question text")
    assert lq.retrieval_query == "raw question text"


def test_validate_ignores_non_string_facts():
    raw = {"facts": ["valid fact", 123, None, "  ", "another fact"]}
    lq = _validate(raw, "question")
    assert lq.facts == ["valid fact", "another fact"]


# ---------------------------------------------- heuristic context isolation

def test_heuristic_query_self_contained_question_ignores_unrelated_context():
    """Regression test: a topically-independent question must not inherit
    an unrelated earlier turn's domain or retrieval text. Previously, a
    "what is my minimum wage?" follow-up right after a murder-punishment
    question kept retrieving murder sections, because the heuristic path
    always blended the full prior context into both domain detection and
    the retrieval query — the earlier turn's dense vocabulary dominated the
    new, unrelated question."""
    context = ("The user's jurisdiction is Punjab, Pakistan.\n"
               "User said: what is the minimum punishment of murder?\n"
               "Daira answered (summary): Under Pakistan law, the punishment for "
               "murder (qatl-i-amd) includes death as qisas, death or imprisonment "
               "for life as ta'zir depending on circumstances.")
    lq = _heuristic_query("what is my minimum wage?", context)
    assert lq.legal_domain == "employment"
    assert lq.retrieval_query == "what is my minimum wage?"
    assert "murder" not in lq.retrieval_query
    assert "qisas" not in lq.retrieval_query


def test_heuristic_query_bare_jurisdiction_reply_still_uses_context():
    """A reply with no domain signal of its own (just answering the
    jurisdiction gate) still needs context to recover the actual topic."""
    context = ("User said: what is the minimum punishment of murder?\n"
               "Daira answered (summary): Under Pakistan law...")
    lq = _heuristic_query("in Pakistan", context)
    assert lq.legal_domain == "criminal_law"
    assert "murder" in lq.retrieval_query


def test_heuristic_query_no_context_uses_question_alone():
    lq = _heuristic_query("what is my minimum wage?", None)
    assert lq.legal_domain == "employment"
    assert lq.retrieval_query == "what is my minimum wage?"
