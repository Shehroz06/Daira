"""Diara application logic.

Orchestrates one chat turn:

    question + session context
        │
        ▼
    legal_query.understand()      (heuristic or one LLM call)
        │
        ▼
    jurisdiction gate             (ask user if needed and unknown)
        │
        ▼
    rag.index.retrieve()          (hybrid + authority ranking + threshold)
        │
        ▼
    grounded prompt → llm.stream_generate()
        │
        ▼
    streamed chunks (+ debug event when DIARA_DEBUG)

Conversation context is bounded: a rolling window of recent turns plus
sticky facts (jurisdiction) extracted along the way.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Iterator, Optional

from . import chat_store, legal_query, prompts
from .llm import LLMError, stream_generate
from .rag import index

logger = logging.getLogger("diara.core")

DEBUG = os.getenv("DIARA_DEBUG", "false").strip().lower() in ("1", "true", "yes")

MAX_TURNS_IN_CONTEXT = 4          # last N user/assistant exchanges
MAX_CONTEXT_CHARS = 1200          # hard cap on context summary size
MAX_SESSIONS = 200                # bound in-memory session store

# This deployment is scoped to a specific jurisdiction, so default rather
# than interrupt every unscoped question with the jurisdiction gate — set
# either to "" to restore the original ask-if-unknown behavior.
DEFAULT_JURISDICTION = os.getenv("DIARA_DEFAULT_JURISDICTION", "Pakistan").strip() or None
DEFAULT_PROVINCE = os.getenv("DIARA_DEFAULT_PROVINCE", "Punjab").strip() or None

_HIGH_STAKES_WORDS = (
    "arrest", "criminal charge", "deadline", "court date", "hearing",
    "deport", "custody", "domestic violence", "threat", "sign this",
    "signature", "foreclosure",
)


@dataclass
class Session:
    turns: list[tuple[str, str]] = field(default_factory=list)  # (user, assistant)
    jurisdiction: Optional[str] = None
    province_or_state: Optional[str] = None
    last_used: float = field(default_factory=time.time)

    def context_summary(self) -> Optional[str]:
        """Bounded summary of recent conversation for the LLM/retrieval."""
        parts = []
        if self.jurisdiction:
            loc = self.jurisdiction
            if self.province_or_state:
                loc = f"{self.province_or_state}, {loc}"
            parts.append(f"The user's jurisdiction is {loc}.")
        for user, assistant in self.turns[-MAX_TURNS_IN_CONTEXT:]:
            parts.append(f"User said: {user[:200]}")
            if assistant:
                parts.append(f"Diara answered (summary): {assistant[:200]}")
        if not parts:
            return None
        return "\n".join(parts)[:MAX_CONTEXT_CHARS]

    def record(self, user: str, assistant: str) -> None:
        self.turns.append((user, assistant))
        if len(self.turns) > MAX_TURNS_IN_CONTEXT * 2:
            self.turns = self.turns[-MAX_TURNS_IN_CONTEXT:]
        self.last_used = time.time()


_sessions: dict[str, Session] = {}


def get_session(session_id: str) -> Session:
    if session_id not in _sessions:
        if len(_sessions) >= MAX_SESSIONS:
            oldest = min(_sessions, key=lambda k: _sessions[k].last_used)
            del _sessions[oldest]
        _sessions[session_id] = Session()
    return _sessions[session_id]


def chat(question: str, session_id: str = "default") -> Iterator[dict]:
    """Process one chat turn. Yields event dicts:

        {"type": "meta", ...}     provider/sources info (first)
        {"type": "chunk", "text": ...}  streamed answer text
        {"type": "debug", ...}    pipeline internals (only when DIARA_DEBUG)
        {"type": "error", ...}    controlled error message
    """
    t_start = time.time()
    question = (question or "").strip()
    if not question:
        yield {"type": "error", "message": "Empty question."}
        return

    session = get_session(session_id)
    context = session.context_summary()

    # ---------------- Query understanding
    t = time.time()
    lq = legal_query.understand(question, context)
    t_understand = time.time() - t

    # Sticky jurisdiction: remember it across turns; reuse if this turn lacks it
    if lq.jurisdiction:
        session.jurisdiction = lq.jurisdiction
        session.province_or_state = lq.province_or_state or session.province_or_state
    elif session.jurisdiction:
        lq.jurisdiction = session.jurisdiction
        lq.province_or_state = lq.province_or_state or session.province_or_state
    elif DEFAULT_JURISDICTION:
        # Never stated, never remembered — default instead of asking. Silent
        # on purpose: the answer shouldn't narrate this assumption.
        lq.jurisdiction = DEFAULT_JURISDICTION
        lq.province_or_state = lq.province_or_state or DEFAULT_PROVINCE
        session.jurisdiction = lq.jurisdiction
        session.province_or_state = lq.province_or_state

    # ---------------- Jurisdiction gate (only reachable if DEFAULT_JURISDICTION is unset)
    if lq.requires_jurisdiction and not lq.jurisdiction:
        msg = prompts.ASK_JURISDICTION_MESSAGE
        session.record(question, msg)
        chat_store.record_turn(session_id, question, msg)
        yield {"type": "meta", "provider": "none", "sources": [],
               "action": "ask_jurisdiction"}
        yield {"type": "chunk", "text": msg}
        if DEBUG:
            yield {"type": "debug", "legal_query": lq.to_dict(),
                   "understanding_time": round(t_understand, 3)}
        return

    # ---------------- Retrieval
    result = index.retrieve(
        lq.retrieval_query or question,
        jurisdiction=lq.jurisdiction,
        province_or_state=lq.province_or_state,
        legal_domain=lq.legal_domain,
    )

    if not result["relevant"]:
        msg = prompts.NO_SOURCES_MESSAGE
        session.record(question, msg)
        chat_store.record_turn(session_id, question, msg)
        yield {"type": "meta", "provider": "none", "sources": [],
               "action": "no_sources"}
        yield {"type": "chunk", "text": msg}
        if DEBUG:
            yield {"type": "debug", "legal_query": lq.to_dict(),
                   "retrieval": result["debug"],
                   "understanding_time": round(t_understand, 3)}
        return

    sources = result["sources"]

    # ---------------- Grounded generation (streamed)
    high_stakes = any(w in question.lower() for w in _HIGH_STAKES_WORDS)
    user_prompt = prompts.build_answer_prompt(question, sources, context)
    if high_stakes:
        user_prompt += ("\n\nNote: this situation may be high-stakes. Alongside the "
                        "grounded information, clearly encourage consulting a "
                        "qualified local lawyer or legal aid service.")

    try:
        t = time.time()
        stream, provider = stream_generate(user_prompt, system=prompts.LEGAL_SYSTEM_PROMPT)
    except LLMError as exc:
        logger.error("All providers failed: %s", exc)
        yield {"type": "error",
               "message": "The language model is currently unavailable. "
                          "Please check that Ollama is running and try again."}
        return

    sources_meta = [{"id": d.get("id"), "title": d.get("title"),
                     "section": d.get("section"),
                     "jurisdiction": d.get("jurisdiction"),
                     "source": d.get("source")} for d in sources]
    yield {"type": "meta", "provider": provider, "sources": sources_meta}

    answer_parts: list[str] = []
    try:
        for chunk in stream:
            answer_parts.append(chunk)
            yield {"type": "chunk", "text": chunk}
    except Exception as exc:
        logger.error("Stream failed mid-generation: %s", exc)
        if not answer_parts:
            yield {"type": "error", "message": "Generation failed. Please try again."}
            return
    t_generate = time.time() - t

    answer = "".join(answer_parts)
    session.record(question, answer[:500])
    chat_store.record_turn(session_id, question, answer,
                            provider=provider, sources=sources_meta)

    if DEBUG:
        yield {"type": "debug",
               "legal_query": lq.to_dict(),
               "retrieval": result["debug"],
               "provider": provider,
               "understanding_time": round(t_understand, 3),
               "generation_time": round(t_generate, 3),
               "total_time": round(time.time() - t_start, 3)}
