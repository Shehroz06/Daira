# Phase 6 — Embedding Quality Audit

Status: **read-only audit, no code modified.** Every number below came from
either a direct config query (`ollama show`) or a live embedding call
against the actual running model — not from documentation alone, and not
from memory of earlier sessions.

## 6.1 Model facts

```
Model:            nomic-embed-text (nomic-bert architecture)
Parameters:       137M
Dimension:        768
Quantization:     F16
Reported context length (model card): 2048
Ollama runtime num_ctx parameter:      8192
```

These two context-length numbers disagree (model card: 2048, runtime
parameter: 8192). Rather than assume which one actually governs behavior,
I tested it directly — see §6.2.

**Normalization**: confirmed in Phase 3 — every stored vector has L2 norm
1.0 (normalized at build time by `build_index.py`, not by the model
itself).

**Pooling**: not independently verifiable from this codebase — Ollama
does not expose the model's internal pooling strategy (mean/CLS/etc.) via
its API, and inspecting it would require the model's own source, which is
out of scope for this audit. Noting this as an acknowledged blind spot
rather than asserting an unverified claim.

## 6.2 Token limit and truncation — tested directly, not assumed

Embedded the single longest chunk in the corpus (`ppc-section-337`, 17,925
characters / 3,247 words) at increasing prefix lengths, and compared each
prefix's embedding to the full-text embedding via cosine similarity. If
truncation occurs at length *L*, every prefix ≥ *L* should produce an
**identical** embedding to the full text (since the model literally never
sees anything past *L*).

| Prefix length (chars) | Words | Cosine similarity vs. full-text embedding |
|---|---|---|
| 500 | 73 | 0.9103 |
| 2,000 | 330 | 0.9632 |
| 4,000 | 687 | 0.9819 |
| **8,000** | **1,392** | **1.000000** |
| 12,000 | 2,125 | 1.000000 |
| 16,000 | 2,884 | 1.000000 |
| 17,925 (full) | 3,247 | 1.000000 |

**Confirmed: truncation occurs at ~8,000 characters (~1,392 words, roughly
2,000 tokens at typical English density) — matching the model's reported
2048 context length, not the 8192 `num_ctx` runtime parameter.** The
`num_ctx` setting does not appear to override the model's actual trained/
effective limit. Anything beyond ~2,000 tokens is silently dropped with no
error, no warning, no truncation flag anywhere in the pipeline.

**How many chunks are actually affected**: checked every chunk's
`canonical_text` length (title + section + body, exactly what
`build_index.py` sends to the embedder) against the ~8,000-char threshold:

| Source | Chunks exceeding the threshold |
|---|---|
| Base corpus | 0 / 324 |
| PPC | **2 / 509** — `ppc-section-337` (17,995 chars, ~44% actually embedded), `ppc-section-499` (8,648 chars, ~92% embedded) |
| Punjab Labour Code | **1 / 435** — `punjab-labour-code-section-13` (13,734 chars, ~58% embedded) |

Only 3 of 1268 documents (0.24%) are affected — this is not a systemic
corpus-wide problem. But for those 3, the effect is severe and
100%-confirmed, not speculative. **`ppc-section-337` compounds directly
with Phase 4's finding**: that chunk already merges 26 distinct
lettered offences (337 through 337-Z) into one oversized unit; this phase
now shows that only the *first* ~44% of that merged content — roughly
337 through the low-to-mid letters — is even present in the embedding at
all. Whatever falls in the later letters is invisible to vector search
twice over: once because it's buried inside the wrong section's chunk
(Phase 4), and again because it's past the point the embedder ever reads
(this phase).

**BM25 is not affected by this at all** — it tokenizes the full `text`
field directly in Python with no external API call and no context window,
confirmed by inspection of `app/rag.py::_build_keyword_index()`. For these
3 oversized chunks, exact keyword matches against the truncated tail would
still work via BM25 even though semantic/paraphrased matches against that
same tail cannot work via vector search. This is a concrete, mechanism-
specific asymmetry between the two retrieval paths.

## 6.3 Similarity tests — pure vector search, isolated from BM25/ranking

Per the audit brief's example query list, ran each as a **bare vector
search** (isolating embedding quality specifically — hybrid fusion and
authority ranking are Phase 7's concern, not this one) against the full
1268-document corpus, `k=10`. Ground truth was established by looking up
actual matching section titles in the corpus (not guessed) — shown in
full below, including the ranked top-10 for every query, not just
pass/fail.

**theft** — ground truth: {378 "Theft", 379 "Punishment for theft"}
```
1. ppc-section-410  0.684        6. ppc-section-382  0.648
2. ppc-section-414  0.666        7. ppc-section-411  0.645
3. ppc-section-378  0.663 ✓      8. ppc-section-412  0.644
4. ppc-section-381  0.659        9. ppc-section-379  0.640 ✓
5. ppc-section-413  0.650       10. ppc-section-390  0.634
```
Both ground-truth sections present, but neither ranks #1 — outranked by
closely-related theft-family offences (dishonest misappropriation,
receiving stolen property) that are legitimately close in meaning but not
the base "Theft" definition itself.

**robbery** — ground truth: {390, 392} — **#1 hit**, clean result.

**murder** — ground truth: {302} — **absent from the entire top 10.**
Investigated directly rather than left as a bare statistic (§6.4).

**attempt murder** — ground truth: {324} — found at rank 5 (0.637),
outranked by section 325 (a related but different attempt-family
offence) and several general homicide-context sections.

**hurt** — ground truth: {332} — **#1 hit**, clean result.

**fraud** — ground truth: {415 "Cheating", the closest PPC equivalent —
PPC has no section literally titled "Fraud"} — found at rank 2 (0.665),
narrowly edged out by section 25 ("Fraudulently," a definitional section
that is arguably also a reasonable answer to a bare "fraud" query — this
ground-truth choice itself has some legitimate ambiguity, noted rather
than hidden).

**forgery** — ground truth: {463, 465} — **#1 hit** for 463, 465 at rank 7.

**bail**, **appeal** — no ground truth defined; both concepts are governed
by CrPC, which Phase 1/2 already established is not yet ingested
(`status: pending` in `acts_registry.json`). Results were generic,
low-confidence (0.52–0.68 cosine), and largely irrelevant (Labour Code
sections, a rent tribunal judgment) — **consistent with, and further
confirming, "the correct source doesn't exist in the corpus yet" rather
than "the embedding model failed."** A useful negative control.

**property** — no single ground truth (too broad a concept, multiple
legitimately relevant chapters/documents) — results were plausible
(PPC property-offence sections, Constitution property-rights articles),
reported qualitatively only.

**contract** — ground truth: {contract-act-1872-section-10} — **#1 hit.**

### Aggregate Recall (8 queries with defined ground truth)

| Metric | Value |
|---|---|
| Recall@1 | 0.500 (4/8) |
| Recall@3 | 0.750 (6/8) |
| Recall@5 | 0.875 (7/8) |
| Recall@10 | 0.875 (7/8) — **"murder" never recovers even at k=10** |

## 6.4 Deep-dive: why "murder" fails as a bare keyword query

This result directly concerns the audit's reported symptoms (Examples 3
and 4 are both about murder retrieval), so it was investigated precisely
rather than left as a number.

```
Section 302's live title: "...Section 302 (Punishment of qatl-i-amd [murder])"
  -- confirms the PPC glossary fix (added earlier this session) is
     still active and correctly applied.

cosine(bare "murder", section 302)                              = 0.5909
cosine("what is the minimum punishment for murder?", section 302) = 0.6553
rank of section 302 for bare "murder", out of 1268 documents      = 23
```

**The glossary fix works, but only partially closes the gap, and its
effect is query-length-dependent.** A full, realistic question (matching
how users actually interact with the chat UI) scores meaningfully higher
than the bare single word. Rank 23 is outside both this test's k=10
window *and* the production pipeline's actual `VECTOR_K=12` — so a bare
"murder" query would not surface Section 302 via the vector channel in
production either. The reason: many *other* PPC sections mention "murder"
in passing as part of a related-but-different offence (dacoity-with-
murder, abetment-of-murder-adjacent sections, other homicide-chapter
provisions) and score higher against an unconstrained single-word query,
which is a known general property of dense embeddings — short queries are
inherently less discriminating than full sentences, because there's less
surrounding context to anchor the vector's meaning.

**This does not contradict the earlier in-session fix** — that fix was
validated against realistic full-question phrasing, which is the actual
production usage pattern for a chat interface, and it measurably works
there. This phase's bare-keyword test is a legitimate, harder stress test
that the audit brief specifically asked for, and it surfaces a real,
narrower residual gap: single-word legal queries remain weak, independent
of the glossary fix.

## 6.5 Summary

| Check | Result |
|---|---|
| Embedding model | nomic-embed-text, 768d, F16, confirmed via `ollama show` |
| Normalization | Confirmed L2=1.0 for all stored vectors (Phase 3) |
| Pooling strategy | Not independently verifiable from this codebase (acknowledged gap) |
| Token limit | ~2,000 tokens (~8,000 chars) — confirmed empirically, contradicts the higher `num_ctx=8192` setting |
| Truncation occurring? | Yes, confirmed for 3/1268 documents (0.24%), severe for 1 (`ppc-section-337`, ~56% of content invisible to vector search) |
| BM25 affected by the same truncation? | No — full text always tokenized, no context window |
| Recall@1 (8 grounded queries) | 0.500 |
| Recall@3 | 0.750 |
| Recall@5 / Recall@10 | 0.875 / 0.875 |
| Worst single-query failure | "murder" — absent from top 10 entirely as a bare keyword, despite the corpus containing the correct section and despite the in-session glossary fix measurably helping full-question phrasing |

**Two concrete, evidenced items carried into Phase 7/12**: (1) the
truncation-defect compounds directly with Phase 4's chunking defect for
`ppc-section-337` specifically — both issues point at the same chunk from
different angles; (2) bare/short-keyword queries for common offence names
are measurably weaker than full-sentence questions, which matters for
Phase 11's benchmark design (it should test both phrasing styles, not
just one).

---

**End of Phase 6.** No code was modified. Ollama was started (it was not
running) purely to make live embedding calls for this phase's tests —
no application code or corpus data was touched.

Stopping here per your instruction to review before proceeding to Phase 7
(Retrieval Evaluation).
