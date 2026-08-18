# Phase 1 — Architecture Overview

Status: **read-only audit, no code modified.** Verified against the live codebase
(file reads, line counts, and direct data inspection — not recalled from memory)
on the date this document was written.

## 1. System summary

Diara is a local-first legal RAG assistant for Pakistan-focused legal questions.
FastAPI backend, hybrid BM25+vector retrieval over an in-memory NumPy index (no
external vector database), Gemini-preferred/Ollama-fallback generation, vanilla-JS
frontend with NDJSON streaming. No authentication, single-process, in-memory
session state.

## 2. Request flow

```
Browser (static/index.html)
    │  POST /chat {message, session_id}
    ▼
main.py                    FastAPI routes: /, /chat, /health
    ▼
app/diara.py :: chat()     orchestrates one turn
    │
    ├─ app/legal_query.py :: understand()
    │      heuristic (regex/keyword) OR one LLM call, decided by is_complex()
    │
    ├─ jurisdiction gate    (currently defaults to Pakistan/Punjab — see §7)
    │
    ├─ app/rag.py :: index.retrieve()
    │      │
    │      ├─ metadata filter (jurisdiction/province, soft)
    │      ├─ vector_search()   cosine similarity, brute-force NumPy matmul
    │      ├─ keyword_search()  BM25 over a hand-rolled inverted index
    │      ├─ Reciprocal Rank Fusion (rank-based, not raw-score-based)
    │      ├─ relevance threshold (MIN_COSINE / MIN_BM25) — survivors only
    │      └─ app/legal_ranker.py :: authority_rank()
    │             re-scores survivors: retrieval + authority + jurisdiction
    │             + domain + status + date, weighted sum
    │
    └─ app/prompts.py + app/llm.py :: stream_generate()
           Gemini (rate-limited, proactive fallback) → Ollama
           NDJSON chunks streamed back to the browser
```

There is **no reranking stage** after `authority_rank()` — whatever survives the
threshold and authority-weighted sort is hard-truncated to `FINAL_K=5` and handed
to the LLM. This is a fact to carry into Phase 7/12, not a conclusion about it yet.

## 3. Folder structure

```
main.py                 FastAPI entrypoint (98 lines)
app/
  diara.py               turn orchestration, session state (218 lines)
  legal_query.py          query understanding (257 lines)
  rag.py                  hybrid retrieval engine (411 lines)
  legal_ranker.py         authority/jurisdiction/date re-scoring (126 lines)
  llm.py                  Gemini/Ollama provider layer (323 lines)
  prompts.py              system prompt + templates (140 lines)
scripts/
  prepare_documents.py    hand-written demo corpus generator (422 lines)
  ingest_pdf.py            PDF → chunked JSON ingestion engine (459 lines)
  build_index.py           embedding builder, incremental (144 lines)
  evaluate.py              golden-dataset retrieval eval (141 lines)
data/
  documents.json           base corpus (324 docs — demo corpus + Constitution)
  embeddings.npy            base corpus's embedding matrix
  index_meta.json           embedding model/dim/doc-id record for the base
  acts_registry.json        catalogue of all known source Acts + status
  corpus/                   one shard per additional Act:
                             <act>.json + <act>.embeddings.npy + <act>.index_meta.json
  sources/
    pdfs/                   raw source PDFs (15 files)
    extracted/               per-source extraction output, pre-merge review copy
static/
  index.html                chat UI (vanilla JS, NDJSON stream reader)
  logo.svg
tests/                     67 hermetic pytest cases (no network)
  golden_dataset.json        14 retrieval eval cases (see §9 — this predates
                              the PPC/Labour Code ingestion and needs expansion)
```

## 4. Data model (per-chunk schema)

Every document/chunk is a flat JSON object:

```
id, title, text,
jurisdiction, province_or_state, legal_domain,
document_type, authority_level, year, status,
source, source_url,
section, subsection, parent_document,
effective_date, effective_until, last_verified
```

`effective_until` exists in the schema (added for notification-type documents
like minimum-wage rates that expire) but **no document in the corpus currently
sets it** — confirmed by direct inspection in Phase 2/5.

## 5. Corpus inventory (verified counts, not estimates)

| Source | Doc count | Domain | Authority | Status |
|---|---|---|---|---|
| `data/documents.json` (base: hand-written demo + Constitution) | 324 | mixed (see below) | mixed | merged |
| `data/corpus/ppc.json` (Pakistan Penal Code, 1860) | 509 | `criminal_law` | `primary` | merged |
| `data/corpus/punjab_labour_code_2026.json` | 435 | `employment` | `primary` | merged |
| **Total loaded at runtime** | **1268** | | | |

Domain distribution across all 1268 docs (counted directly, not sampled):

```
employment          440   (mostly Punjab Labour Code + a handful of demo docs)
criminal_law         509   (entirely PPC)
constitutional_law   304   (Constitution articles)
landlord_tenant         8
contract_law            4
consumer_law             3
```

Authority-level distribution:

```
primary          961
constitutional    304
judicial            1
guidance            1
secondary           1
```

11 more source PDFs are catalogued in `data/acts_registry.json` as
`not_started` (no `SourceConfig` yet) or `pending` (config ready, not yet
extracted) — CrPC, Companies Act, Qanun-e-Shahadat, the Zina/Qazf/Hadd
Ordinances, Arms Ordinance, Motor Vehicles Ordinance, Illicit Arms Act,
Hotel Restriction Security Act, Anti-Terrorism Act. **None of these are in
the live index yet.** This matters directly for symptom Example 2 ("what
are my rights?") and any query expecting CrPC-covered content (bail
procedure, arrest rights) — that source simply isn't ingested yet.

## 6. Ingestion pipeline (`scripts/ingest_pdf.py`)

1. `pdftotext -layout` (poppler-utils binary, no Python PDF dependency).
2. `clean_lines()` strips table-of-contents lines (dot-leader detection),
   footnote/amendment-annotation lines, bare page-number lines.
3. `parse_sections()` finds "markers" (lines starting with `N.`, optionally
   amendment-bracketed) and pairs them into sections **per-marker**, not
   per-document:
   - **dual-marker**: a heading-only marker immediately followed by a
     second same-numbered marker that starts the real body (Constitution,
     most of PPC).
   - **single-marker**: title and body share one line, split at the first
     colon (preferred) or period+optional-dash (CrPC, Companies Act,
     Punjab Labour Code).
4. Optional per-source `glossary: dict[str, str]` — appends a common
   English synonym to a section's title when it contains a term a general
   embedding model doesn't associate with the English word (only PPC has
   one currently: qatl-i-amd→murder, qisas→retaliatory punishment, etc.
   — 16 entries, all in `SOURCE_CONFIGS["ppc"]`). **This only touches the
   title string, never the body text.**
5. Extraction output written to `data/sources/extracted/<key>_extracted.json`
   for human review; a separate `--merge` step writes it into
   `data/corpus/<shard>.json` (new sources) or upserts into
   `data/documents.json` (Constitution only, legacy path).
6. **One chunk = one Section/Article's full body text, unconditionally.**
   No sub-chunking by clause, no merging of adjacent short sections. Chunk
   size is therefore whatever the source section's natural length is —
   see Phase 4 for actual measured distribution.

`scripts/build_index.py` embeds each corpus file's chunks via
`ollama_embed()` (nomic-embed-text, 768-dim, batch size 16), L2-normalizes,
and writes `<file>.embeddings.npy` + `<file>.index_meta.json`. **Incremental
by row-count only**: a shard is skipped if its embeddings file already has
the same number of rows as its JSON. This does **not** detect changed text
in an existing chunk (a content hash would; row count doesn't) — noted as a
real gap, not yet a proven bug, for Phase 12.

## 7. Retrieval pipeline (`app/rag.py`)

- **Vector search**: `self.embeddings @ query_vector` — a single dense
  matrix multiply over the *entire* loaded corpus (1268 × 768 floats),
  brute-force, no ANN index, no external vector DB. At this scale
  (~4MB matrix) this is fast in absolute terms; it does not use any
  approximate-nearest-neighbor structure.
- **Keyword search**: BM25 (k1=1.5, b=0.75) over a hand-rolled inverted
  index (`term -> [(doc_idx, term_freq)]`), built at load time from
  `title + section + text`, lowercased, tokenized by `[a-z0-9]+` (no
  stemming, no lemmatization, no stopword list — see Phase 8).
- **Fusion**: Reciprocal Rank Fusion (`1/(60+rank+1)`, summed across both
  lists), rank-based not raw-score-based.
- **Relevance threshold**: a candidate survives if its vector cosine ≥
  `MIN_COSINE` (default 0.52, `.env` currently sets 0.45) **or** its BM25
  score ≥ `MIN_BM25` (default 4.5, `.env` currently sets 1.0). Note the
  code-default and the checked-in `.env` disagree — `.env`'s values are
  what's actually active at runtime.
- **Authority re-ranking**: `legal_ranker.authority_rank()` computes a
  weighted sum — `1.0×normalized_fusion + 0.25×authority_level +
  0.30×jurisdiction_match + 0.15×domain_match + 0.20×status + 0.10×date` —
  over only the threshold survivors, then truncates to `FINAL_K=5`.
- **Metadata filter**: jurisdiction/province filtering is *soft* — a
  document with unknown jurisdiction is never excluded; only a *known,
  different* jurisdiction excludes it. Applied before search, not after.

## 8. Query understanding (`app/legal_query.py`)

Two paths, chosen by `is_complex()`:
- **Heuristic** (no LLM call): keyword-list domain/jurisdiction detection.
  Fixed today (this session) to prefer the *current* question's own domain
  signal over blended conversation context, specifically to stop an
  unrelated prior turn's vocabulary from hijacking a topic-switching
  follow-up question.
- **LLM path**: one structured Gemini/Ollama call, triggered when the
  question contains a pronoun reference alongside prior context, or hits
  length/hint-word thresholds (see `_COMPLEX_HINTS`). Output strictly
  validated (`_validate()`) against an allowed-field/allowed-enum set.

No stemming, lemmatization, spelling correction, or query expansion exists
anywhere in this path or in `rag.py`'s tokenizer. The only vocabulary
bridging mechanism in the entire system is the ingestion-time PPC glossary
described in §6 — it operates on stored document titles, not on the user's
query at all.

## 9. Generation & citations (`app/llm.py`, `app/prompts.py`)

- Provider-agnostic `generate`/`stream_generate`/`generate_structured`.
  Gemini preferred, proactively rate-limited client-side
  (`GEMINI_MAX_RPM`, default 15/60s rolling window) to fail over to Ollama
  *before* hitting Google's own 429, not after.
- `LEGAL_SYSTEM_PROMPT` instructs: ground claims in retrieved sources only,
  never invent statutes/sections, distinguish source-text from inference,
  lead with concrete numbers when present, end with a `Sources:` line.
- **Citations are entirely LLM-self-reported** — there is no programmatic
  verification that the `Sources:` line the model outputs actually matches
  the `id`/`section` fields of the documents that were retrieved and put in
  its context window. The frontend used to render a second, independently
  built source list from the retrieval `meta` event; that was removed
  (this session) specifically because it sometimes disagreed with the
  model's own citation line. Now there is exactly one citation surface —
  the model's own text — and zero automated cross-check against it. This
  is a concrete, testable gap for Phase 10.

## 10. Existing evaluation tooling

- `tests/` — 67 hermetic pytest unit tests (BM25 mechanics, ranker scoring,
  domain/jurisdiction heuristics, sharded loading, safe JSON parsing,
  prompt formatting). All currently passing. **None of these test
  end-to-end retrieval accuracy against real queries** — they test
  individual functions in isolation with small synthetic fixtures.
- `scripts/evaluate.py` + `tests/golden_dataset.json` — the only existing
  end-to-end retrieval benchmark. **14 cases, written before PPC and the
  Punjab Labour Code existed in the corpus.** Zero cases currently test
  criminal-law retrieval (theft, murder, bail, etc.) — the exact domain
  where the reported symptoms live. This benchmark cannot currently detect
  or measure any of the four symptom examples in this audit's brief.

## 11. What does not exist (explicit, since absence matters for later phases)

- No cross-encoder or LLM-based reranking stage.
- No real vector database (FAISS/Chroma/pgvector/etc.) — brute-force NumPy.
- No sub-section chunking — one chunk is always one whole Section/Article,
  regardless of length.
- No query-side stemming, lemmatization, or synonym expansion.
- No stopword removal in BM25 tokenization.
- No programmatic citation verification.
- No content-hash-based incremental embedding (row-count only).
- No retrieval benchmark covering criminal law, the domain the reported
  symptoms are all in.

## 12. Configuration surface (`.env`)

```
GEMINI_MODEL, GEMINI_ENABLED, GEMINI_MAX_RPM
OLLAMA_URL, OLLAMA_MODEL, OLLAMA_EMBED_MODEL
LLM_PROVIDER (auto|gemini|ollama)
DIARA_NUM_THREADS, DIARA_DEBUG
DIARA_MIN_COSINE (checked-in: 0.45, code default: 0.52)
DIARA_MIN_BM25   (checked-in: 1.0,  code default: 4.5)
DIARA_DEFAULT_JURISDICTION (default "Pakistan"), DIARA_DEFAULT_PROVINCE (default "Punjab")
```

The threshold discrepancy between `.env` and the code defaults is flagged
here as a fact; whether it's a contributing cause to the reported symptoms
is a Phase 7 question, not answered here.

---

**End of Phase 1.** No code was modified. Next: Phase 2 (Dataset Verification)
will check every source document actually exists, is uncorrupted, and was
extracted without silent parser failures — producing `dataset_audit.md`.

Stopping here per your instruction to review before proceeding.
