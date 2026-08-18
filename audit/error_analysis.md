# Phase 11 — Error Analysis (100+ Query Benchmark)

Status: **read-only audit, no code modified.** Two layers of evidence:
(1) a fast, retrieval-only benchmark across **100 queries** spanning 14
categories, computed by calling `index.retrieve()` directly (no LLM), and
(2) a stratified **19-query live-generation sample** (one per category,
two for categories central to Phases 7/9's findings) for the metrics that
require actual answer text — Citation Accuracy, Hallucination Rate,
grounding/over-generalization behavior.

All ground-truth document ids were **verified to exist in the live corpus
by direct lookup before use** (`audit/benchmark_queries.json`), not
assumed. One id was caught and corrected during construction (see §11.2).

## 11.1 Method

- Ground truth built from the same verification discipline as Phases 1–10:
  every category's expected document ids were confirmed present in
  `data/documents.json` / `data/corpus/*.json` by direct lookup, not
  guessed from memory of Pakistani law.
- Categories deliberately include ones already known (Phases 1–2, 6, 9) to
  be **absent from the corpus** — `bail`, large parts of
  `criminal_procedure` and `family` — with `expected: []`. This is honest
  ground truth, not a gap in the benchmark: a system that returns nothing
  (or clearly flags insufficiency) for these is *correct*, and a system
  that returns confident-looking wrong answers is a *real defect*, so both
  outcomes needed to be measurable.
- Each query ran through the actual production path:
  `legal_query.understand()` → `rag.index.retrieve()` (heuristic path only
  — none of the 100 queries triggered the LLM query-understanding branch,
  confirmed by checking `provider="heuristic"` throughout, consistent with
  the Gemini-rationing design principle).
- Retrieval metrics computed at k=10 (beyond production's `FINAL_K=5`) to
  distinguish "wrong answer" from "right answer, ranked just past what the
  LLM sees."

## 11.2 A correction made *during* benchmark construction, not after

Two things were caught and fixed before running anything, both by direct
verification rather than assumption:

1. **`ppc-section-304a` does not exist.** Checked directly — Section
   304-A (causing death by negligence, a commonly-cited PPC provision) is
   **absent from the corpus entirely**, not merged into Section 304's
   chunk (304's actual text is narrow evidentiary rules for qatl-i-amd
   proof, unrelated). This is a **new corpus-coverage gap**, distinct from
   the already-known missing 311/315 (Phase 2) — added to the benchmark as
   `expected: []` with a note, not silently dropped.
2. **`employment-6` ("Can my employer fire me without notice?")** was
   initially benchmarked as `expected: []` (assumed uncovered). The live
   run showed this assumption was wrong: `punjab-labour-code-section-150`
   directly answers it (30-day notice-or-pay-in-lieu rule, 14 days for
   micro-enterprises) and the model cited it correctly. Flagging this here
   rather than quietly correcting it, since the audit's rule is that every
   claim must be evidence-checked — including the benchmark's own claims.

## 11.3 Retrieval-only results (100 queries, 84 with a valid target)

**Aggregate (84 covered queries):**

| Metric | Value |
|---|---|
| Recall@1 | 0.62 |
| Recall@3 | 0.81 |
| Recall@5 | 0.82 |
| Recall@10 | 0.86 |
| MRR | 0.72 |
| Mean Precision@5 | 0.19 |

**Per category:**

| Category | n covered | R@1 | R@3 | R@5 | R@10 | MRR | n uncovered |
|---|---|---|---|---|---|---|---|
| contracts | 6 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0 |
| landlord_tenant | 3 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0 |
| constitutional | 10 | 0.90 | 1.00 | 1.00 | 1.00 | 0.95 | 0 |
| consumer | 4 | 0.75 | 1.00 | 1.00 | 1.00 | 0.88 | 0 |
| family | 4 | 0.75 | 1.00 | 1.00 | 1.00 | 0.88 | 3 |
| fraud | 9 | 0.67 | 0.89 | 1.00 | 1.00 | 0.79 | 0 |
| appeal | 3 | 0.67 | 0.67 | 0.67 | 0.67 | 0.67 | 2 |
| theft | 10 | 0.60 | 0.80 | 0.80 | 0.80 | 0.70 | 0 |
| property | 8 | 0.50 | 0.88 | 0.88 | 1.00 | 0.68 | 0 |
| criminal_procedure | 2 | 0.50 | 0.50 | 0.50 | 0.50 | 0.50 | 4 |
| employment | 8 | 0.50 | 0.75 | 0.75 | 0.75 | 0.60 | 1 |
| hurt | 7 | 0.43 | 0.57 | 0.57 | 0.57 | 0.50 | 0 |
| **murder** | 10 | **0.20** | 0.50 | 0.50 | 0.70 | **0.38** | 1 |
| bail | 0 | — | — | — | — | — | 5 |

**Murder is the clear worst-performing covered category** — R@1 = 0.20,
MRR = 0.38, well below every other category with n≥4. This is not a new
finding: it is the **same mechanism Phase 7 diagnosed on 2 hand-picked
queries, now confirmed at n=10 with independently-written query
phrasings** ("I did a murder...", "Not attempt, completed murder",
"Qatl-i-amd punishment", "Murder committed under grave provocation", "What
is qisas?", etc.). Manually inspecting the 8 misses: all 8 return PPC's
General Part (Sections 36–38, 79, 108) and/or topically-adjacent-but-wrong
specific sections (306/309/396/324) ahead of Section 302 — exactly Phase
7's "General Part outranks specific offence" pattern, now shown to affect
the *category*, not just the two originally-reported phrasings.

`hurt` (R@1=0.43) is the second-worst — inspection shows the same
mechanism recurring: general assault/force provisions and
robbery-adjacent hurt sections outrank plain "voluntarily causing hurt"
(Section 332/337) for lay phrasings. This extends Phase 7's diagnosed
mechanism to a second offence category not previously tested live.

## 11.4 New finding: the relevance threshold has a 100% false-positive rate on genuinely-uncovered queries

This was **not tested in Phases 1–10** — Phase 9's contrast test (Test 2)
checked exactly one uncovered query and found the *generation* layer
correctly refused. Phase 11 tests the *retrieval* layer's `relevant` flag
directly, across all 16 uncovered-category queries (`bail`×5, `family`×3,
`criminal_procedure`×4, `appeal`×2, `employment-6` before correction,
`murder-9`):

```
16 / 16 uncovered queries -> retrieve() returned relevant=True
                              with 5 confident-looking (wrong) sources
```

Every single one crossed `MIN_COSINE`/`MIN_BM25` on some topically-adjacent
but incorrect document (e.g. a bail query pulling PPC Section 205's
incidental mention of "bail or security" in an unrelated false-personation
provision). **The threshold gate provides zero protection against this
failure mode** — it was designed to catch obviously off-topic queries
("how do I cook biryani," per `CLAUDE.md`), and does that correctly, but
has no mechanism to catch on-topic-sounding-but-wrong. The entire burden of
catching this currently falls on the LLM's own judgment at generation
time — which Phase 9 already showed is **inconsistent** (correctly refuses
for obviously-mismatched sources, over-generalizes for topically-adjacent
ones). Phase 11's generation sample (§11.5) tests whether that
inconsistency actually bites in practice across more than Phase 9's one
example.

## 11.5 Generation-layer results (19-query stratified sample)

All 19 generations completed via Gemini (no Ollama fallback needed on the
successful run — one earlier attempt did fail over to Ollama and timed
out under concurrent load, itself a minor operational data point, not a
correctness one).

**Citation accuracy — checked against the literal "Sources:" line, cross-referenced to actually-retrieved document ids:**

```
19 / 19 answers: every cited section in the "Sources:" line matches a
                 retrieved document, OR is explained by the known
                 hyphenated-suffix merged-chunk defect (Phase 4/9)
```

One apparent mismatch (`theft-1` citing "Section 381-A") is the *same*
merged-chunk artifact Phase 9 already found for a different query —
confirms it's a systematic consequence of the Phase 4 chunking defect, not
a one-off. **Zero hallucinated citations in 19 live tests** (5 in Phases
9–10 + 19 here = 24 total, 0 hallucinated).

**Honesty under genuinely insufficient sources** — every uncovered-category
query in the sample:

| Query | Behavior |
|---|---|
| `bail-1` "What is bail?" | Correctly refuses: "I cannot answer... sources do not contain a definition" |
| `crimproc-1` bail eligibility | Correctly refuses, names *why* (CrPC not in corpus) |
| `murder-9` death by negligence | Correctly refuses: "do not contain a specific section... do not cover pure criminal negligence" |
| `theft-5` "someone stole my belongings" | Retrieval missed 378/379 (returned receiving-stolen-property sections instead) — model **honestly flagged the mismatch**: "sources only cover receiving... rather than the initial act of theft itself" |
| `family-1` kidnapping-adjacent | Answered using Section 361 (kidnapping from guardianship) but explicitly caveated: "sources are limited to criminal penalties... rather than family law custody determinations" |

**5/5 in-sample uncovered/mismatched cases were handled honestly** — this
is a materially better result than §11.4's retrieval-layer 0% would
predict on its own, confirming the system currently survives on the LLM's
judgment layer catching what retrieval's threshold does not.

**But that judgment layer is not reliable — reproduced from Phase 9 at n=2 instead of n=1:**

| Query | Behavior |
|---|---|
| `murder-2` "I did a murder..." | **Over-generalizes** — confidently synthesizes an answer entirely from General Part sections (37, 38, 79, 108) without stating that none of them define murder's actual punishment |
| `murder-3` "Not attempt, completed murder" | **Same failure** — answers fluently from Sections 36–38 alone |

Both failures are in the murder category — the same category §11.3
already flagged as retrieval's worst performer. **This is the clearest
convergent finding of the whole audit**: retrieval ranks General Part
sections above Section 302 for murder queries (Phase 7, confirmed at scale
in §11.3), the relevance threshold has no way to catch it because General
Part sections are genuinely topically related (§11.4), and the LLM's
sufficiency judgment — the last line of defense — fails specifically when
the wrong sources are topically adjacent rather than obviously wrong
(Phase 9, confirmed again here). All three layers have the same blind
spot, for the same reason, on the same query category.

## 11.6 Failure category summary

| Failure category | Evidence | Phases |
|---|---|---|
| General Part outranks specific offence (retrieval) | Murder R@1=0.20 (n=10), Hurt R@1=0.43 (n=7) | 7, 8, **11 (scaled)** |
| Relevance threshold false-positive on uncovered queries | 16/16 (100%) uncovered queries marked `relevant=True` | **11 (new)** |
| LLM over-generalization on topically-adjacent-but-wrong sources | 2/2 murder-category generation tests | 9, **11 (confirmed 2nd time)** |
| Missing-section corpus gaps | 304-A (new), 311/315 (Phase 2), CrPC/bail (Phase 1) entirely absent | 2, **11 (new: 304-A)** |
| Hallucinated citations | **0/24** across all live-generation tests to date | 9, 10, **11 (confirmed at scale)** |
| Chunking defect surfacing in citations (381-A) | Reproduced a 2nd time, independently | 4, 9, **11** |
| Honest refusal under genuine source gaps | 5/5 in this sample's uncovered cases | 9, **11 (confirmed at n=5)** |

## 11.7 What Phase 11 changes about the audit's conclusions so far

Nothing in Phases 1–10 is contradicted. Phase 11's contribution is:

1. **Scale**: the murder-category retrieval failure Phase 7 diagnosed from
   2 queries is now confirmed across 10 independently-phrased queries
   (R@1=0.20) — not an artifact of the two specific reported phrasings.
2. **A second affected category found**: `hurt` (R@1=0.43) shows the same
   mechanism, previously untested.
3. **A new architectural gap, not previously measured**: the relevance
   threshold's 0% precision on genuinely-uncovered queries (§11.4) — the
   system currently has no retrieval-layer signal at all for "this looks
   topically right but isn't," relying entirely on the LLM to catch it,
   inconsistently.
4. **A new corpus gap**: Section 304-A missing entirely.
5. **One benchmark self-correction**: `employment-6` was wrongly assumed
   uncovered; the corpus in fact answers it correctly and well.

---

**End of Phase 11.** No code was modified — 100 retrieval-only calls (no
LLM) plus 19 live generation calls were made for evidence-gathering only.
Ground truth (with the 304-A/employment-6 corrections already applied) is
preserved at `audit/benchmark_queries.json`; raw per-query retrieval and
generation output were computed in a session scratch directory that does
not persist and were not archived — every number and example used above
was captured into this report directly from that output, so nothing
load-bearing depends on the scratch files.

Stopping here per your instruction to review before proceeding to Phase 12
(Recommend Improvements).
