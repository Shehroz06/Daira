"""Legal authority ranking for Daira.

Retrieved candidates are re-scored by combining:

    fused retrieval score  (semantic + keyword, rank-fused)
  + authority level        (constitution > statute > judgment > ... > web)
  + jurisdiction match     (country and province/state)
  + legal domain match
  + current status         (active vs repealed/superseded)
  + date relevance         (newer preferred, old docs NOT discarded)
  + provision specificity  (PPC only — specific offence sections preferred
                             over General Part sections, see below)

The output is a re-ranked list; nothing is hard-dropped here — repealed or
old documents are demoted, not deleted, because historical questions may
need them.
"""

from __future__ import annotations

import re
from typing import Optional

# Authority hierarchy (higher = more authoritative)
AUTHORITY_WEIGHTS = {
    "constitutional": 1.00,
    "primary": 0.90,       # statutes
    "judicial": 0.80,      # court judgments
    "regulatory": 0.70,    # regulations / rules
    "guidance": 0.55,      # government guidance
    "secondary": 0.40,     # academic commentary
    "practitioner": 0.30,  # law firm explanations
    "web": 0.15,           # general web articles
}
DEFAULT_AUTHORITY = 0.35   # unknown authority sits between secondary and practitioner

# Relative weights of each signal in the final score. Retrieval relevance
# dominates; metadata signals adjust the ordering among relevant chunks.
W_RETRIEVAL = 1.0
W_AUTHORITY = 0.25
W_JURISDICTION = 0.30
W_DOMAIN = 0.15
W_STATUS = 0.20
W_DATE = 0.10
W_SPECIFICITY = 0.35
W_QUALIFIER = 0.5

_CURRENT_YEAR = 2026


def _jurisdiction_score(doc: dict, jurisdiction: Optional[str],
                        province: Optional[str]) -> float:
    """1.0 exact match, 0.5 unknown/unspecified, 0.0 known mismatch."""
    if not jurisdiction:
        return 0.5
    dj = (doc.get("jurisdiction") or "").strip().lower()
    if not dj:
        return 0.5  # unknown metadata is not a disqualifier
    if dj != jurisdiction.strip().lower():
        return 0.0
    if province:
        dp = (doc.get("province_or_state") or "").strip().lower()
        if not dp:
            return 0.8  # country matches, province unknown
        return 1.0 if dp == province.strip().lower() else 0.3
    return 1.0


def _domain_score(doc: dict, legal_domain: Optional[str]) -> float:
    if not legal_domain:
        return 0.5
    dd = (doc.get("legal_domain") or "").strip().lower()
    if not dd:
        return 0.5
    return 1.0 if dd == legal_domain.strip().lower() else 0.2


def _status_score(doc: dict) -> float:
    status = (doc.get("status") or "active").strip().lower()
    if status == "active":
        return 1.0
    if status in ("amended", "partially_repealed"):
        return 0.7
    # repealed / superseded: demoted but never dropped (historical questions)
    return 0.3


def _date_score(doc: dict) -> float:
    year = doc.get("year")
    if not isinstance(year, int):
        return 0.5
    age = max(0, _CURRENT_YEAR - year)
    # Gentle decay: 0 years -> 1.0, 50 years -> ~0.5, 150 years -> ~0.25
    return 1.0 / (1.0 + age / 50.0)


# PPC's own chapter structure (public, verifiable, not corpus-specific):
# Chapters I-V + VA (Sections 1-120, 120A-120C) are General Explanations /
# Punishments / General Exceptions / Abetment / Criminal Conspiracy —
# principles applicable to every offence in the Code. Chapter VI onward
# (121+) defines specific offences (murder, theft, dacoity, etc.).
#
# Retrieval audit finding: a lay description of a situation ("I did a
# murder, what happens to me?") lexically resembles the General Part's
# generic liability language ("whoever... commits an offence") more than
# it resembles the specific offence's own technical text (qatl-i-amd,
# qisas), on both BM25 and vector similarity — so General Part sections
# routinely outrank the actual answer. Nothing else in this module's
# signals differentiates "states a general principle" from "defines a
# specific offence" (both share identical jurisdiction/domain/status/date),
# so this is a dedicated signal for that one distinction.
_PPC_SECTION_NUM_RE = re.compile(r"(\d{1,3})")
_PPC_GENERAL_PART_MAX = 120


def _provision_specificity_score(doc: dict) -> float:
    """1.0 for a PPC section defining a specific offence, 0.3 for a PPC
    General Part section, 0.5 (neutral) for anything outside the PPC where
    no equivalent verified chapter convention is being relied on."""
    if not str(doc.get("id", "")).startswith("ppc-section-"):
        return 0.5
    m = _PPC_SECTION_NUM_RE.search(doc.get("section") or "")
    if not m:
        return 0.5
    return 0.3 if int(m.group(1)) <= _PPC_GENERAL_PART_MAX else 1.0


# Second, narrower ranking problem the specificity signal above doesn't
# touch: PPC's murder-family sections (300, 302, 314, 324, 396, 398...) are
# ALL "specific offences" by the general/specific test, so they tie on
# _provision_specificity_score — yet they are not interchangeable. Retrieval
# audit finding: a query with no qualifying detail ("I did a murder") still
# retrieves variant sections (attempt, dacoity-with-murder) ahead of the
# base offence (302), because those variants' titles/bodies happen to share
# more surface vocabulary with a lay phrasing. A query naming a qualifier
# should prefer the matching variant; a query naming none should not be
# pushed toward one anyway.
_QUALIFIER_TERMS = (
    "attempt", "attempted", "dacoity", "conspiracy", "abet", "abetment",
    "negligence", "negligent", "provocation", "unborn",
)


_NEGATION_WORDS = ("not", "no", "never", "without", "isn't", "wasn't", "didn't")


def _positively_mentioned_terms(query: str) -> set[str]:
    """Qualifier terms the query actually asserts — excludes a term the
    query explicitly negates (e.g. "Not attempt, completed murder" negates
    "attempt", so it must not count as if the user asked about an attempt)."""
    words = re.findall(r"[a-z']+", query.lower())
    positive = set()
    for i, w in enumerate(words):
        if w not in _QUALIFIER_TERMS:
            continue
        preceding = words[max(0, i - 2):i]
        if any(p in _NEGATION_WORDS for p in preceding):
            continue
        positive.add(w)
    return positive


def _qualifier_match_score(doc: dict, query: Optional[str]) -> float:
    """1.0 if the doc's title carries no qualifying-variant term, or the
    query positively names a qualifier the title also carries. 0.35 if the
    title names a qualifier the query never asked for (offering a narrower
    variant than what was actually asked) — including one the query
    explicitly negated. Scoped to PPC only, like _provision_specificity_score
    — this term list was built for PPC's murder-family disambiguation and
    was never validated against other Acts' vocabulary (a first pass that
    applied it corpus-wide measurably hurt unrelated Constitution/Labour
    Code queries whose titles happened to contain one of these words)."""
    if not str(doc.get("id", "")).startswith("ppc-section-"):
        return 1.0
    title = (doc.get("title") or "").lower()
    title_terms = [t for t in _QUALIFIER_TERMS if t in title]
    if not title_terms:
        return 1.0
    if not query:
        return 0.6
    positive = _positively_mentioned_terms(query)
    return 1.0 if title_terms and set(title_terms) & positive else 0.35


def authority_rank(
    candidates: list[tuple[int, float]],
    docs: list[dict],
    jurisdiction: Optional[str] = None,
    province_or_state: Optional[str] = None,
    legal_domain: Optional[str] = None,
    query: Optional[str] = None,
) -> list[tuple[int, float]]:
    """Re-rank fused candidates by combined legal-authority score.

    candidates: [(doc_index, fused_retrieval_score)]
    Returns [(doc_index, final_score)] sorted descending.
    """
    if not candidates:
        return []

    # Normalize fused retrieval scores to [0, 1] so weights are comparable.
    max_fused = max(s for _, s in candidates) or 1.0

    ranked: list[tuple[int, float]] = []
    for idx, fused in candidates:
        doc = docs[idx]
        authority = AUTHORITY_WEIGHTS.get(
            (doc.get("authority_level") or "").strip().lower(), DEFAULT_AUTHORITY)
        score = (
            W_RETRIEVAL * (fused / max_fused)
            + W_AUTHORITY * authority
            + W_JURISDICTION * _jurisdiction_score(doc, jurisdiction, province_or_state)
            + W_DOMAIN * _domain_score(doc, legal_domain)
            + W_STATUS * _status_score(doc)
            + W_DATE * _date_score(doc)
            + W_SPECIFICITY * _provision_specificity_score(doc)
            + W_QUALIFIER * _qualifier_match_score(doc, query)
        )
        ranked.append((idx, score))

    ranked.sort(key=lambda x: -x[1])
    return ranked
