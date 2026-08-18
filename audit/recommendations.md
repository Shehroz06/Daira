# Phase 12 — Recommended Improvements (prioritized)

Status: **recommendations only, no code modified.** Every item below cites
the specific phase(s) whose evidence motivates it. Ordered by priority
(expected benefit weighed against complexity and risk), not by phase
number. "Priority" is a judgment call made explicit here so it can be
challenged before Phase 13 touches any code.

## Priority 1 — Highest evidenced benefit, contained risk

### 12.1 Fix the hyphenated-letter-suffix section-marker parsing gap
**Evidence**: Phase 4 — 26 PPC base sections / 146 marker occurrences
merged incorrectly (`ppc-section-337` alone merges 26 distinct offences,
17,925 chars). Phase 6 — this is *why* `ppc-section-337` gets embedded at
only ~44% coverage (truncation). Phase 9/11 — this defect surfaces
downstream as a citation the corpus can't cleanly represent ("Section
381-A"), reproduced independently twice.
**Fix**: extend `scripts/ingest_pdf.py`'s `MARKER_RE` to also match
`\d{1,3}-[A-Z]\.` (not just `\d{1,3}[A-Z]?\.`), so `"337-A."` opens its
own section instead of falling inside 337's body. Re-run ingestion for
PPC only (other sources unaffected — Phase 4 confirmed this is
PPC-specific). Re-run `scripts/build_index.py` to refresh PPC's embedding
shard.
**Benefit**: directly fixes the root cause of the worst chunk-size and
worst embedding-truncation outliers found in Phases 4/6; gives 26
currently-invisible offences (e.g. distinct grievous-hurt variants under
337-A through 337-Z) their own citable, retrievable identity.
**Complexity**: Low–Medium (regex change + targeted re-ingestion + one
shard's embeddings rebuilt — Ollama required, no schema change).
**Risk**: Low. Purely additive — splits one oversized chunk into many
correctly-sized ones; doesn't touch any other source or any ranking code.
**Priority: 1 (do first).**

### 12.2 Add an explicit "specific vs. general provision" ranking signal
**Evidence**: Phase 7 — proved with a direct re-insertion test that even
handing `authority_rank()` the correct document (Section 302), it still
loses to General Part sections because *no signal anywhere* distinguishes
"defines a specific offence" from "states a principle applicable to every
offence." Phase 11 — confirmed this is not a two-query fluke: Murder R@1 =
0.20 (n=10), Hurt R@1 = 0.43 (n=7), both showing the identical pattern.
Phase 9/11 — this is also the exact scenario where the LLM's own
sufficiency judgment fails (over-generalizes instead of flagging the gap).
**Fix (research-backed, not a guess)**: PPC's own structure already marks
this distinction — General Part sections live in Chapters II–V (General
Explanations, Punishments, General Exceptions, Abetment); every specific
offence lives in a later, offence-named chapter. This is recoverable
**without new manual metadata** — `scripts/ingest_pdf.py` already parses
chapter headings for other purposes (Phase 5 confirmed 51 chapter headers
are extracted from the raw PDF and then discarded). Tag each section with
its chapter number/name at ingestion time, classify Chapters II–V as
`provision_type: "general"` vs. everything else `"specific"`, and give
`authority_rank()` a new small negative weight for `general` when the
query's retrieval score already indicates a plausible domain match (i.e.
down-rank general provisions *relative to* specific ones competing for
the same query, not remove them — they're still valid supporting context).
**Benefit**: directly targets the single most-evidenced, highest-severity
finding in the entire audit (murder/hurt R@1).
**Complexity**: Medium — needs a schema addition (`provision_type` field),
a re-ingestion pass for PPC (chapter boundaries are already parsed, just
not persisted), and a new weighted term in `legal_ranker.authority_rank()`.
**Risk**: Medium — a ranking-formula change needs regression testing
against every category that currently scores well (Phase 14 exists for
exactly this). Must not simply delete General Part sections from results
(they're often legitimately relevant, e.g. abetment questions) — this is a
re-weighting, not a filter.
**Priority: 1 (highest-value fix in the whole audit, but sequence after
12.1 since 12.1 is a prerequisite for clean PPC chapter boundaries).**

### 12.3 Strengthen the sufficiency-check instruction in the system prompt
**Evidence**: Phase 9 — proved the model's "are sources sufficient?"
judgment tracks *surface topical similarity*, not whether the *specific*
fact asked was actually found, using a direct controlled contrast (murder
vs. bail). Phase 11 — reproduced this a second time (2/2 murder-category
generation tests over-generalized) while also showing 5/5 *other*
uncovered-category tests were handled honestly — meaning the model is
*capable* of the right judgment, just inconsistently applies it exactly
when sources are topically adjacent.
**Fix**: add one explicit instruction to `LEGAL_SYSTEM_PROMPT` telling the
model to check whether retrieved sources state the *specific* fact asked
(not just a related general principle) before treating them as
sufficient — e.g. "Before answering, check whether your sources actually
state the specific rule asked about, not just a related general
principle; if they only offer the latter, say so explicitly rather than
answering as if the specific rule were covered." This was already
identified as a candidate in Phase 9 but deliberately not implemented
then, per the audit's "don't touch prompts before finishing the audit"
rule — that rule's condition is now satisfied.
**Benefit**: directly addresses Symptom 3/4's downstream user-facing
harm (confident wrong-sounding answers) even before 12.2's deeper
retrieval fix lands; cheap insurance layer under 12.2.
**Complexity**: Low — one prompt addition, no code path change.
**Risk**: Low–Medium — prompt changes can shift behavior on currently-good
answers; must re-run Phase 9/11-style spot checks (not just the murder
case) after changing it, per governing rule "never reduce accuracy for
speed."
**Priority: 1 (cheap, evidenced, and independent of 12.1/12.2 — can ship
in parallel).**

## Priority 2 — Real, evidenced, lower severity or narrower scope

### 12.4 Add a coverage/ambiguity gate for the relevance threshold
**Evidence**: Phase 11 §11.4 — **16/16 (100%) of genuinely-uncovered
queries** (bail, family, criminal_procedure, etc.) were marked
`relevant=True` by `rag.py`'s threshold, each returning 5 confident-
looking but wrong sources. Phase 7 §7.3 first flagged the *architectural*
gap (no mechanism symmetric to the existing jurisdiction gate); Phase 11
is the first to *quantify* it at 100% false-positive rate.
**Fix**: this is architecturally different from 12.2 — it's not about
ranking order, it's about whether to show results at all. One concrete,
testable option: require **both** vector and BM25 channels to independently
clear a stricter joint threshold (currently `OR`, could require `AND`
plus a minimum score margin) before marking `relevant=True`, OR add a
secondary check comparing the top result's score against the *median* of
its own candidate pool (a real "this doesn't stand out" signal, rather
than a fixed global constant). Needs its own small evaluation pass (not
just intuition) before being trusted — Phase 13 should re-run Phase 11's
16 uncovered-category queries specifically against any threshold change,
since 12.3's prompt fix already covers this failure mode more cheaply and
this is a candidate for "is 12.3 alone sufficient, or is this still
needed" — recommend implementing 12.3 first and re-measuring before
building this.
**Benefit**: closes the retrieval-layer gap Phase 11 found, rather than
depending entirely on the LLM (12.3) to catch it every time.
**Complexity**: Medium — threshold-logic change needs its own careful
tuning pass, referencing the existing known finding (`CLAUDE.md`'s
documented car-repair false positive) so as not to regress it.
**Risk**: Medium — could reduce recall on legitimately-narrow-margin good
queries; must be evaluated with Phase 11's benchmark before/after, not
assumed safe.
**Priority: 2 (do after measuring whether 12.3 alone is enough).**

### 12.5 Fix hyphenated-compound query tokenization
**Evidence**: Phase 8 §8.2 — "Qatl-i-Amd" tokenizes to
`['qatl','i','amd']`, and the stray `"i"` token has document frequency
114/1268 — measurable noise, not theoretical. Same regex blind spot as
12.1, but on the query side (`app/rag.py::_tokenize`).
**Fix**: in `_tokenize()`, treat a lone single-letter token surrounded by
hyphens as part of its neighboring compound rather than a separate token
(e.g. `qatl-i-amd` → keep as `qatli`+`amd` or a single `qatliamd` token,
matching however 12.1's fix ends up normalizing the same compounds in
document titles/glossary).
**Benefit**: removes a small, real, quantified source of BM25 noise;
low-effort complement to 12.1 (same underlying defect, opposite side).
**Complexity**: Low.
**Risk**: Low — must add a regression test asserting `qatl-i-amd` no
longer produces a bare `"i"` token (Phase 14).
**Priority: 2.**

### 12.6 Add lightweight stemming/synonym normalization for common legal-vocabulary mismatches
**Evidence**: Phase 8 §8.3 — "stealing" (a completely natural query word)
retrieves only `ppc-section-326` ("Thug"), zero theft-relevant results,
because the corpus's own text says "theft." "attempted" vs "attempt"
returns **completely disjoint** result sets, with Section 324 (the
originally-reported Symptom 3 target) absent from "attempted"'s results
entirely.
**Fix**: a small, explicit synonym/normalization map for the highest-
value known mismatches (steal→theft, attempted→attempt, kill→murder, hit→
hurt, etc.), applied at query time only — not a general stemmer (avoids
the complexity/regression-risk of a full linguistic stemming library for
a corpus this size, consistent with `CLAUDE.md`'s "no dependencies beyond
what's used" convention). This is a narrow, targeted extension of the
*existing* mechanism (`ingest_pdf.py`'s glossary, Phase 8 §8.4) rather
than a new one, but applied query-side rather than title-side.
**Benefit**: directly fixes two concretely-demonstrated, high-severity
misses for completely natural English phrasings.
**Complexity**: Low–Medium (needs a maintained mapping, not just a
regex).
**Risk**: Low, if scoped to a short explicit list rather than an automatic
stemmer (which risks unintended collisions across a multi-Act legal
corpus where word choice is often deliberately precise).
**Priority: 2.**

### 12.7 Strip chapter/part heading leakage from chunk bodies
**Evidence**: Phase 5 — 89/1268 chunks (7.0%) have CHAPTER/PART headings
contaminating body text, across all 3 sources (more general than 12.1's
PPC-specific defect).
**Fix**: extend `ingest_pdf.py`'s cleaning step to strip lines matching
the already-known chapter/part heading patterns (the same 51 headers
Phase 5 found were extractable) before they're folded into a section's
body text.
**Benefit**: modest but real text-quality cleanup; low interaction risk
with other fixes.
**Complexity**: Low.
**Risk**: Low.
**Priority: 2.**

## Priority 3 — Real but lower-severity, or requires a scope decision from you

### 12.8 Guard against embedding truncation for any future oversized chunk
**Evidence**: Phase 6 — confirmed empirically at ~2048 tokens (matches
the model's native limit, not the configured `num_ctx=8192`). Currently
only 3/1268 docs affected, and 12.1 fixes the worst offender
(`ppc-section-337`) directly.
**Fix**: add a build-time warning (not a hard failure — consistent with
"graceful degradation everywhere," `CLAUDE.md`) in `scripts/build_index.py`
when a chunk's character count exceeds the empirically-confirmed
truncation point, so future ingestions catch this class of defect before
it silently ships, rather than requiring another audit to find it.
**Benefit**: prevents recurrence of exactly what 12.1 is fixing, for any
future source.
**Complexity**: Low (a length check + log warning).
**Risk**: None — purely diagnostic, no behavior change.
**Priority: 3 (cheap safety net, not urgent on its own).**

### 12.9 Ingest CrPC and family-law statutes — a scope decision, not a code fix
**Evidence**: Phase 1/2/11 — bail (100% of queries, Phase 11), most of
criminal_procedure, and most of family law are **entirely absent** from
the corpus — not a retrieval defect, a coverage gap. `data/
acts_registry.json` already lists `crpc` as `status: "pending"`.
**Not recommending a specific fix here** — this is new-source ingestion
(PDF sourcing + `ingest_pdf.py` configuration for a new Act), which is a
content project on the scale of the PPC/Labour Code work already done
this session, not a pipeline bug fix. Flagging it because Phase 11
quantified how often it's hit (bail: 5/5 sample queries all correctly
refuse, but a refusal isn't a *useful* answer to a very common real-world
legal question), but whether to scope this into the current
Implementation phase (13, which the governing rules say should stay
narrow and evidence-driven) or treat it as separate follow-up work is a
product decision for you, not something the audit should decide
unilaterally.
**Priority: 3, pending your call on scope.**

## Summary table

| # | Recommendation | Evidence | Benefit | Complexity | Risk | Priority |
|---|---|---|---|---|---|---|
| 12.1 | Fix hyphenated-suffix marker parsing | Ph. 4, 6, 9, 11 | High | Low–Med | Low | **1** |
| 12.2 | General-vs-specific provision ranking signal | Ph. 5, 7, 9, 11 | High | Medium | Medium | **1** |
| 12.3 | Strengthen sufficiency-check prompt instruction | Ph. 9, 11 | High | Low | Low–Med | **1** |
| 12.4 | Coverage/ambiguity gate on relevance threshold | Ph. 7, 11 | Medium | Medium | Medium | 2 |
| 12.5 | Fix hyphenated-compound query tokenization | Ph. 8 | Low–Med | Low | Low | 2 |
| 12.6 | Targeted query-side synonym normalization | Ph. 8 | Medium | Low–Med | Low | 2 |
| 12.7 | Strip chapter/part heading leakage | Ph. 5 | Low | Low | Low | 2 |
| 12.8 | Build-time truncation-risk warning | Ph. 6 | Low | Low | None | 3 |
| 12.9 | Ingest CrPC / family law (scope decision) | Ph. 1, 2, 11 | High (coverage) | High | — | 3, needs your call |

**Recommended Phase 13 order** (each implemented and re-benchmarked
individually, per the governing rule): **12.1 → 12.2 → 12.3 →
[re-measure] → 12.5 → 12.6 → 12.7 → 12.4 (if still needed after 12.3) →
12.8**. 12.9 held out pending your decision on scope.

---

**End of Phase 12.** No code was modified.

Stopping here per your instruction to review before proceeding to Phase 13
(Implementation).
