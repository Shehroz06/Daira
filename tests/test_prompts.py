from app.prompts import build_answer_prompt, format_source


def test_format_source_includes_all_available_metadata():
    doc = {
        "title": "Punjab Rented Premises Act 2009 — Section 8",
        "text": "Deposit must be refunded after lawful deductions.",
        "jurisdiction": "Pakistan",
        "province_or_state": "Punjab",
        "document_type": "statute",
        "authority_level": "primary",
        "year": 2009,
        "status": "active",
        "source": "simplified summary",
    }
    out = format_source(1, doc)
    assert out.startswith("[Source 1] Punjab Rented Premises Act 2009 — Section 8")
    assert "Jurisdiction: Punjab, Pakistan" in out
    assert "Type: statute" in out
    assert "Authority: primary" in out
    assert "Year: 2009" in out
    assert "Source: simplified summary" in out
    assert "STATUS" not in out  # active status is not flagged
    assert "Deposit must be refunded after lawful deductions." in out


def test_format_source_flags_non_active_status():
    doc = {"title": "Old Ordinance", "text": "...", "status": "repealed"}
    out = format_source(2, doc)
    assert "STATUS: REPEALED" in out


def test_format_source_tolerates_missing_metadata():
    doc = {"text": "Bare minimum chunk with no metadata at all."}
    out = format_source(1, doc)
    assert "[Source 1] Untitled" in out
    assert "Bare minimum chunk with no metadata at all." in out


def test_build_answer_prompt_includes_question_and_sources():
    sources = [{"title": "Example Act", "text": "Example text."}]
    prompt = build_answer_prompt("What are my rights?", sources)
    assert "What are my rights?" in prompt
    assert "[Source 1] Example Act" in prompt
    assert "Example text." in prompt
    assert "Conversation context" not in prompt


def test_build_answer_prompt_includes_context_when_present():
    sources = [{"title": "Example Act", "text": "Example text."}]
    prompt = build_answer_prompt("Follow-up question", sources, "User's jurisdiction is Punjab, Pakistan.")
    assert "Conversation context:" in prompt
    assert "User's jurisdiction is Punjab, Pakistan." in prompt
    assert prompt.index("Conversation context") < prompt.index("Follow-up question")
