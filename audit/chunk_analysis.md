# Phase 4 — Chunking Audit

Status: **read-only audit, no code modified.** Statistics computed directly
from the live corpus; every flagged "bad chunk" below was read in full and
cross-checked against the raw source PDF, not inferred from size alone.

## 4.1 Chunking strategy (recap from Phase 1)

One chunk = one Section/Article's full body text, unconditionally. No
sub-chunking by clause, no merging of adjacent sections *by design*. This
phase checks whether that design is actually being honored by the parser,
or whether real sections are silently ending up merged despite it.

## 4.2 Size statistics

Token counts are an **estimate** (~4 characters/token, a standard English-
prose heuristic) — no tokenizer for the actual embedding/generation models
was available in this environment (`tiktoken` not installed). Treat the
token column as approximate; words and characters are exact.

| Source (n) | | min | p50 | avg | p90 | p95 | max |
|---|---|---|---|---|---|---|---|
| **Base** (324) | words | 8 | 95 | 158 | 358 | 511 | 1,210 |
| | chars | 49 | 571 | 923 | 2,067 | 2,982 | 7,261 |
| | tokens~ | 12 | 143 | 231 | 517 | 746 | 1,815 |
| **PPC** (509) | words | 2 | 69 | 122 | 247 | 365 | 3,247 |
| | chars | 13 | 400 | 689 | 1,422 | 2,050 | 17,925 |
| | tokens~ | 3 | 100 | 172 | 356 | 512 | 4,481 |
| **Punjab Labour Code** (435) | words | 11 | 116 | 181 | 409 | 575 | 2,117 |
| | chars | 71 | 719 | 1,090 | 2,415 | 3,410 | 13,635 |
| | tokens~ | 18 | 180 | 273 | 604 | 852 | 3,409 |
| **All combined** (1268) | words | 2 | 88 | 151 | 343 | 506 | 3,247 |
| | chars | 13 | 519 | 886 | 2,042 | 2,952 | 17,925 |
| | tokens~ | 3 | 130 | 222 | 510 | 738 | 4,481 |

The distribution is heavily right-skewed in every source: the median chunk
is a few hundred tokens, but the tail reaches into the thousands. That gap
between p95 and max is large enough (PPC: 512 vs 4,481 estimated tokens —
a 9× jump) to warrant inspecting the actual outliers rather than trusting
the summary stats alone.

## 4.3 The largest chunk: a real, evidenced parser defect

The single largest chunk in the entire corpus is `ppc-section-337`
("Shajjah") at 17,925 characters / ~4,481 estimated tokens — more than 4×
the corpus-wide p95.

**Investigated directly.** Its text runs from Section 337's own opening
clause all the way through a line reading `"337-Z. Disbursement of arsh or
daman: ..."` — i.e. this one chunk actually contains **Section 337 plus
its entire lettered sub-series, 337-A through 337-Z**. Confirmed against
the raw PDF: Pakistan Penal Code Sections 337-A through 337-Z are a real,
extensive, distinctly-numbered sub-series (added by Qisas & Diyat law
amendments) — each one defines a *different* category of "shajjah" (head/
face wound) or related hurt, **each with its own specific arsh/daman
(compensation) amount**. These are not sub-clauses of one idea; they are
individually numbered offences with individually different penalties,
exactly the kind of thing the audit brief calls "merging unrelated
offences."

**Root cause, confirmed against the parser regex**: `ingest_pdf.py`'s
`MARKER_RE` requires a section number optionally followed by *one letter
directly adjacent* (`\d{1,3}[A-Z]?`) before the period — matching "10A."
but not "337-A." (a hyphen between the number and the letter). Every
337-A–337-Z marker line fails to match at all, so the parser never sees
them as section boundaries; their entire content is silently absorbed as
continuation text of Section 337's body.

**This is not isolated to Section 337.** Scanning the raw PPC text for the
same `<number>-<letter>.` pattern found it in **26 distinct base
sections**, 146 total marker-line occurrences:

```
52, 55, 108, 120, 121, 123, 124, 138, 153, 165, 171, 216, 225, 263,
294, 295, 298, 337, 338, 354, 364, 365, 366, 402, 477, 489
```

(Occurrence count per base section — some appear twice per sub-letter
because of the dual-marker heading+body convention, so the true count of
distinct hidden lettered sections is roughly half of 146, i.e. on the
order of 70+ individually-numbered PPC provisions currently invisible as
separate retrievable units — each merged into whichever base section
number precedes it.)

Confirmed this pattern is **specific to PPC** — the same scan against the
Punjab Labour Code and the Constitution's raw text found zero occurrences
of the hyphenated-letter marker format in either.

**Concrete impact example**: Section 338's chunk (14 hidden lettered
occurrences — 338-A through roughly 338-H, the "itlaf-i-udw" wounding
provisions) exhibits the identical failure mode as 337. A query asking
specifically about one lettered variant (e.g. "punishment for itlaf-i-
udw") retrieves the same oversized merged chunk as a query about the base
section, with no way for either BM25 term-frequency or embedding
similarity to distinguish which specific lettered provision is actually
relevant — the distinguishing text is present, but diluted across a
chunk 4-9× the corpus's typical size.

## 4.4 Second finding: an isolated title/body split defect

Spot-checking chunks at various sizes (not just the extremes) for
coherence, `ppc-section-109`'s title reads:

```
"Punishment of abetment if the Act abetted committed In consequence and"
```

— grammatically incomplete, cut off mid-clause. Its body then opens with
`"where no express provision is made for its punishment: Whoever abets..."`
— which reads as the direct grammatical continuation of that same
truncated title. The section's actual content is not lost (the full
sentence is present, just split at the wrong point between the `title`
and `text` fields), so this is a **cosmetic title-quality defect**, not a
content-loss or merged-offence defect like §4.3. Root cause is plausibly
the same `split_title_body()` colon-preference heuristic misfiring on a
title containing an internal comma-then-colon structure — flagged for
Phase 12, not chased further here since it's a display-quality issue, not
a retrieval-correctness one.

No other instances of this specific pattern were found in the sections
spot-checked (109, 411, 34, plus the ones already examined in Phase 2 for
other reasons) — noted as a spot-check, not an exhaustive scan; a full
scan is listed as a Phase 12 follow-up if warranted.

## 4.5 "Too small" chunks

Already investigated in Phase 2 (§2.5): the three shortest non-trivial PPC
chunks (sections 15, 16, 18, each under 20 characters) are genuine —
verbatim repeal notices in the source document itself, not truncation.
Re-confirmed here from the chunking-size angle: excluding those, the
smallest substantive chunk found was `ppc-section-34` (188 characters,
shown in full in §4.3's sibling check) — a single, complete, one-sentence
section (common-intention liability). Genuinely short because the
underlying legal provision genuinely is that short; not a defect.

## 4.6 Boundary-crossing / cross-topic merging

Spot-checked several mid-to-large chunks across all three sources
(`ppc-section-109`, `ppc-section-411`, `ppc-section-34`, plus the base-
corpus and Labour Code outliers listed in §4.2) for the specific failure
mode of one chunk's text bleeding into an *unrelated* adjacent section
(different topic entirely, not the same numbered family as in §4.3).
**None found** in this spot-check. The one confirmed cross-boundary defect
in the corpus (§4.3) is specifically the hyphenated-letter-suffix pattern,
where the "unrelated" content is actually a same-family lettered
sub-provision, not a genuinely different, unrelated topic.

## 4.7 Summary

| Question from the audit brief | Finding |
|---|---|
| Chunks too large? | Yes — top outlier is 4× the corpus p95, root-caused (§4.3), not a rounding artifact |
| Chunks too small? | 3 instances, all verified genuine (repealed one-line notices), not defects |
| Crossing section boundaries? | Yes, systematically — 26 PPC base sections silently absorb their hyphenated lettered sub-sections (§4.3) |
| Merging unrelated offences? | Yes, concretely — Section 337 alone merges 26 individually-punished wound categories into one chunk |
| Breaking legal context? | Not observed in the spot-checked sample beyond §4.3/§4.4 — flagged as spot-check, not exhaustive |

**This is the most concrete, high-confidence lead so far in this audit.**
Unlike Phase 2's status-metadata finding (whose retrieval impact is still
unproven), this one is directly testable: if a user's query concerns any
of the ~70+ hidden lettered PPC provisions, the correct specific text
exists in the corpus but is diluted inside an oversized chunk under the
wrong section number, competing for retrieval rank against everything else
crammed into that same chunk. Phase 7 should specifically test queries
targeting sections in the affected list (§4.3) against this hypothesis
with real retrieval evidence before it's treated as confirmed.

---

**End of Phase 4.** No code was modified.

Stopping here per your instruction to review before proceeding to Phase 5
(Metadata Audit).
