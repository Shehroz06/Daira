# Phase 7 — Retrieval Evaluation (the four reported symptoms, with evidence)

Status: **read-only audit, no code modified.** Every symptom below was
re-run against the live pipeline just now — not assumed to still reproduce
from the original bug report. The corpus has changed substantially since
that report (PPC and the Punjab Labour Code were ingested, a title
glossary fix and a conversation-context-isolation fix were both applied,
earlier in this session) — so the first job of this phase was determining
which symptoms are still live at all.

## 7.1 Method

For each symptom, ran the exact reported query through
`legal_query.understand()` → `rag.index.retrieve()`, capturing every
intermediate signal: detected domain/jurisdiction, the full (not
top-8-truncated) vector and BM25 rankings, RRF fusion, threshold survival,
and final authority-ranked output. Where a "correct" document was
expected but absent from the visible results, its exact rank and score on
*every* channel was looked up directly — never inferred.

## 7.2 Symptom 1 — "What is the punishment of theft?"

**Originally reported**: "no sources" / insufficient-information response.
**Re-tested now**: **this symptom no longer reproduces.**

```
legal_domain detected: criminal_law (correct)
final_ranking:
  1. ppc-section-379  (Punishment for theft)      score=1.7481
  2. ppc-section-382  (Theft after preparation...) score=1.7481
  3. ppc-section-378  (Theft)                      score=1.6818
  4. ppc-section-439  (Punishment for intention...) score=1.6808
  5. ppc-section-390  (Robbery)                     score=1.6734
```

The correct section (379) is rank 1. **Root cause of the original
symptom**: at the time it was reported, PPC was not yet in the corpus at
all (Phase 1/2 confirm PPC was ingested during this session) — "no
sources" was the system correctly and honestly reporting that no theft
provision existed anywhere in the index, which was true at the time. This
was a **corpus-coverage gap, not a retrieval-logic defect**, and it's been
closed by the ingestion work already done this session. No further action
needed for this specific symptom.

## 7.3 Symptom 2 — "What are my rights?"

**Originally reported**: retrieved "Punishment of theft" (a specific,
unrelated result presented with unwarranted confidence).
**Re-tested now**: does not retrieve theft — but is still qualitatively
broken in the way the brief's "Expected" behavior describes.

```
legal_domain detected: None (correctly — no domain keyword in this query)
final_ranking:
  1. punjab-labour-code-section-334  score=1.7384
     "Civil courts to have no jurisdiction in relation to rights disputes"
  2. constitution-pk-article-7        score=1.7235
     "Definition of the State"
  3. punjab-labour-code-section-336  score=1.6899
     "Reference of rights dispute to a mediator"
```

Investigated each result directly: none of them answer "what are my
rights" in any way a lay user would recognize. They matched purely on the
literal token "rights" (Labour Code's narrow "rights dispute" grievance
machinery) or generic constitutional vocabulary ("the State"). **This
confirms the specific manifestation reported (theft) doesn't currently
reproduce, but the underlying category of failure is still present and
is architecturally distinct from Symptoms 1/3/4**: this is not a case of
a correct document being outranked — there is no single correct document
for this query at all. `legal_domain: None` is the *correct* detection
(the question genuinely doesn't specify a domain), but the current system
has no mechanism to act on "domain is unknown and the question is
too broad to answer safely" the way it already does have a mechanism for
"jurisdiction is unknown" (`app/daira.py`'s jurisdiction gate). This is a
**query-understanding / dialogue-design gap** (Phase 8/9 territory), not
a scoring or index defect. Carried into Phase 12 as an architecture
recommendation (an ambiguity gate, symmetric to the existing jurisdiction
gate), not fixed here.

## 7.4 Symptom 3 — "I did a murder what happens to me?"

**Originally reported**: retrieved Section 324 (Attempt to murder).
**Re-tested now**: retrieves different wrong sections (37, 79, 108) —
**the specific wrong answer changed, but the failure itself is still
fully reproducible and was traced to its exact numeric cause.**

```
legal_domain detected: criminal_law (correct)
final_ranking:
  1. ppc-section-37   score=1.7481   "Co-operation by doing one of several acts constituting an offence"
  2. ppc-section-79   score=1.6818   "Act done by a person justified... by mistake of fact..."
  3. ppc-section-108  score=1.6417   "Abettor" (general definition)
  4. ppc-section-38   score=1.2604   "Persons concerned in criminal act may be guilty of different offences"
  5. ppc-section-254  score=1.2604   (unrelated — currency-related offence)
```

Section 302 (the correct murder provision) is **absent from this list
entirely.** Looked up its exact position on every channel, unrestricted:

```
Section 302 — full-corpus vector rank: 35 (score 0.545)
Section 302 — full-corpus BM25 rank:    9 (score 8.03)
```

Both channels retrieve only their top **12** candidates before fusion
(`VECTOR_K=12`, `KEYWORD_K=12` — confirmed in Phase 1). Section 302 misses
*both* cutoffs, so it is never in the candidate pool `authority_rank()`
even sees — the ranking stage can't rescue a document it's never handed.

**Then tested the deeper question: even if it had survived the cutoff,
would it actually win?** Manually inserted Section 302 into the candidate
pool with its true (lower) fused RRF score and re-ran the real
`authority_rank()` function on it:

```
Hypothetical rank of Section 302, if allowed into the pool: #4 of 22
  1. ppc-section-37   1.7481
  2. ppc-section-79   1.6818
  3. ppc-section-108  1.6417
  4. ppc-section-302  1.5299   <- still loses to 3 general provisions
  5. ppc-section-38   1.2604
```

**It still loses.** This rules out "the K cutoff is simply too small" as
the complete explanation and identifies the real mechanism: Sections 37,
79, and 108 are PPC's **General Part** (Chapters II–V: General
Explanations, General Exceptions, Abetment) — provisions that use generic
liability language ("whoever... commits an offence," "guilty of," "act
done by a person") applicable to *every* crime in the Code by design.
Section 302 uses the Code's own specific technical vocabulary
(qatl-i-amd, qisas, ta'zir). A lay description of a situation
("I did X, what happens to me") lexically and semantically resembles the
generic liability language of the General Part far more than it resembles
any specific offence's technical text — on *both* BM25 (generic English
words like "offence," "act," "person" are common across the whole
General Part) and vector similarity (§6.4 already established that
general "criminal liability" framing embeds strongly, independent of the
specific offence named).

`authority_rank()`'s non-retrieval signals (jurisdiction 0.30, domain
0.15, status 0.20, date 0.10) provide **zero differentiation** here — all
of sections 37, 79, 108, and 302 share the identical jurisdiction
(Pakistan), domain (criminal_law), and near-identical status/date
profile. There is no signal anywhere in the current pipeline that
distinguishes "a section that defines a specific offence" from "a
section that states a general principle applicable to all offences."
This is the same gap Phase 5 flagged architecturally (no `offence` or
structured provision-type field) — this phase now proves it has a real,
measurable retrieval consequence, not just a theoretical one.

## 7.5 Symptom 4 — "Not attempt, completed murder."

**Originally reported**: retrieved Section 396 (Dacoity with Murder).
**Re-tested now**: same failure mechanism as §7.4, confirmed with the
same method.

```
legal_domain detected: criminal_law (correct)
final_ranking:
  1. ppc-section-38   score=1.7481   (general — "persons concerned in criminal act")
  2. ppc-section-37   score=1.7481   (general — "co-operation... constituting an offence")
  3. ppc-section-36   score=1.7463   (general — related "several acts" provision)
  4. ppc-section-396  score=1.7285   Dacoity with Murder — matches the original report
  5. ppc-section-324  score=1.7102   Attempt to commit qatl-i-amd
```

Section 302's exact position:

```
Section 302 — full-corpus vector rank: 44 (score 0.557)
Section 302 — full-corpus BM25 rank:   19 (score 5.64)
```

Both again outside the k=12 cutoffs. Hypothetical re-insertion (same
method as §7.4): Section 302 would rank **#7 of 19** even if included —
losing not only to the same three General Part sections as §7.4, but
also to Sections 396 (Dacoity with Murder) and 324 (Attempt), both of
which are *closer* topical relatives of murder than the General Part
sections are, but still not the actual answer to "completed murder."
This confirms §7.4's root cause generalizes across phrasing — it isn't
specific to one query's wording.

## 7.6 Cross-symptom pattern

| Symptom | Domain detection | Root cause category | Fixed by intervening session work? |
|---|---|---|---|
| 1. Theft | Correct | Corpus-coverage gap (PPC not yet ingested) | **Yes — resolved** |
| 2. "What are my rights?" | Correctly `None` | Missing ambiguity-clarification mechanism (query understanding / dialogue gap) | No — still open |
| 3. "I did a murder..." | Correct | K-cutoff exclusion **and** missing offence-specificity ranking signal | No — still open, precisely diagnosed |
| 4. "Not attempt, completed murder." | Correct | Same as #3 | No — still open, same diagnosis |

Symptoms 3 and 4 share one root cause, evidenced at the numeric level, not
inferred: **General Part / procedural PPC sections systematically
outrank specific offence-definition sections for lay-phrased situational
queries, on both retrieval channels independently, and the authority
ranking stage has no signal capable of correcting this even when given
the chance.** This is the most concrete, actionable, and highest-priority
finding of the entire audit. Symptom 2 is a related but architecturally
different problem (no correct target exists at all vs. the correct target
being outranked) and needs a different kind of fix (a clarification gate,
not a ranking fix).

## 7.7 What this phase does *not* yet prove

This phase used four hand-picked queries chosen because they were
reported as broken. It does not establish how common the General-Part-
outranks-specific-offence pattern is across the corpus, nor whether fixing
it would regress any currently-working query. Both questions are exactly
what Phase 11's 100-query benchmark is for — this phase provides the
mechanism, Phase 11 provides the scale.

---

**End of Phase 7.** No code was modified.

Stopping here per your instruction to review before proceeding to Phase 8
(Query Understanding / Preprocessing Audit).
