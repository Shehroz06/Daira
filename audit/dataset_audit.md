# Phase 2 — Dataset Verification

Status: **read-only audit, no code modified.** All numbers below were produced
by direct inspection of the live files (`data/*.json`, `data/corpus/*.json`,
`data/sources/pdfs/*.pdf`) run just now — not recalled from prior sessions.

## 2.1 Source PDF integrity

All 15 PDFs cataloged in `data/acts_registry.json` were checked for
existence, page count, and whether `pdftotext` can extract a real text layer
from them.

| File | Size | Pages | Extracted chars |
|---|---|---|---|
| CrPC | 570 KB | 126 | 428,301 |
| PPC | 435 KB | 175 | 426,312 |
| Qanun-e-Shahadat | 170 KB | 69 | 153,706 |
| Qazf Ordinance | 22 KB | 6 | 13,734 |
| Zina Ordinance | 24 KB | 7 | 16,786 |
| Offences Against Property Ord. | 28 KB | 9 | 19,778 |
| Arms Ordinance | 44 KB | 14 | 29,061 |
| Motor Vehicles Ordinance | 319 KB | 127 | 305,445 |
| Hadd Order | 31 KB | 10 | 21,820 |
| Illicit Arms Act | 20 KB | 4 | 9,540 |
| Hotel Restriction Security Act | 131 KB | 3 | 7,590 |
| Anti-Terrorism Act | 240 KB | 46 | 144,747 |
| Punjab Labour Code | 2.77 MB | 186 | 669,334 |
| Constitution | 1.29 MB | 222 | 537,159 |
| Companies Act | 4.13 MB | 418 | 1,175,861 |

**Result: 15/15 exist, 0 corrupted, 0 missing.** Every file yields a
substantial native text layer via `pdftotext` — these are all text-based
PDFs, not scanned images. **No OCR is involved anywhere in this pipeline**;
Phase 6's "OCR failures" checklist item doesn't apply to this corpus.

## 2.2 Ingested corpus — structural integrity

Three sources are currently merged into the live index: the base corpus
(`data/documents.json`), PPC (`data/corpus/ppc.json`), and the Punjab
Labour Code (`data/corpus/punjab_labour_code_2026.json`).

| Source | Docs | Duplicate IDs | Empty text | Empty title | Text length (min/median/max) |
|---|---|---|---|---|---|
| Base (demo corpus + Constitution) | 324 | none | none | none | 49 / 571 / 7,261 |
| PPC | 509 | none | none | none | 13 / 400 / 17,925 |
| Punjab Labour Code | 435 | none | none | none | 71 / 719 / 13,635 |

**Cross-file ID collisions**: checked all three pairwise intersections
(base∩ppc, base∩plc, ppc∩plc) — all empty. No document exists under the
same id in two files.

**Extracted-copy vs. merged-shard consistency**: `data/sources/extracted/`
holds the pre-merge review copy for each source. Verified byte-for-count
match against the live shard for all three: PPC 509=509, Labour Code
435=435, Constitution 304=304. No silent divergence between what was
reviewed and what's actually loaded.

**Registry claims vs. reality**: `data/acts_registry.json`'s
`document_count` field for each merged source matches the actual file
count exactly (304/509/435). The registry is accurate, not aspirational.

## 2.3 Missing sections (numbering-gap check)

For each source, I derived the expected numeric range from the source's own
section numbering and checked for gaps:

- **PPC**: range 1–511 expected. **Missing: 311, 315** (2 of 511, 99.6%
  coverage). Root cause confirmed by direct inspection of the raw PDF text
  — both use a hyphen instead of a period after the section number
  (`"311-Ta'zir after waiver..."`, `"315-Qatl shibh-i-amd"`), which the
  current marker regex doesn't match (it requires a period). This was
  already known and documented in the registry; re-confirmed here
  independently rather than taken on faith.
- **Punjab Labour Code**: range 1–435 expected. **Missing: none.** 100%
  coverage.
- **Constitution**: range 1–280 (plain-numbered) expected. **Missing:
  none.** 100% coverage of plain numbers, plus 24 correctly-extracted
  lettered variants (2A, 10A, 25A, 63A, etc.) for 304 total.

## 2.4 Duplicate sections

**None found** — checked within each file (Counter on id field) and across
all three files pairwise. Every id is unique.

## 2.5 Malformed / suspiciously short sections

Flagged any document with text under 20 characters for manual inspection:

- **PPC**: 3 flagged — `ppc-section-15` (13 chars), `ppc-section-16` (17
  chars), `ppc-section-18` (17 chars). **Investigated against the raw PDF
  directly — these are genuine, not extraction failures.** Sections 15, 16,
  and 18 of the Pakistan Penal Code were repealed by the Adaptation Order of
  1937; the official gazette text itself contains nothing but a brief
  repeal notice at those numbers (e.g. `"16. Definition of "Government of
  India": [Rep. by AO. 1937]."` — confirmed present verbatim in
  `pdftotext` output at PDF line 1476). The extraction is correct; the
  source document is just that short there. One cosmetic issue inherited
  from the source PDF itself (not introduced by our parser): missing
  spaces in a few of these notices (`"byA.0."`, `"byAO."`) — a kerning
  artifact in the PDF's own text layer, confined to already-repealed
  sections, no legal-accuracy impact.
- **Punjab Labour Code, base corpus**: none flagged.

## 2.6 New finding: repealed sections mismarked `status: "active"`

Not on the original checklist, but surfaced while investigating §2.5 —
searched all 1268 documents' text for repeal/omission language
(`"Repealed"`, `"Omitted"`) and cross-checked against each document's own
`status` metadata field.

**19 PPC sections and 6 Constitution articles contain their own textual
confirmation of being repealed or omitted, but are tagged `status:
"active"`:**

PPC: 13, 16, 18, 56, 58, 59, 61, 62, 226, 366, 372, 373, **375**, 376, 490,
492, 493, 497, 498 (19 total — includes the section that was previously
identified this session as "Rape, repealed by the Zina Ordinance", plus
7 other Zina-Ordinance-superseded sections in the same numeric
neighborhood: 366, 372, 373, 376, 493, 497, 498).

Constitution: Articles 71, 96, 134, 152A, 212A, 212B (6 total — verified
each by reading its own text; excluded Articles 264 and 267B from this
count because their text merely *discusses* repeal as a general legal
concept without being repealed themselves — a naive keyword match would
have false-positived on those two).

**Why this matters for retrieval, stated as fact, not yet as root-cause
diagnosis (that's Phase 7):** `app/legal_ranker.py::_status_score()` only
demotes a document (0.3× multiplier) when its `status` field reads
`"repealed"` or similar. All 25 of these documents currently score the
full 1.0, identical to genuinely active law, in that dimension of ranking.
Whether this is *sufficient* to explain any of the four reported symptoms
requires the ranked-candidate evidence gathered in Phase 7 — noted here as
a verified, quantified, corpus-level fact for that phase to use.

**Control check**: the one hand-written demo document that's intentionally
repealed (`punjab-rent-ordinance-1959-section-13`, the Constitution's
sibling example cited in `.claude/CLAUDE.md`) is correctly tagged `status:
"repealed"`. This is not a systemic modeling gap — it's specific to the
two PDF-ingestion pipelines (`SourceConfig` hardcodes `status: "active"`
as a per-source default and nothing currently detects repeal language
in the body text to override it per-section).

## 2.7 Summary

| Check | Result |
|---|---|
| Missing files | 0 / 15 |
| Corrupted files | 0 / 15 |
| OCR failures | N/A — no OCR in this pipeline |
| Duplicate sections | 0 |
| Skipped/missing sections | 2 (PPC 311, 315 — known cause) |
| Malformed sections | 0 (3 short PPC sections investigated and confirmed genuine) |
| Parsing failures | 0 confirmed |
| **New: mismarked status metadata** | **25 documents (19 PPC + 6 Constitution)** |

---

**End of Phase 2.** No code was modified. The one actionable new finding
(§2.6) is documented as fact for Phase 5 (Metadata Audit, where it belongs
structurally) and Phase 7 (Retrieval Evaluation, where its actual impact on
ranking gets tested with evidence) to build on — not acted on yet.

Stopping here per your instruction to review before proceeding to Phase 3
(Index Verification).
