import pytest

from app import chat_store


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(chat_store, "DB_PATH", tmp_path / "test_chats.db")
    chat_store.init_db()


def test_init_db_is_idempotent():
    chat_store.init_db()
    chat_store.init_db()
    assert chat_store.DB_PATH.exists()


def test_record_turn_creates_chat_and_messages():
    long_answer = "x" * 800  # longer than Session's 500-char cap
    chat_store.record_turn(
        "chat-1", "What is theft?", long_answer,
        provider="gemini", sources=[{"id": "ppc-section-379"}],
    )
    chat = chat_store.get_chat("chat-1")
    assert chat is not None
    assert chat["id"] == "chat-1"
    assert len(chat["messages"]) == 2
    user_msg, assistant_msg = chat["messages"]
    assert user_msg["role"] == "user"
    assert user_msg["text"] == "What is theft?"
    assert assistant_msg["role"] == "assistant"
    assert assistant_msg["text"] == long_answer  # not truncated
    assert assistant_msg["provider"] == "gemini"
    assert assistant_msg["sources"] == [{"id": "ppc-section-379"}]


def test_record_turn_appends_to_existing_chat():
    chat_store.record_turn("chat-1", "First question", "First answer")
    first = chat_store.list_chats()[0]
    chat_store.record_turn("chat-1", "Second question", "Second answer")
    chat = chat_store.get_chat("chat-1")
    assert len(chat["messages"]) == 4
    assert chat["title"] == first["title"]  # title set once, not overwritten
    second = chat_store.list_chats()[0]
    assert second["updated_at"] >= first["updated_at"]


def test_record_turn_without_provider_or_sources():
    chat_store.record_turn("chat-1", "Where am I?", "Please tell me your jurisdiction.")
    chat = chat_store.get_chat("chat-1")
    assistant_msg = chat["messages"][1]
    assert assistant_msg["provider"] is None
    assert assistant_msg["sources"] is None


def test_title_derivation_truncates_long_questions():
    long_question = "word " * 30  # well over 60 chars
    chat_store.record_turn("chat-1", long_question, "answer")
    chat = chat_store.get_chat("chat-1")
    assert len(chat["title"]) <= 61
    assert chat["title"].endswith("…")


def test_title_derivation_keeps_short_questions_verbatim():
    chat_store.record_turn("chat-1", "What is theft?", "answer")
    chat = chat_store.get_chat("chat-1")
    assert chat["title"] == "What is theft?"


def test_list_chats_orders_by_recency():
    chat_store.record_turn("chat-a", "q", "a")
    chat_store.record_turn("chat-b", "q", "a")
    chat_store.record_turn("chat-a", "q2", "a2")  # touch A again
    ids = [c["id"] for c in chat_store.list_chats()]
    assert ids == ["chat-a", "chat-b"]


def test_list_chats_empty():
    assert chat_store.list_chats() == []


def test_get_chat_missing_returns_none():
    assert chat_store.get_chat("does-not-exist") is None


def test_delete_chat():
    chat_store.record_turn("chat-1", "q", "a")
    assert chat_store.delete_chat("chat-1") is True
    assert chat_store.get_chat("chat-1") is None
    assert chat_store.list_chats() == []
    assert chat_store.delete_chat("chat-1") is False


def test_graceful_degradation_on_unwritable_db_path(tmp_path, monkeypatch):
    monkeypatch.setattr(chat_store, "DB_PATH", tmp_path / "nonexistent_dir" / "readonly" / "chats.db")
    # Make the intended parent unwritable-by-mkdir by occupying its name with a file.
    (tmp_path / "nonexistent_dir").write_text("not a directory")

    chat_store.init_db()  # must not raise
    chat_store.record_turn("chat-1", "q", "a")  # must not raise
    assert chat_store.list_chats() == []
    assert chat_store.get_chat("chat-1") is None
    assert chat_store.delete_chat("chat-1") is False
