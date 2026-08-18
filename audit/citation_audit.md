# Phase 10 — Citation Audit

Status: **read-only audit, no code modified.** Builds directly on Phase
9's per-test citation checks, extended here to a systematic corpus-wide
collision scan plus two deliberately constructed stress tests (not left
to chance whether a natural query would happen to trigger them).

## 10.1 Section-number collisions across different Acts — quantified

Checked every document's bare section/article number against every other
document's, across all three live sources, for numbers that exist under
more than one Act:

```
Section numbers appearing in more than one Act: 433
```

Examples: "Section 5" alone exists in the Pakistan Penal Code, the Punjab
Labour Code, the Payment of Wages Act, the Punjab Rented Premises Act, and
Article 5 of the Constitution — five different, unrelated provisions
sharing one bare number. This is expected in any multi-Act corpus (each
Act numbers its own sections starting from 1), but it means **a bare
citation like "Section 5" is inherently ambiguous without its Act name
attached** — a real, quantified risk surface for citation errors if the
Act name is ever dropped.

## 10.2 Does this collision risk actually produce wrong-act citations? Tested directly, not assumed

Three natural queries were tried first, none happened to retrieve
colliding section numbers together (reported for completeness — this
alone doesn't prove the risk is unrealized, just that these three queries
didn't exercise it). So a collision was **deliberately constructed**:
built a source set from `ppc-section-5`, `punjab-labour-code-section-5`,
and `constitution-pk-article-5` — a genuine 3-way "Section 5" collision —
and ran it through the real generation pipeline with the question
*"Summarize what Section 5 says."*

**Result**: the model opened by explicitly naming the ambiguity
("Because 'Section 5' appears in multiple legal texts, the content
depends on which law you are referencing"), then correctly attributed
each fact to its correct Act throughout the prose — including correctly
using **"Article 5"** for the Constitution and **"Section 5"** for the two
statutes, matching each document's own correct citation convention rather
than treating them interchangeably. The final `Sources:` line listed all
three with full Act name and correct label. **No cross-act
misattribution.**

This substantially de-risks §10.1's raw collision count in practice — the
underlying data has widespread numbering collisions, but `format_source()`
supplying the full document title (which always includes the Act name) in
every retrieved source's context, combined with the system prompt's
instruction to cite "title + section," appears to reliably prevent the
model from collapsing multiple Acts' same-numbered sections into an
ambiguous bare citation. Verified with a real, deliberately adversarial
test case, not inferred from reading the prompt text.

## 10.3 Subsection/paragraph-level citation — an architectural ceiling, tested for honesty

Phase 3/5 already established that no document in the corpus has its
`subsection` field populated (chunking is always whole-section). This
phase tested the practical consequence directly: asked *"What does clause
(c) of Section 302 say specifically?"*, supplying only the (unavoidably
whole-section) `ppc-section-302` chunk as context.

**Result**: the model correctly located and answered from clause (c)
specifically (the 25-year alternative-to-qisas provision) — reading it
out of the full section body, which does contain the internal (a)/(b)/(c)
structure as plain text even though it isn't represented as separate
metadata. Critically, **it cited only "Section 302"** — it did not
fabricate a more specific "Section 302(c)" citation that the metadata
doesn't actually support.

**This is the correct, honest behavior given the architecture's real
limit**: the system cannot offer subsection-level *citations* (that
granularity doesn't exist as a citable unit anywhere in the corpus), but
it does not paper over that limit by inventing false precision — it
answers accurately at the content level while citing accurately at the
(coarser) level the data actually supports. The gap is a **citation
precision ceiling**, not a citation accuracy defect.

## 10.4 Cross-check against Phase 9's findings

Combining this phase's two new tests with Phase 9's three: **5 live
generation tests total, 0 hallucinated citations, 0 wrong-act
attributions, 0 fabricated subsection references.** One case (Phase 9's
"Section 381-A") required checking merged-chunk content directly to
confirm it wasn't hallucinated; every other citation was a direct,
unambiguous match to a retrieved document.

## 10.5 Summary

| Audit brief question | Finding |
|---|---|
| Citations point to the correct section? | Yes, in every test run across Phases 9–10 |
| Citations point to the correct Act? | Yes, including under a deliberately constructed 3-way same-number collision — verified, not assumed |
| Citations point to the correct subsection/paragraph? | **Not applicable — this granularity doesn't exist in the corpus at all** (Phase 3/5). The model correctly avoids fabricating it rather than getting it "wrong" |
| Are citations ever fabricated? | **No fabricated citations found** in 5 live tests across two phases |
| Is the 433-collision risk realized in practice? | Tested directly with an adversarial case — **not realized**, full-title context appears to reliably prevent it |

**Overall**: citation *accuracy* is solid, verified by direct adversarial
testing rather than by trusting the prompt's instructions alone. The
limiting factor is citation *granularity* — inherited directly from
Phase 4's chunking-strategy finding (whole-section chunks only) and
Phase 5's metadata finding (`subsection` never populated) — not citation
correctness. No new defect discovered this phase; this phase's
contribution is confirming, with direct evidence, that the citation
*mechanism* built on top of that limited granularity behaves honestly
rather than compounding the limitation with fabrication.

---

**End of Phase 10.** No code was modified — two live generation calls were
made for evidence-gathering only (one deliberately adversarial collision
test, one subsection-granularity test).

Stopping here per your instruction to review before proceeding to Phase 11
(the 100+ query benchmark).
