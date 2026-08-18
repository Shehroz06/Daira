from app import llm


def test_safe_parse_json_plain_object():
    assert llm._safe_parse_json('{"a": 1, "b": "two"}') == {"a": 1, "b": "two"}


def test_safe_parse_json_strips_markdown_fence():
    text = '```json\n{"a": 1}\n```'
    assert llm._safe_parse_json(text) == {"a": 1}


def test_safe_parse_json_strips_bare_fence():
    text = '```\n{"a": 1}\n```'
    assert llm._safe_parse_json(text) == {"a": 1}


def test_safe_parse_json_extracts_object_from_surrounding_prose():
    text = 'Sure, here is the JSON:\n{"a": 1, "b": 2}\nHope that helps!'
    assert llm._safe_parse_json(text) == {"a": 1, "b": 2}


def test_safe_parse_json_rejects_non_object_json():
    assert llm._safe_parse_json("[1, 2, 3]") is None
    assert llm._safe_parse_json('"just a string"') is None


def test_safe_parse_json_returns_none_for_garbage():
    assert llm._safe_parse_json("not json at all") is None
    assert llm._safe_parse_json("") is None
    assert llm._safe_parse_json(None) is None


def test_gemini_available_requires_key_enabled_and_provider_mode(monkeypatch):
    monkeypatch.setattr(llm, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm, "GEMINI_ENABLED", True)
    monkeypatch.setattr(llm, "LLM_PROVIDER", "auto")
    assert llm.gemini_available() is True

    monkeypatch.setattr(llm, "GEMINI_API_KEY", "")
    assert llm.gemini_available() is False

    monkeypatch.setattr(llm, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm, "GEMINI_ENABLED", False)
    assert llm.gemini_available() is False

    monkeypatch.setattr(llm, "GEMINI_ENABLED", True)
    monkeypatch.setattr(llm, "LLM_PROVIDER", "ollama")
    assert llm.gemini_available() is False


def test_ollama_allowed_respects_provider_mode(monkeypatch):
    monkeypatch.setattr(llm, "LLM_PROVIDER", "auto")
    assert llm._ollama_allowed() is True

    monkeypatch.setattr(llm, "LLM_PROVIDER", "ollama")
    assert llm._ollama_allowed() is True

    monkeypatch.setattr(llm, "LLM_PROVIDER", "gemini")
    assert llm._ollama_allowed() is False


def test_gemini_rate_limit_allows_calls_under_the_cap(monkeypatch):
    monkeypatch.setattr(llm, "GEMINI_MAX_RPM", 3)
    monkeypatch.setattr(llm, "_gemini_call_times", __import__("collections").deque())
    assert llm._gemini_under_rate_limit() is True
    llm._record_gemini_call()
    llm._record_gemini_call()
    assert llm._gemini_under_rate_limit() is True


def test_gemini_rate_limit_blocks_at_the_cap(monkeypatch):
    monkeypatch.setattr(llm, "GEMINI_MAX_RPM", 3)
    monkeypatch.setattr(llm, "_gemini_call_times", __import__("collections").deque())
    for _ in range(3):
        llm._record_gemini_call()
    assert llm._gemini_under_rate_limit() is False


def test_gemini_rate_limit_expires_old_calls(monkeypatch):
    import time
    from collections import deque

    monkeypatch.setattr(llm, "GEMINI_MAX_RPM", 1)
    old_call = time.time() - 61  # just outside the 60s window
    monkeypatch.setattr(llm, "_gemini_call_times", deque([old_call]))
    assert llm._gemini_under_rate_limit() is True


def test_gemini_ready_requires_availability_and_rate_limit(monkeypatch):
    from collections import deque

    monkeypatch.setattr(llm, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(llm, "GEMINI_ENABLED", True)
    monkeypatch.setattr(llm, "LLM_PROVIDER", "auto")
    monkeypatch.setattr(llm, "GEMINI_MAX_RPM", 1)
    monkeypatch.setattr(llm, "_gemini_call_times", deque())

    assert llm._gemini_ready() is True
    llm._record_gemini_call()
    assert llm._gemini_ready() is False  # available, but over the cap

    monkeypatch.setattr(llm, "GEMINI_API_KEY", "")
    assert llm._gemini_ready() is False  # not available at all
