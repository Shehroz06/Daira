"""Legal query understanding for Daira.

Converts a natural-language question (plus bounded conversation context)
into a validated structured legal intent:

    {
      jurisdiction, province_or_state, legal_domain, issue,
      facts, question_type, requires_jurisdiction, retrieval_query
    }

Policy (Gemini usage discipline):
  - Simple queries -> cheap local heuristics only, no LLM call.
  - Complex queries -> one structured LLM call (Gemini preferred,
    Ollama fallback), validated strictly.
  - Any failure -> fall back to the raw natural-language query.
    Query understanding must never crash retrieval.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from .llm import generate_structured
from .prompts import QUERY_UNDERSTANDING_SYSTEM, build_query_understanding_prompt

logger = logging.getLogger("daira.legal_query")

ALLOWED_FIELDS = {
    "jurisdiction", "province_or_state", "legal_domain", "issue",
    "facts", "question_type", "requires_jurisdiction", "retrieval_query",
}
ALLOWED_DOMAINS = {
    "landlord_tenant", "employment", "consumer_law", "contract_law",
    "constitutional_law", "criminal_law", "family_law", "immigration",
    "company_law", "traffic_law", "other",
}
ALLOWED_QUESTION_TYPES = {
    "legal_rights", "definition", "procedure", "comparison",
    "document_analysis", "other",
}


@dataclass
class LegalQuery:
    jurisdiction: Optional[str] = None
    province_or_state: Optional[str] = None
    legal_domain: Optional[str] = None
    issue: Optional[str] = None
    facts: list[str] = field(default_factory=list)
    question_type: Optional[str] = None
    requires_jurisdiction: bool = False
    retrieval_query: str = ""
    provider: str = "heuristic"   # heuristic | gemini | ollama | fallback

    def to_dict(self) -> dict:
        return {
            "jurisdiction": self.jurisdiction,
            "province_or_state": self.province_or_state,
            "legal_domain": self.legal_domain,
            "issue": self.issue,
            "facts": self.facts,
            "question_type": self.question_type,
            "requires_jurisdiction": self.requires_jurisdiction,
            "retrieval_query": self.retrieval_query,
            "provider": self.provider,
        }


# --------------------------------------------------------------------------
# Local heuristics (no LLM)
# --------------------------------------------------------------------------

_JURISDICTIONS = {
    "pakistan": "Pakistan",
    "india": "India",
}
_PROVINCES = {
    "punjab": "Punjab",
    "sindh": "Sindh",
    "balochistan": "Balochistan",
    "khyber pakhtunkhwa": "Khyber Pakhtunkhwa",
}
_DOMAIN_KEYWORDS = {
    "landlord_tenant": ["landlord", "tenant", "rent", "deposit", "evict", "lease", "premises"],
    "employment": ["employer", "employee", "wages", "salary", "fired", "dismissal",
                   "workplace", "job", "overtime", "pay me", "minimum wage",
                   "working hours", "leave", "maternity", "paternity", "sick leave"],
    "consumer_law": ["consumer", "product", "refund", "defective", "warranty",
                     "shop", "purchase", "faulty"],
    "contract_law": ["contract", "agreement", "clause", "breach", "penalty",
                     "consideration", "void", "sign"],
    "constitutional_law": ["constitution", "fundamental right", "article",
                           "fair trial", "due process"],
    "criminal_law": ["arrest", "police", "criminal", "charge", "bail", "fir",
                     "theft", "murder", "qatl", "punishment", "offence", "penal code",
                     "ppc", "crpc", "pakistan penal code"],
    "family_law": ["divorce", "custody", "marriage", "inheritance", "nikah"],
    "immigration": ["visa", "deport", "immigration", "citizenship", "asylum"],
    "company_law": ["company", "incorporation", "shareholder", "director",
                    "registrar of companies", "securities and exchange commission"],
    "traffic_law": ["traffic", "driving license", "vehicle", "motor vehicle",
                    "road", "challan", "speeding"],
}

# Indicators that a query is complex enough to justify an LLM understanding call
_COMPLEX_HINTS = [
    " and ", " but ", " however ", " compare", " difference between",
    " versus ", " vs ", "this clause", "this contract", "this decision",
    "challenge", "what should i do", "what are my options",
]
_PRONOUN_REFS = re.compile(r"\b(this|that|it|they|them)\b", re.IGNORECASE)


def _detect_jurisdiction(text: str) -> tuple[Optional[str], Optional[str]]:
    low = text.lower()
    country = next((v for k, v in _JURISDICTIONS.items() if k in low), None)
    province = next((v for k, v in _PROVINCES.items() if k in low), None)
    # "Punjab" alone is ambiguous (PK or IN); only trust province with a country
    # or default to Pakistan-focused corpus when explicitly Pakistani cities appear.
    if province and not country:
        if any(c in low for c in ("lahore", "karachi", "islamabad", "rawalpindi")):
            country = "Pakistan"
    return country, province


def _detect_domain(text: str) -> Optional[str]:
    low = text.lower()
    best, best_hits = None, 0
    for domain, words in _DOMAIN_KEYWORDS.items():
        hits = sum(1 for w in words if w in low)
        if hits > best_hits:
            best, best_hits = domain, hits
    return best


def is_complex(question: str, has_context: bool) -> bool:
    """Decide whether to spend an LLM call on query understanding."""
    low = question.lower()
    if has_context and _PRONOUN_REFS.search(low):
        return True  # conversational reference resolution needs the LLM
    hints = sum(1 for h in _COMPLEX_HINTS if h in low)
    sentences = len(re.findall(r"[.!?]+", question)) or 1
    return hints >= 1 and (sentences >= 2 or len(question) > 120)


def _heuristic_query(question: str,
                     context_summary: Optional[str]) -> LegalQuery:
    combined = f"{context_summary or ''} {question}"
    country, province = _detect_jurisdiction(combined)

    # Prefer the current question's own domain signal. A question that
    # clearly carries its own topic is treated as self-contained, so an
    # unrelated earlier turn can't hijack it — e.g. asking about wages right
    # after asking about murder punishment must not keep retrieving murder
    # sections just because the prior turn's text dominates a blended query.
    # A question with no domain signal of its own (a bare jurisdiction
    # reply like "in Pakistan") still needs context to recover what's
    # actually being asked — is_complex() already routes anything needing
    # real pronoun/reference resolution to the LLM path instead of here.
    own_domain = _detect_domain(question)
    if own_domain:
        domain = own_domain
        retrieval_query = question
    else:
        domain = _detect_domain(combined)
        retrieval_query = question if not context_summary else f"{context_summary} {question}"

    is_definition = bool(re.match(
        r"^\s*(what is|what does .* mean|define|difference between)", question.lower()))
    return LegalQuery(
        jurisdiction=country,
        province_or_state=province,
        legal_domain=domain,
        question_type="definition" if is_definition else "legal_rights",
        requires_jurisdiction=not is_definition and domain is not None,
        retrieval_query=retrieval_query,
        provider="heuristic",
    )


# --------------------------------------------------------------------------
# Validation of LLM output
# --------------------------------------------------------------------------

def _validate(raw: dict, question: str) -> Optional[LegalQuery]:
    """Strictly validate LLM JSON. Unknown fields dropped; wrong types rejected."""
    if not isinstance(raw, dict):
        return None
    data = {k: v for k, v in raw.items() if k in ALLOWED_FIELDS}

    def opt_str(key: str) -> Optional[str]:
        v = data.get(key)
        return v.strip() if isinstance(v, str) and v.strip() else None

    domain = opt_str("legal_domain")
    if domain and domain not in ALLOWED_DOMAINS:
        domain = "other"
    qtype = opt_str("question_type")
    if qtype and qtype not in ALLOWED_QUESTION_TYPES:
        qtype = "other"

    facts_raw = data.get("facts")
    facts = [f.strip() for f in facts_raw if isinstance(f, str) and f.strip()] \
        if isinstance(facts_raw, list) else []

    retrieval_query = opt_str("retrieval_query") or question

    return LegalQuery(
        jurisdiction=opt_str("jurisdiction"),
        province_or_state=opt_str("province_or_state"),
        legal_domain=domain,
        issue=opt_str("issue"),
        facts=facts[:10],
        question_type=qtype,
        requires_jurisdiction=bool(data.get("requires_jurisdiction", False)),
        retrieval_query=retrieval_query[:600],
    )


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------

def understand(question: str, context_summary: Optional[str] = None) -> LegalQuery:
    """Produce a validated LegalQuery. Never raises."""
    has_context = bool(context_summary)

    if not is_complex(question, has_context):
        return _heuristic_query(question, context_summary)

    try:
        raw, provider = generate_structured(
            build_query_understanding_prompt(question, context_summary),
            system=QUERY_UNDERSTANDING_SYSTEM,
        )
    except Exception as exc:  # defensive: generate_structured shouldn't raise
        logger.warning("Query understanding call failed: %s", exc)
        raw, provider = None, "none"

    if raw is not None:
        validated = _validate(raw, question)
        if validated is not None:
            validated.provider = provider
            # Merge in heuristic jurisdiction if the LLM missed an explicit one
            if not validated.jurisdiction:
                country, province = _detect_jurisdiction(
                    f"{context_summary or ''} {question}")
                validated.jurisdiction = validated.jurisdiction or country
                validated.province_or_state = validated.province_or_state or province
            return validated
        logger.warning("Query understanding JSON failed validation; using heuristics")

    fallback = _heuristic_query(question, context_summary)
    fallback.provider = "fallback"
    return fallback
