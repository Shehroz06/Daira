# Diara Legal RAG — Forensic Audit & Recovery: Final Report

15-phase audit of four reported retrieval failures. Phases 1-12 (read-only
forensic audit) and 14 (regression testing) are summarized here; full
evidence lives in the per-phase files listed at the end. Phase 13
(implementation) fixed the three symptoms confirmed to be live bugs.

## 1. Architecture (see `01_architecture_overview.md`)

```
USER -> FastAPI (main.py) -> app/diara.py (session/orchestration)
      -> app/legal_query.py (heuristic fast-path, or one LLM call for
         complex queries — jurisdiction/domain/facts extraction)
      -> app/rag.py (BM25 inverted index + vector cosine search ->
         Reciprocal Rank Fusion -> relevance threshold)
      -> app/legal_ranker.py (re-ranks by authority/jurisdiction/domain/
         status/date/[new: provision specificity/qualifier match])
      -> app/prompts.py + app/llm.py (Gemini/Ollama fallback) -> answer
```

Corpus at audit start: 1268 chunks across Constitution (304 articles),
PPC (509→**592** sections after Phase 13), Punjab Labour Code (435
sections), plus a small original hand-written demo corpus.

## 2. Weaknesses found, by severity

| # | Weakness | Phase | Status |
|---|---|---|---|
| 1 | PPC hyphenated section markers (`337-A.`) merged into the preceding section — one PPC chunk merged 26 distinct offences | 4 | **Fixed** (13) |
| 2 | General Part (Sections 1-120) systematically outranks specific offences for lay-phrased criminal queries | 7, 11 | **Fixed** (13) |
| 3 | Within a family of related specific offences (murder/attempt/dacoity-with-murder), nothing distinguished the base offence from variants | 7, 11 | **Fixed** (13) |
| 4 | Relevance threshold has ~0% precision on genuinely-uncovered query categories (16/16 false `relevant=True`) | 11 | Open — recommended (12.4), not implemented |
| 5 | LLM sufficiency judgment inconsistently over-generalizes on topically-adjacent-but-wrong sources | 9, 11 | Open — recommended (12.3), not implemented |
| 6 | No stemming; "stealing"→wrong doc, "attempted"↔"attempt" disjoint result sets | 8 | Open — recommended (12.6) |
| 7 | Query-side hyphen tokenization shreds compounds ("qatl-i-amd"→3 tokens incl. noise token "i") | 8 | Open — recommended (12.5) |
| 8 | 89/1268 chunks have chapter/part headings leaked into body text | 5 | Open — recommended (12.7) |
| 9 | Embedding truncation at ~2048 tokens for oversized chunks | 6 | Mostly resolved as a side effect of fixing #1 |
| 10 | 25 documents (19 PPC + 6 Constitution) genuinely repealed but tagged `status: active`; Section 304-A and CrPC/bail entirely absent from corpus | 2, 11 | Open — content/data gaps, not code bugs |

## 3. Root causes (the four originally reported symptoms)

1. **"punishment of theft" → no result.** Root cause: PPC simply wasn't
   ingested yet at the time reported. Resolved earlier this session
   (before the audit began) by ingesting PPC; confirmed still resolved in
   Phase 7 and Phase 13.
2. **"I did a murder" → Section 324 (attempt).** Root cause: two-layered —
   (a) Section 302 missed both retrieval channels' top-12 cutoff entirely;
   (b) even manually reinserted, it still lost to PPC's General Part
   sections (37/79/108) because no signal in the ranking formula
   distinguished "specific offence" from "general principle." **Fixed.**
3. **"completed murder" → Section 396 (dacoity with murder).** Same
   mechanism as #2, confirmed independently. Additionally exposed a
   second-order problem once #2's fix landed: siblings within the murder
   family (300/302/306/314/324/396) had no differentiation from each
   other either. **Fixed.**
4. **"what are my rights?" → confident wrong answer.** Different
   architecture entirely — no single correct target exists for this
   question; it needs a clarification/ambiguity gate (like the existing
   jurisdiction gate), not a ranking fix. **Not fixed** — flagged as
   recommendation 12.4, held out of Phase 13's urgent-fix scope by
   explicit instruction.

## 4. Metrics: before vs. after (100-query benchmark + live generation)

| Metric | Phase 11 (before) | Phase 14 (after) |
|---|---|---|
| Aggregate Recall@1 | 0.62 | 0.60 |
| Aggregate Recall@3 | 0.81 | 0.83 |
| Aggregate Recall@5 | 0.82 | 0.85 |
| Aggregate MRR | 0.72 | 0.71 |
| **Murder R@1 / MRR** | **0.20 / 0.38** | **0.40 / 0.55** |
| Hurt R@1 / MRR | 0.43 / 0.50 | 0.29 / 0.35 (disclosed trade-off, §5) |
| Citation accuracy (live generation) | 24/24 clean (Ph. 9-11) | 9/9 clean (Ph. 14) |
| Hallucination rate | 0/24 | 0/9 |
| Hermetic test suite | 70/70 | 70/70 |
| Live retrieval regression suite | n/a (didn't exist) | 8/8 (new) |

## 5. Before → after on the reported queries

| Query | Before | After top-5 |
|---|---|---|
| "punishment of theft" | No sources (corpus gap, pre-audit) | 379, 382, 439, 378, 390 |
| "I did a murder what happens to me?" | 37, 79, 108, 38, 254 (General Part; 302 absent) | 300, 314, **302**, 37, 79 |
| "Not attempt, completed murder." | 38, 37, 36, 396, 324 (General Part + wrong variant; 302 absent) | 300, 306, **302**, 36, 37 |

## 6. Implemented changes (Phase 13)

1. `scripts/ingest_pdf.py` — `MARKER_RE` now matches hyphenated section
   suffixes. Re-ingested PPC (509→592 sections) and Constitution (+3
   previously-lost articles). Embeddings rebuilt.
2. `app/rag.py` — `VECTOR_K`/`KEYWORD_K` widened 12→50/25 (brute-force
   cosine search cost is independent of K, so this was nearly free); BM25
   now weights document titles 3x (titles carry the PPC glossary's
   English synonyms, previously under-weighted against organic body-text
   matches).
3. `app/legal_ranker.py` — two new PPC-scoped ranking signals in
   `authority_rank()`: a general-vs-specific provision score (based on
   PPC's real, public chapter structure — Sections ≤120 are General Part)
   and a qualifier-match score (a query naming no qualifier like "attempt"
   or "dacoity" shouldn't be pushed toward a variant section that has
   one; handles negation, e.g. "**not** attempt").
4. `tests/test_retrieval_regression.py` — new, 8 live cases covering
   theft/murder/qatl-i-amd/attempt/dacoity/robbery plus the exact
   negation-style symptom queries.

Deliberately **not** touched: `LEGAL_SYSTEM_PROMPT` (per explicit
instruction — prompt changes are not a substitute for a real retrieval
fix, and retrieval is what was broken).

## 7. Disclosed trade-offs / regressions (Phase 14 detail)

- **Hurt category R@1 dropped** (0.43→0.29): a direct, expected
  consequence of correctly splitting the merged `ppc-section-337` blob.
  The old chunk artificially won generic "hurt" queries by containing
  every hurt variant's vocabulary; that was never a genuine strength.
  Needs the same qualifier-style treatment as the murder family — a good
  candidate for a focused follow-up, out of this session's urgent scope.
- **Constitutional/Appeal R@1 dipped slightly**: rank-2 misses (not
  exclusions) from widening the candidate pool — e.g. a PPC "unlawful
  assembly" section now edges out the Constitution's "freedom of
  assembly" article by one rank for a 2-word query. R@3/R@5 unaffected.

## 8. Recommendations not yet implemented (see `recommendations.md` for full detail)

- **12.3** — strengthen the system prompt's sufficiency-check instruction
  (targets Symptom 4 / the "what are my rights?" over-generalization
  pattern).
- **12.4** — a coverage/ambiguity gate for the relevance threshold (16/16
  false-positive rate on genuinely uncovered query categories).
- **12.5/12.6** — query-side hyphen tokenization fix; targeted
  steal↔theft / attempt↔attempted synonym normalization.
- **12.7** — strip chapter/part heading leakage from 89/1268 chunks.
- **12.9** — ingest CrPC (governs bail — 100% absent from corpus) and
  family law; a content project, not a code fix, needs your scope call.
- **New from Phase 14** — extend the qualifier-match idea to the `hurt`
  family (337-A through 337-Z) to recover the R@1 this session's fix cost
  that category.

## 9. Open problems

- No mechanism exists for "this question is too ambiguous to answer
  safely" (Symptom 4) — architecturally different from a ranking fix.
- The corpus has real, unresolved content gaps: CrPC/bail, most family
  law, Section 304-A, 25 documents that are repealed but tagged active.
- Citation granularity ceiling: no document anywhere has subsection-level
  metadata; the system correctly avoids fabricating that precision
  (verified, Phase 10) rather than pretending the ceiling doesn't exist.

## 10. Lessons learned

- **The two-layer bug (K-cutoff exclusion + no ranking signal) needed
  both fixes together** — Phase 7's manual-reinsertion test proved widening
  K alone wouldn't have been sufficient, and that discipline (verify each
  layer independently before claiming a fix) is what made Phase 13's fix
  land correctly on the first evidenced attempt rather than several blind
  retries.
- **A fix for one symptom can reveal or reintroduce another** — splitting
  `ppc-section-337` correctly (fixing an evidenced parsing defect) directly
  caused the `hurt` category regression. Catching this required re-running
  the full benchmark after the change, not just re-checking the original
  three queries — a narrower regression check would have missed it.
- **Corpus-wide heuristics need corpus-wide validation before shipping** —
  the qualifier-match signal, designed for PPC's murder family, initially
  applied to every source and measurably hurt unrelated Constitution/Labour
  Code queries. Scoping it to PPC only (matching the precedent already set
  by the specificity signal) fixed it in one line once the regression was
  actually measured, not assumed away.
- **Glossary synonyms need enough term-frequency weight to compete** — a
  single title-only "[murder]" annotation lost to sections whose body text
  organically said "murder" many times; weighting title 3x in BM25 was the
  concrete fix, discovered by directly inspecting per-channel scores
  rather than guessing at the ranking formula.

---

## Phase file index

`01_architecture_overview.md` · `dataset_audit.md` · `index_audit.md` ·
`chunk_analysis.md` · `metadata_audit.md` · `embedding_quality_audit.md` ·
`retrieval_evaluation.md` · `query_understanding_audit.md` ·
`prompt_audit.md` · `citation_audit.md` · `error_analysis.md` ·
`recommendations.md` · `regression_testing.md` · `benchmark_queries.json`
(100-query ground truth, corrected during construction — see
`error_analysis.md` §11.2)
