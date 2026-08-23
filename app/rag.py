"""Legal RAG retrieval for Daira.

Hybrid local retrieval:

    User Query
        ├── Vector search  (Ollama query embedding · normalized doc matrix)
        └── Keyword search (BM25 over an inverted index)
                │
                ▼
        Reciprocal Rank Fusion
                │
                ▼
        Authority / jurisdiction ranking (legal_ranker)
                │
                ▼
        Relevance threshold → final sources (possibly empty)

Documents and embeddings are loaded once at startup. Only the query is
embedded at runtime. All failure modes (missing/corrupted files, embedding
failure) degrade gracefully — retrieval never crashes the app.

Corpus layout — designed so adding a new Act never risks the rest:

    data/documents.json              base corpus (hand-written + Constitution)
    data/embeddings.npy               its embedding matrix
    data/corpus/<act>.json            one shard per additional Act
    data/corpus/<act>.embeddings.npy  that shard's own embedding matrix

Every shard is loaded independently. A duplicate id across files is a loud
load-time error, not a silent overwrite. A shard with missing/bad embeddings
degrades to BM25-only for *that shard's documents* — it does not disable
vector search for the base corpus or any other shard.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

import numpy as np

from .legal_ranker import authority_rank
from .llm import ollama_embed

logger = logging.getLogger("daira.rag")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Retrieval tuning
# VECTOR_K/KEYWORD_K widened from 12: audit evidence (retrieval evaluation)
# showed the correct specific-offence section for lay-phrased criminal
# queries sometimes ranks outside the old cutoff on one channel even
# though present in the corpus — RRF fusion only needs a doc in ONE
# channel's top-K to enter the candidate pool authority_rank() sees, so a
# doc that's strong on BM25 but weak on embedding similarity (or vice
# versa) still needs to actually clear its weak channel's cutoff to be
# rescued by its strong one. Brute-force NumPy cosine and the BM25
# inverted index are both cheap to widen (cost scales with corpus size,
# not K) — vector search in particular is one full-corpus dot product
# regardless of how many results are kept, so a wide K is nearly free.
VECTOR_K = 50          # candidates from vector search
KEYWORD_K = 25         # candidates from keyword search
RRF_K = 60             # standard RRF constant
FINAL_K = 5            # sources handed to the LLM
# Minimum cosine similarity for a chunk to count as "relevant at all".
# Below this, vector hits are noise (e.g. cooking questions vs legal corpus).
MIN_COSINE = float(os.getenv("DAIRA_MIN_COSINE", "0.52"))
# A candidate that only appears via keyword match must still clear this.
MIN_BM25 = float(os.getenv("DAIRA_MIN_BM25", "4.5"))

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Legal abbreviations that never appear spelled out in a query but whose
# corpus documents only use the full name (e.g. PPC section titles say
# "Pakistan Penal Code", never "PPC") — without this, a query token like
# "ppc" has zero postings and contributes nothing to BM25, so a bare
# "Section 302 PPC" query can't distinguish the Pakistan Penal Code's
# Section 302 from another Act's unrelated Section 302.
_ALIAS_EXPANSIONS = {
    "ppc": ("pakistan", "penal", "code"),
    "crpc": ("criminal", "procedure", "code"),
}


def _tokenize(text: str) -> list[str]:
    tokens = _TOKEN_RE.findall(text.lower())
    expanded = list(tokens)
    for tok in tokens:
        expanded.extend(_ALIAS_EXPANSIONS.get(tok, ()))
    return expanded


def _edit_distance(a: str, b: str, max_dist: int) -> int:
    """Levenshtein distance, capped at max_dist + 1 once exceeded (bails out
    of comparisons against words that are already too far off — used for
    fuzzy-correcting typos against a multi-thousand-term vocabulary, so
    cheap short-circuiting matters more than exactness past the cap).

    Deliberately not difflib.SequenceMatcher: its ratio() is asymmetric
    (SequenceMatcher(None, a, b).ratio() != ...(None, b, a).ratio()) and
    get_close_matches() fixes the query as one side of that asymmetry —
    on real typos (e.g. "mudur" for "murder") that ordering can rank
    unrelated short words above the actual intended word.
    """
    if abs(len(a) - len(b)) > max_dist:
        return max_dist + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[len(b)]


def _shard_files(shard_dir: Path) -> list[Path]:
    """Every document shard under data/corpus/ — excludes the
    <shard>.index_meta.json sidecar files build_index.py writes there,
    which are metadata, not corpus content."""
    return sorted(
        p for p in shard_dir.glob("*.json")
        if not p.name.endswith(".index_meta.json")
    )


class LegalIndex:
    """In-memory hybrid index over the legal corpus."""

    def __init__(self) -> None:
        self.docs: list[dict] = []
        self.embeddings: Optional[np.ndarray] = None
        self.embed_ok = False
        # BM25 state — an inverted index (term -> [(doc_idx, term_freq)]),
        # so a query only touches documents containing its terms instead of
        # scanning the whole corpus. Matters once the corpus is thousands
        # of chunks rather than hundreds.
        self._doc_len: list[int] = []
        self._avg_len = 0.0
        self._postings: dict[str, list[tuple[int, int]]] = {}
        self._df: dict[str, int] = {}
        # Vocabulary grouped by first letter, for fuzzy typo correction —
        # scanning the full multi-thousand-term vocabulary with an edit
        # distance check per candidate is too slow for query-time use (it
        # measured ~0.3s per unmatched token against ~7k terms). Typos
        # essentially never change the first letter, so bucketing by it
        # cuts the candidate set by roughly 26x for a negligible accuracy
        # cost.
        self._vocab_by_letter: dict[str, list[str]] = {}

    # ---------------------------------------------------------------- load

    def load(self) -> None:
        self._load_documents()
        self._load_embeddings()
        self._build_keyword_index()
        logger.info(
            "Legal index ready: %d docs, vector search %s",
            len(self.docs),
            "enabled" if self.embed_ok else "DISABLED",
        )

    def _load_documents(self) -> None:
        """Load the base corpus plus any additional shards under data/corpus/.

        Shards let a new Act be added as its own file — ingest_pdf.py writes
        one shard per source — without touching documents.json or any other
        shard. A duplicate id across shards is a load-time error (loud, not
        a silent overwrite), since it usually means two shards cover the
        same Act.
        """
        self.docs = []
        seen_ids: dict[str, str] = {}  # id -> which file it came from

        def _load_one(path: Path) -> list[dict]:
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                logger.error("Failed to load %s: %s", path.name, exc)
                return []
            if not isinstance(raw, list):
                logger.error("%s is not a list; ignoring", path.name)
                return []
            valid = [d for d in raw if isinstance(d, dict) and d.get("text")]
            deduped = []
            for d in valid:
                doc_id = d.get("id")
                if doc_id in seen_ids:
                    logger.error(
                        "Duplicate document id %r in %s (already loaded from %s) — skipping",
                        doc_id, path.name, seen_ids[doc_id],
                    )
                    continue
                seen_ids[doc_id] = path.name
                deduped.append(d)
            return deduped

        base_path = DATA_DIR / "documents.json"
        if base_path.exists():
            self.docs.extend(_load_one(base_path))
        else:
            logger.warning("documents.json not found — base legal database is empty")

        shard_dir = DATA_DIR / "corpus"
        if shard_dir.is_dir():
            for shard_path in _shard_files(shard_dir):
                shard_docs = _load_one(shard_path)
                self.docs.extend(shard_docs)
                logger.info("Loaded shard %s: %d documents", shard_path.name, len(shard_docs))

    def _load_embeddings(self) -> None:
        """Load the base embedding matrix plus any per-shard matrices under
        data/corpus/, in the same order documents were loaded, so a new
        shard's embeddings never require re-embedding (or even touching)
        anything that came before it.
        """
        if not self.docs:
            return

        base_path = DATA_DIR / "documents.json"
        base_count = 0
        if base_path.exists():
            try:
                base_count = len(json.loads(base_path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                base_count = 0

        def _load_matrix(path: Path, expected_rows: int) -> Optional[np.ndarray]:
            try:
                arr = np.load(path)
            except FileNotFoundError:
                logger.warning("%s not found — that source has no vector search "
                               "until scripts/build_index.py embeds it (BM25 still covers it)",
                               path.name)
                return None
            except (OSError, ValueError) as exc:
                logger.error("%s corrupted: %s — vector search unavailable for that source",
                             path.name, exc)
                return None
            if arr.ndim != 2 or arr.shape[0] != expected_rows:
                logger.error(
                    "%s shape %s does not match %d documents — vector search unavailable "
                    "for that source", path.name, arr.shape, expected_rows,
                )
                return None
            return arr.astype(np.float32, copy=False)

        # Load each source's matrix independently. A source with missing or
        # bad embeddings doesn't take vector search down for everyone else —
        # it's zero-filled (see below) so BM25 still covers its documents,
        # while every other source's vector search keeps working untouched.
        sources: list[tuple[Optional[np.ndarray], int]] = [
            (_load_matrix(DATA_DIR / "embeddings.npy", base_count), base_count),
        ]
        shard_dir = DATA_DIR / "corpus"
        if shard_dir.is_dir():
            for shard_path in _shard_files(shard_dir):
                try:
                    shard_count = len(json.loads(shard_path.read_text(encoding="utf-8")))
                except (json.JSONDecodeError, OSError):
                    shard_count = 0
                embed_path = shard_path.with_suffix("").with_suffix(".embeddings.npy")
                sources.append((_load_matrix(embed_path, shard_count), shard_count))

        dim = next((m.shape[1] for m, _ in sources if m is not None), None)
        if dim is None:
            return  # nothing anywhere has valid embeddings yet

        matrices = [
            m if m is not None else np.zeros((count, dim), dtype=np.float32)
            for m, count in sources
        ]
        combined = np.concatenate(matrices, axis=0)
        if combined.shape[0] != len(self.docs):
            logger.error(
                "Combined embeddings shape %s does not match %d total documents — "
                "vector search disabled", combined.shape, len(self.docs),
            )
            return
        self.embeddings = combined
        self.embed_ok = True

    def _build_keyword_index(self) -> None:
        # Title is weighted 3x: it's the highest-signal, lowest-noise part of
        # a document (and the only place a glossary synonym like PPC's
        # "qatl-i-amd [murder]" lives — audit finding: a single title-only
        # occurrence of a synonym couldn't out-compete a sibling section's
        # organic, repeated use of the same word in its body text, so a
        # plain-English query would rank the sibling above the section it
        # was actually asking about).
        doc_tokens = [
            _tokenize(
                f"{d.get('title', '')} {d.get('title', '')} {d.get('title', '')} "
                f"{d.get('section', '') or ''} {d.get('text', '')}"
            )
            for d in self.docs
        ]
        self._doc_len = [len(t) for t in doc_tokens]
        self._avg_len = (sum(self._doc_len) / len(self._doc_len)) if self._doc_len else 0.0

        postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for idx, toks in enumerate(doc_tokens):
            for term, tf in Counter(toks).items():
                postings[term].append((idx, tf))
        self._postings = dict(postings)
        self._df = {term: len(plist) for term, plist in self._postings.items()}
        vocab_by_letter: dict[str, list[str]] = defaultdict(list)
        for term in self._postings:
            vocab_by_letter[term[0]].append(term)
        self._vocab_by_letter = dict(vocab_by_letter)

    # -------------------------------------------------------------- search

    def vector_search(self, query: str, k: int = VECTOR_K,
                      allowed: Optional[list[int]] = None) -> list[tuple[int, float]]:
        """Cosine similarity search. Returns [(doc_idx, score)]."""
        if not self.embed_ok or self.embeddings is None:
            return []
        try:
            q = np.asarray(ollama_embed([query])[0], dtype=np.float32)
        except Exception as exc:
            logger.warning("Query embedding failed — vector search skipped: %s", exc)
            return []
        norm = float(np.linalg.norm(q))
        if norm == 0:
            return []
        q = q / norm
        scores = self.embeddings @ q  # docs are pre-normalized
        if allowed is not None:
            mask = np.full(len(self.docs), -np.inf, dtype=np.float32)
            mask[allowed] = 0.0
            scores = scores + mask
        top = np.argsort(-scores)[:k]
        return [(int(i), float(scores[i])) for i in top if np.isfinite(scores[i])]

    def _correct_token(self, tok: str) -> str:
        """Fuzzy-correct a query token with no BM25 postings to the closest
        indexed term (e.g. "mudur" -> "murder"). BM25 is exact-match, so a
        single typo on the one content word in a short query previously
        returned zero keyword candidates. Only tried when the token isn't
        already indexed, so correctly-spelled queries pay nothing extra;
        4-char minimum avoids risky corrections on short words. Allowed
        edit distance scales with word length (~1/3, floor 1) so longer
        words tolerate more corruption without opening short words up to
        matching almost anything. Candidates are restricted to the query
        token's first-letter bucket (see _vocab_by_letter)."""
        if tok in self._postings or len(tok) < 4:
            return tok
        max_dist = max(1, (len(tok) + 1) // 3)
        best, best_dist = tok, max_dist + 1
        for cand in self._vocab_by_letter.get(tok[0], ()):
            if abs(len(cand) - len(tok)) > max_dist:
                continue
            d = _edit_distance(tok, cand, max_dist)
            if d < best_dist:
                best, best_dist = cand, d
                if d == 0:
                    break
        return best

    def keyword_search(self, query: str, k: int = KEYWORD_K,
                       allowed: Optional[list[int]] = None) -> list[tuple[int, float]]:
        """BM25 search via inverted index.

        Only touches documents that contain at least one query term —
        cost scales with how many documents match, not with corpus size.
        """
        if not self.docs:
            return []
        q_tokens = [self._correct_token(t) for t in _tokenize(query)]
        if not q_tokens:
            return []
        n = len(self.docs)
        k1, b = 1.5, 0.75
        allowed_set = set(allowed) if allowed is not None else None
        scores: dict[int, float] = {}
        for tok in set(q_tokens):
            plist = self._postings.get(tok)
            if not plist:
                continue
            df = self._df[tok]
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            for idx, tf in plist:
                if allowed_set is not None and idx not in allowed_set:
                    continue
                dl = self._doc_len[idx] or 1
                scores[idx] = scores.get(idx, 0.0) + (
                    idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / self._avg_len))
                )
        results = sorted(scores.items(), key=lambda x: -x[1])
        return results[:k]

    # ------------------------------------------------------------ pipeline

    def _metadata_filter(self, jurisdiction: Optional[str],
                         province: Optional[str]) -> Optional[list[int]]:
        """Soft jurisdiction filter.

        Documents from a *different* known jurisdiction are excluded;
        documents with missing metadata are kept (unknown ≠ invalid).
        Returns None when no filter applies (search everything).
        """
        if not jurisdiction:
            return None
        j = jurisdiction.strip().lower()
        p = province.strip().lower() if province else None
        allowed = []
        for idx, d in enumerate(self.docs):
            dj = (d.get("jurisdiction") or "").strip().lower()
            if dj and dj != j:
                continue  # known, different country -> exclude
            dp = (d.get("province_or_state") or "").strip().lower()
            if p and dp and dp != p:
                continue  # known, different province -> exclude
            allowed.append(idx)
        # If filtering would wipe out everything, fall back to unfiltered search.
        return allowed if allowed else None

    def retrieve(
        self,
        query: str,
        jurisdiction: Optional[str] = None,
        province_or_state: Optional[str] = None,
        legal_domain: Optional[str] = None,
        k: int = FINAL_K,
    ) -> dict:
        """Full hybrid retrieval pipeline.

        Returns a debug-friendly dict:
            {
              "sources": [doc, ...],          # final ranked chunks (may be [])
              "relevant": bool,               # False -> honest "no sources" answer
              "debug": {...timings and candidate lists...}
            }
        """
        t0 = time.time()
        debug: dict = {"query": query, "jurisdiction": jurisdiction,
                       "province_or_state": province_or_state,
                       "legal_domain": legal_domain}

        if not self.docs:
            return {"sources": [], "relevant": False,
                    "debug": {**debug, "error": "empty legal database"}}

        allowed = self._metadata_filter(jurisdiction, province_or_state)
        debug["filtered_corpus_size"] = len(allowed) if allowed is not None else len(self.docs)

        t = time.time()
        vec = self.vector_search(query, allowed=allowed)
        debug["vector_time"] = round(time.time() - t, 3)
        debug["vector_candidates"] = [
            (self.docs[i]["id"], round(s, 3)) for i, s in vec]

        t = time.time()
        kw = self.keyword_search(query, allowed=allowed)
        debug["keyword_time"] = round(time.time() - t, 3)
        debug["keyword_candidates"] = [
            (self.docs[i]["id"], round(s, 2)) for i, s in kw]

        # ---------------- Reciprocal Rank Fusion (rank-based, not raw scores)
        vec_scores = dict(vec)
        kw_scores = dict(kw)
        fused: dict[int, float] = {}
        for rank, (idx, _) in enumerate(vec):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (RRF_K + rank + 1)
        for rank, (idx, _) in enumerate(kw):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (RRF_K + rank + 1)

        # ---------------- Relevance threshold
        # A candidate survives if its vector similarity is decent OR its BM25
        # score is strong (exact terms like "Section 10" may not embed well).
        survivors = [
            idx for idx in fused
            if vec_scores.get(idx, 0.0) >= MIN_COSINE or kw_scores.get(idx, 0.0) >= MIN_BM25
        ]
        debug["threshold_survivors"] = len(survivors)

        if not survivors:
            debug["total_time"] = round(time.time() - t0, 3)
            return {"sources": [], "relevant": False, "debug": debug}

        # ---------------- Authority / domain / status / date ranking
        t = time.time()
        ranked = authority_rank(
            [(idx, fused[idx]) for idx in survivors],
            self.docs,
            jurisdiction=jurisdiction,
            province_or_state=province_or_state,
            legal_domain=legal_domain,
            query=query,
        )
        debug["rank_time"] = round(time.time() - t, 3)
        debug["final_ranking"] = [
            (self.docs[i]["id"], round(s, 4)) for i, s in ranked[:k]]

        sources = [self.docs[i] for i, _ in ranked[:k]]
        debug["total_time"] = round(time.time() - t0, 3)
        return {"sources": sources, "relevant": True, "debug": debug}


# Module-level singleton, loaded by main.py at startup.
index = LegalIndex()
