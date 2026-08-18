# Phase 3 — Index Verification

Status: **read-only audit, no code modified.** All numbers below were
produced by loading the live index (`app.rag.LegalIndex.load()`) and
directly inspecting the resulting in-memory state and on-disk `.npy`/
`.json` files — not recalled from prior sessions.

## 3.1 What "the index" actually is here

Per Phase 1: there is no external vector database. "The index" is two
independent, in-process structures rebuilt/loaded at every app startup:

1. **Vector index**: NumPy matrices loaded from `.npy` files on disk
   (persistent, built offline by `scripts/build_index.py`).
2. **BM25 index**: an inverted index built fresh in memory from the live
   JSON documents on every startup (never persisted, so it cannot go
   stale the way the vector index can).

This means the vector index has a **real staleness risk** the BM25 index
doesn't: if a document file changes after its embeddings were last built,
the two can silently diverge. That's the highest-priority thing to check
in this phase, not a shape/count sanity check alone.

## 3.2 Embedding-matrix row alignment (the critical check)

For each of the three live sources, compared the **live JSON document
order** against the **doc order recorded in `index_meta.json` at the time
embeddings were last built**. If these two orderings ever diverge, row *i*
of the embedding matrix would silently belong to the wrong document — a
document could surface in vector search results under someone else's
semantic content, or never surface under its own.

| Source | Live doc count | Build-time doc count | Order match | Embedding rows | Dim |
|---|---|---|---|---|---|
| Base corpus | 324 | 324 | **exact match** | 324 | 768 |
| PPC | 509 | 509 | **exact match** | 509 | 768 |
| Punjab Labour Code | 435 | 435 | **exact match** | 435 | 768 |

All three are correctly aligned right now. Worth stating plainly: this
*would* be silently broken if someone hand-edited a corpus JSON file
without re-running `build_index.py` afterward — there is currently no
runtime check that would catch that (see §3.6).

## 3.3 Vector quality checks

For all 1268 vectors currently loaded:

- **L2 norm**: every vector's norm falls within [0.99, 1.01] of 1.0 (i.e.,
  correctly normalized at build time, as `build_index.py` is supposed to
  do). **0 vectors outside this range.** No zero-vectors present in the
  live index — this is notable because the *code* supports zero-filling a
  shard's rows when its embeddings are missing (graceful degradation to
  BM25-only for that shard), but right now all three loaded sources
  actually have real embeddings, so that fallback path isn't currently
  active for anything.
- **NaN/Inf**: 0 rows contain NaN, 0 rows contain Inf.
- **Exact-duplicate vectors**: 0 groups. No two documents — even very
  short, superficially similar ones (e.g. the repealed one-line PPC
  sections found in Phase 2) — ended up with byte-identical embeddings.
  This rules out a class of bug where a failed embedding call silently
  returns some fallback/zero-ish vector reused across multiple inputs.
- **Embedding model consistency**: all three `index_meta.json` files
  record `embed_model: "nomic-embed-text"`, `dim: 768`. No shard was
  embedded with a different model — if one had been, cosine similarity
  between it and the rest of the corpus would be comparing incompatible
  vector spaces without any error being raised (this is not currently
  happening, but it's worth knowing the system has no guard against it if
  a future shard used a different `OLLAMA_EMBED_MODEL`).

## 3.4 BM25 index sanity

Rebuilt fresh from the current 1268 live documents:

```
vocabulary size (unique terms):  7,247
total postings entries:         96,315
avg postings list length:         13.3 docs/term
avg document length:             167.3 tokens
documents with 0 tokens:          0
doc_len array length matches doc count: yes
```

No document produced an empty token list (which would make it permanently
unreachable via BM25 regardless of query). Postings-list length is
reasonably sparse (13 docs/term on average against a 1268-doc corpus),
consistent with legal vocabulary being fairly specific rather than generic.

## 3.5 Per-document field completeness (embedding + metadata, closing out Phase 2's partial coverage)

Phase 2 checked `text`/`title` emptiness. This phase checked **every**
schema field across all 1268 live documents:

| Field | Missing key | Null/empty | Has value |
|---|---|---|---|
| id, title, text, jurisdiction, legal_domain, document_type, authority_level, status, source, parent_document | 0 | 0 | 1268 (all) |
| province_or_state | 0 | 823 | 445 |
| year | 0 | 2 | 1266 |
| section | 0 | 3 | 1265 |
| subsection | 0 | 1268 | 0 |
| source_url | 0 | 1268 | 0 |
| effective_date | 0 | 1268 | 0 |
| effective_until | **324** | 944 | 0 |
| last_verified | 0 | 1268 | 0 |

Investigated every non-obvious gap individually rather than treating the
counts as noise:

- **`province_or_state` null for 823/1268**: expected — PPC (509) and the
  Constitution (304) are federal-level law with no province scope; only
  Punjab Labour Code and a handful of demo docs are province-specific.
  Not a defect.
- **`year` missing for exactly 2 docs**: `labour-guidance-unpaid-wages`
  and `commentary-security-deposits` — both `authority_level: guidance`/
  `secondary` sources (general advisory material, not a dated Act). Not a
  defect; a "year" doesn't cleanly apply to this document type.
- **`section` missing for exactly 3 docs**: the same 2 above, plus
  `rent-tribunal-judgment-2018` (a court judgment — judgments have
  paragraph/holding references, not "sections," and none was populated
  here). Legitimate content gap for this one doc (could carry a
  paragraph/citation reference instead of nothing), not a parsing failure.
- **`subsection` null for all 1268**: consistent with the Phase 1 finding
  that chunking never sub-splits a section — there is currently no
  document type in the corpus that populates this field at all. Confirms
  it's unused in practice, not selectively missing.
- **`source_url` empty for all 1268**: **a real completeness gap.** No
  ingested document — including the three PDF-sourced ones — carries a
  link back to an official online source. This doesn't affect retrieval,
  but it affects citation trustworthiness (Phase 10's territory) and is
  worth fixing when a source's official URL is known.
- **`effective_date`/`last_verified` empty for all 1268**: confirms the
  Phase 1 note that no document currently uses temporal-validity tracking
  — the schema fields exist, nothing populates them yet.
- **`effective_until` missing the *key itself* (not just null) on all 324
  base-corpus documents**: this field was added to the schema after the
  base corpus was created and was never backfilled onto existing entries
  — only new `SourceConfig`-built documents (PPC, Labour Code) carry the
  key at all (as `null`). Not currently causing errors (all reads go
  through `.get()`), but it's a schema-consistency gap: the same logical
  field is either absent or present-as-null depending on which pipeline
  created the document. Worth normalizing.

## 3.6 Gaps in the index-verification process itself (observations, not yet fixes)

- **No content-hash-based staleness detection.** `build_index.py`'s
  incremental check (confirmed in Phase 1) compares only row *count*
  between a shard's JSON and its `.npy`. If an existing chunk's text were
  edited without adding/removing any documents, the count would still
  match and the stale embedding would be silently kept. Not observed to
  have happened to the live index (§3.2 shows correct alignment right
  now) — flagged as a structural risk for future edits, not a current bug.
- **No runtime alignment check.** `app/rag.py::_load_embeddings()` checks
  matrix *shape* against the live document *count*, but not that the
  specific document *identities/order* match what was embedded. Two
  different 509-document versions of `ppc.json` (same count, different
  content or order) would pass the current check silently. This is the
  same risk as the bullet above, from the runtime side rather than the
  build-time side.

## 3.7 Summary

| Check | Result |
|---|---|
| Vector created for every live document | 1268 / 1268 |
| Embedding-matrix row alignment with live doc order | 3/3 sources exact match |
| Missing vectors | 0 |
| Duplicate vectors | 0 |
| Empty (all-zero) vectors | 0 (fallback path exists but inactive) |
| NaN/Inf vectors | 0 |
| Non-normalized vectors | 0 |
| Embedding model consistency across shards | consistent (nomic-embed-text, 768d, all 3) |
| BM25 index built for every document | 1268 / 1268, 0 empty-token docs |
| Metadata fields present where expected | all gaps individually investigated, all explained (§3.5) |
| **New completeness gap** | `source_url` empty for all 1268 docs; `effective_until` key missing (not just null) on the 324 base-corpus docs |

**No index corruption, misalignment, or missing/duplicate vectors found in
the current live index.** This phase's most important negative result:
whatever is causing the four reported symptoms, it is **not** vector/BM25
index corruption — the index faithfully represents the corpus as it
currently stands. That corpus itself (Phase 2's findings: 25 mismarked
`status` fields, 11 of 15 sources not yet ingested) remains the most
concrete lead so far, to be tested with actual query evidence in Phase 7.

---

**End of Phase 3.** No code was modified.

Stopping here per your instruction to review before proceeding to Phase 4
(Chunking Audit).
