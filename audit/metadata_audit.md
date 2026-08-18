# Phase 5 — Metadata Audit

Status: **read-only audit, no code modified.** Builds on Phase 3 (which
verified completeness of the *existing* schema fields) — this phase checks
whether the schema even has the fields the audit brief specifically asks
about, and whether information visible in the raw source is being
captured or silently discarded.

## 5.1 Which requested fields actually exist in the schema

The audit brief asks to verify: section number, chapter, title, offence,
keywords, act name, year, citation, source file. Checked the literal union
of every key present across all 1268 live documents:

| Field requested | Exists in schema? | Notes |
|---|---|---|
| section number | ✅ `section` | e.g. `"Section 302"` |
| title | ✅ `title` | |
| act name | ✅ `parent_document` | e.g. `"Pakistan Penal Code, 1860"` — same concept, different field name |
| year | ✅ `year` | |
| **chapter** | ❌ absent | never captured, see §5.2 — recoverable, not currently lost |
| **offence** | ❌ absent | no structured offence-name field distinct from `title` |
| **keywords** | ❌ absent | no tag/keyword field of any kind |
| **citation** | ❌ absent as a field | reconstructable from other fields, see §5.4 |
| **source file** | ❌ absent | which PDF/page a chunk came from is not tracked per-document |

Four of the nine requested fields don't exist in the schema at all — not
null on some documents, structurally absent from every document. This is
consistent with Phase 3's finding that the schema was designed once (for
the hand-written demo corpus + Constitution) and extended incrementally
(`effective_until` added later, backfilled inconsistently) rather than
being purpose-built for a large multi-domain criminal-law corpus.

## 5.2 "Chapter" — present in the source, discarded during ingestion

Checked whether chapter information is actually available to capture, not
just theoretically useful. The raw PPC PDF contains genuine chapter
headers throughout (`"CHAPTER I"`, `"CHAPTER V-A"`, `"CHAPTER XVI"`, etc.
— **51 occurrences** in the raw `pdftotext` output, TOC entries and real
body headers combined). This is real, existing structure in the source
document — Chapter XVI, for instance, is literally "Of Offences Affecting
the Human Body" and contains all the murder/hurt/assault provisions. A
`chapter` field would be directly useful for exactly the kind of
domain-narrowing the reported symptoms need (Example 3/4: distinguishing
completed murder from attempt-to-murder from dacoity-with-murder — all
in different chapters). **This is a recoverable gap, not a lost one** —
the information exists in the already-downloaded PDFs and could be
captured by extending the parser, not by re-sourcing anything.

## 5.3 Chapter/Part headings leaking into chunk body text (new finding)

While checking §5.2, searched every chunk's body text for a stray
`CHAPTER`/`PART` heading that shouldn't be there (the parser has no
special handling for these lines — they're neither recognized as markers
nor filtered as noise, so whenever one falls between two section markers
it gets silently absorbed into whichever chunk is being collected at that
point).

| Source | Chunks with a leaked chapter/part heading in their body text |
|---|---|
| PPC | 23 / 509 |
| Base corpus (incl. Constitution) | 27 / 324 |
| Punjab Labour Code | 39 / 435 |
| **Total** | **89 / 1268 (7.0%)** |

Example (`ppc-section-120`): the chunk's text contains the fragment
`"...or with both. CHAPTER V-A CRIMINAL CONSPIRACY 120-A."` — the chapter
title text is embedded mid-sentence inside what should be Section 120's
own content. (This particular example also confirms Phase 4's finding
independently from a different angle — `120-A` appears here too, meaning
Section 120 is one of the 26 sections from Phase 4's hyphenated-letter
list, and the same collection window that swallowed 120-A also swallowed
the interstitial chapter heading ahead of it.)

**Important distinction from Phase 4**: this leak is *not* exclusively
tied to the hyphenated-letter defect — it happens in the Constitution and
Labour Code too, neither of which has that specific issue (confirmed in
Phase 4). This is a separate, more general gap: chapter/part headings are
simply unhandled everywhere, and only sometimes visible as contamination
depending on where they happen to fall relative to markers.

**Severity**: low-to-moderate. This is text noise inside an otherwise
correct chunk (not lost content, not wrong content), but it does mean ~7%
of chunks have a short irrelevant string mixed into their embedded/
indexed text, which could very marginally dilute BM25/embedding relevance
for those specific chunks. Not tested against real queries here — that's
Phase 7's job if it turns out to matter.

## 5.4 "Citation" — reconstructable today, but not stored or linkable

No document stores a formatted citation string. Tested whether one can be
built from existing fields:

```
parent_document + ", " + section + " (" + year + ")"
  -> "Pakistan Penal Code, 1860, Section 101 (1860)"
```

Works, but is slightly redundant (the year appears twice — once inside
`parent_document`'s own name, once appended). More importantly, per Phase
3's finding, `source_url` is empty on all 1268 documents, so even a
well-formatted citation can't be made **verifiable** — there's no link
back to an authoritative online copy of the Act for a user (or a lawyer)
to check the citation against.

## 5.5 "Offence" and "keywords" — genuinely absent, disproportionately relevant here

509 of 1268 documents (40% of the entire corpus) are PPC criminal-law
provisions, and the reported symptoms are entirely in this domain. Neither
a structured `offence` name (distinct from the free-text `title`, which
often contains extra qualifying language — e.g. Section 109's title is a
grammatically broken fragment per Phase 4 §4.4) nor any `keywords`/tag
field exists to let retrieval or filtering key off of a normalized offence
name like `"murder"`, `"theft"`, `"attempt"`, `"dacoity"` independent of
whatever words happen to appear in the title/body text. This is an
architectural gap worth carrying into Phase 12 — noted here as a schema
fact, not yet as a proven cause of the reported symptoms (that requires
Phase 7's query-level evidence).

## 5.6 Cross-reference to Phase 3

Phase 3 already exhaustively checked completeness of the fields that *do*
exist in the schema (`province_or_state`, `year`, `section`, `subsection`,
`source_url`, `effective_date`, `effective_until`, `last_verified`) and
individually explained every gap found there. Not repeated here — see
`index_audit.md` §3.5 for that table.

## 5.7 Summary

| Check | Result |
|---|---|
| Fields requested by the audit brief that exist in the schema | 4 / 9 (section, title, act name↔parent_document, year) |
| Fields requested but structurally absent | 5 / 9 (chapter, offence, keywords, citation, source file) |
| Is the missing "chapter" info recoverable from already-downloaded sources? | Yes — confirmed present in the raw PDF, just not captured |
| Chunks with leaked chapter/part heading noise in their body text | 89 / 1268 (7.0%), all three sources affected |
| Can a citation be reconstructed from existing fields? | Yes, with minor redundancy; not verifiable (no `source_url`) |
| Is `offence`/`keywords` absence specific to a small part of the corpus? | No — affects 40% of the corpus (all of PPC), the exact domain of the reported symptoms |

---

**End of Phase 5.** No code was modified. Two new findings this phase:
recoverable-but-uncaptured chapter metadata (§5.2), and chapter-heading
noise leaking into ~7% of chunks (§5.3) — both facts for Phase 12 to
weigh, neither yet tested against real retrieval outcomes.

Stopping here per your instruction to review before proceeding to Phase 6
(Embedding Quality Audit).
