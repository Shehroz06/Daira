# Daira

Daira is a local-first legal information and research assistant. It answers
legal questions using Retrieval-Augmented Generation: every substantive
answer is grounded in a local legal corpus, retrieved and ranked *before*
generation — it never answers from an LLM's general training knowledge
alone.

Daira is not a lawyer and does not create an attorney-client relationship.
See [Limitations](#limitations) before relying on anything it says.

## Contents

- [Project structure](#project-structure)
- [Quickstart](#quickstart)
- [Configuration](#configuration)
- [Testing](#testing)
- [Evaluation](#evaluation)
- [Adding legal documents](#adding-legal-documents)
- [Limitations](#limitations)
- [License](#license)

## Project structure

```text
Daira/
├── main.py                  FastAPI entrypoint (/, /chat, /health)
├── app/                     application package
│   ├── daira.py               orchestration, session context
│   ├── legal_query.py         query understanding (heuristic + LLM)
│   ├── rag.py                 hybrid retrieval (vector + BM25 + RRF)
│   ├── legal_ranker.py        authority/jurisdiction/date ranking
│   ├── llm.py                 Gemini/Ollama provider layer
│   └── prompts.py             system prompt + templates
├── scripts/
│   ├── prepare_documents.py   builds the hand-written demo corpus
│   ├── ingest_pdf.py          ingests a statute PDF, chunked by Article
│   ├── build_index.py         embeds the corpus -> data/embeddings.npy
│   └── evaluate.py            runs the golden retrieval eval
├── data/
│   ├── documents.json          base corpus (chunks + metadata)
│   ├── embeddings.npy          base corpus's embedding matrix
│   ├── index_meta.json         embedding model/dim/doc-id integrity check
│   ├── acts_registry.json      catalogue of every source Act (status, path)
│   ├── corpus/                 one shard per additional Act (<act>.json +
│   │                            <act>.embeddings.npy + <act>.index_meta.json)
│   └── sources/
│       ├── pdfs/                raw source PDFs
│       └── extracted/           per-source extraction output, for review
│                                 before merging into a shard
├── static/
│   ├── index.html              chat UI (vanilla JS, NDJSON streaming)
│   └── logo.svg                header mark — swap this file for your own
├── tests/                    hermetic pytest suite (no network)
├── requirements.txt
└── .env.example
```

## Quickstart

```bash
# 1. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create your local config and edit it (all fields are optional —
#    Daira runs on Ollama alone with no .env at all)
cp .env.example .env
nano .env

# 4. Pull the local models (Ollama must be running)
ollama pull llama3.2
ollama pull nomic-embed-text

# 5. Build the legal corpus and its embedding index
python scripts/prepare_documents.py
python scripts/build_index.py

# 6. Run the app
uvicorn main:app --reload
```

Then open `http://localhost:8000`.

To use Gemini as the preferred provider, set `GEMINI_API_KEY` in `.env`.
Daira works with Ollama alone if it's unset.

## Configuration

All configuration is via environment variables (see `.env.example`):

| Variable | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | *(empty)* | Enables Gemini when set |
| `GEMINI_MODEL` | `gemini-2.0-flash` | Gemini model name |
| `GEMINI_ENABLED` | `true` | Master on/off switch for Gemini |
| `GEMINI_MAX_RPM` | `15` | Client-side cap on Gemini calls/minute — Daira falls back to Ollama proactively once hit, instead of waiting on a 429 |
| `OLLAMA_URL` | `http://localhost:11434` | Local Ollama server |
| `OLLAMA_MODEL` | `llama3.2` | Ollama generation model |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Ollama embedding model |
| `LLM_PROVIDER` | `auto` | `auto` \| `gemini` \| `ollama` |
| `DAIRA_NUM_THREADS` | *(unset)* | Caps NumPy/BLAS threads for vector search |
| `DAIRA_DEBUG` | `false` | Adds pipeline-internals `debug` events to `/chat` |
| `DAIRA_MIN_COSINE` | `0.52` | Vector-search relevance floor |
| `DAIRA_MIN_BM25` | `4.5` | Keyword-search relevance floor |

## Testing

```bash
pytest tests/
```

The suite covers query-understanding heuristics and validation, authority
ranking, hybrid retrieval mechanics (keyword search, metadata filtering,
relevance threshold), safe JSON parsing, and prompt construction. It runs
fully offline — no Ollama or Gemini required.

## Evaluation

```bash
python scripts/evaluate.py
```

Runs `tests/golden_dataset.json` through the live retrieval pipeline and
reports Recall@1/3/5, Hit Rate, jurisdiction accuracy, relevance-threshold
accuracy, and retrieval latency. Requires a running Ollama instance (for
query embeddings) and a built index (`scripts/build_index.py`). This
measures retrieval *mechanics* against whatever corpus currently exists —
not legal completeness.

## Adding legal documents

Two ways to grow the corpus:

- **Hand-written chunks**: add entries to `scripts/prepare_documents.py`
  following the existing `doc(...)` calls, then re-run it.
- **PDF ingestion**: drop the statute PDF into `data/sources/pdfs/`, add a
  `SourceConfig` entry for it in `scripts/ingest_pdf.py` (metadata: Act
  name, jurisdiction, domain, year, numbering label), then:

  ```bash
  python scripts/ingest_pdf.py <source_key>
  # inspect data/sources/extracted/<source_key>_extracted.json, then:
  python scripts/ingest_pdf.py <source_key> --merge
  ```

  This targets documents structured as numbered "Article N" / "Section N"
  chunks — the parser handles both conventions found in the wild (a
  separate marginal heading vs. title-and-body on the same line) per
  section automatically. It requires the `pdftotext` binary (poppler-utils)
  on `PATH` — no Python PDF dependency needed. New sources merge into their
  own shard under `data/corpus/`, never into the base `data/documents.json`,
  so adding one Act can't affect anything already working. See
  `data/acts_registry.json` for what's ingested vs. pending.

Either way, **re-run `python scripts/build_index.py`** afterward (needs
Ollama running) — it's incremental, so it only embeds what's new or
changed, not the whole corpus every time.

## Limitations

- The corpus mixes a small hand-written demonstration set (Punjab tenancy,
  employment, consumer protection, contract law) with the Constitution of
  Pakistan ingested from an official PDF. Layout-based PDF extraction is
  inherently imperfect — spot-check anything you rely on against the
  official source rather than trusting it blindly.
- Conversation sessions are in-memory only (bounded to the most recent 200
  sessions) and are lost on restart.
- There is no authentication — the app is intended for local, single-user
  use.
- This is a demonstration project, not a vetted legal research tool. Do not
  use Daira's answers as a substitute for advice from a qualified lawyer.

## License

MIT — see [`LICENSE`](LICENSE). Chosen as a permissive default for a demo
project; change it if you have other plans for this code. Note the corpus
itself includes text extracted from official government publications (see
`data/sources/pdfs/`), which carries its own status independent of this
codebase's license.
