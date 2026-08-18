# Phase 9 — Prompt Audit

Status: **read-only audit, no code modified.** Rather than reviewing
`LEGAL_SYSTEM_PROMPT`'s text alone (already inventoried in Phase 1), this
phase ran real generation calls through the live pipeline against exactly
the failure cases Phase 7 already characterized, and verified every claim
against the actual retrieved source text — not against what the answer
merely *sounded like* it was doing.

## 9.1 Method

Three live test cases, each captured with the actual retrieved sources
(`meta.sources`) alongside the generated answer, then cross-checked:

1. Every section number the model *cites in prose* against what was
   *actually retrieved* (hallucinated-citation check).
2. Every non-trivial legal term/fact the model *states* against the
   *literal retrieved text* (fabricated-content check).
3. Whether the model's treatment of source *sufficiency* is consistent.

## 9.2 Test 1 — known-bad retrieval (Phase 7's murder query)

Query: `"I did a murder what happens to me?"` — Phase 7 already proved
retrieval hands the model PPC's General Part (co-operation, justification,
abetment) instead of Section 302.

**Retrieved**: `ppc-section-37, 79, 108, 38, 254`

**Generated answer** (verbatim): *"Under the Pakistan Penal Code, anyone
who intentionally co-operates in the commission of a murder... can be
held criminally liable... Whether your actions constitute full murder, an
attempt, or a different related offense (such as culpable homicide)
depends entirely on your specific intent, whether you acted under grave
provocation..."*

**Citation check**: all four sections named in the "Sources:" line (37,
79, 108, 38) exactly match what was retrieved. **No hallucinated
citation.**

**Fact-grounding check**: the terms "culpable homicide" and "grave
provocation" don't appear in three of the five retrieved sections — but
checked directly against all five, and **`ppc-section-38`'s own text does
contain both phrases** (in its illustrative examples). Confirmed: **not
fabricated** — the model correctly sourced this language from within the
provided context rather than injecting outside training knowledge.

**The actual defect here is neither hallucination nor fabrication — it's
over-generalization.** The model had no source stating murder's actual
punishment, and instead of clearly saying so, it constructed a fluent,
confident-sounding answer entirely out of *general* criminal-liability
language, without ever flagging that none of its sources define what
happens for murder specifically (as distinct from criminal acts
generally). A user reading this answer would reasonably believe they've
been told something substantive about murder consequences; they have not.

## 9.3 Test 2 — genuinely insufficient sources (contrast case)

Query: `"What is the bail eligibility for a crime in Pakistan?"` — Phase
6 already established no CrPC content exists in the corpus.

**Retrieved**: `ppc-section-213, 205, 65, 254, 67` (all mention "bail" only
as an incidental procedural aside within unrelated specific offences).

**Generated answer**: *"The retrieved legal sources do not contain
provisions regarding general bail eligibility... The sources only mention
'bail' in the context of criminal penalties for false personation
(Section 205)... Because the sources are insufficient..."*

**This is the correct behavior** — honest, specific about *why* the
sources fall short, no invented bail rules. Directly contradicts Test 1's
outcome on the "sufficiency" question.

## 9.4 Why Test 1 and Test 2 differ — an evidenced hypothesis, not a guess

The two cases differ in one measurable way: Test 2's retrieved sections
are about *unrelated specific offences* (false personation, etc.) that
happen to mention the word "bail" in passing — an obvious mismatch even
on casual reading. Test 1's retrieved sections are *general criminal-
liability principles* that are topically adjacent to any criminal
question, including murder — genuinely harder to distinguish from "the
answer" without already knowing the corpus lacks the offence-specific
provision. **The model's sufficiency judgment tracks surface topical
similarity, not whether the specific question asked is actually
answered** — which is consistent with, and plausibly explained by,
Phase 7's finding that nothing in the retrieval or ranking layer
distinguishes "general provision" from "offence-specific provision" in
the first place. The prompt doesn't currently instruct the model to check
for that distinction explicitly.

## 9.5 Test 3 — control case, and a citation-accuracy nuance

Query: `"What is the punishment for theft in Pakistan?"` (retrieval
succeeds cleanly per Phase 7 §7.2).

**Retrieved**: `ppc-section-379, 380, 381, 382, 439`

The generated answer is accurate, well-organized by aggravating
circumstance, and cites "Section 381-A" alongside 381. A naive citation
checker would flag this as hallucinated — `ppc-section-381-a` does not
exist as a document id anywhere in the corpus. **Investigated directly**:
Section 381's *retrieved* full text literally contains `"381-A. Theft of
a car or other motor vehicles..."` — the hyphenated sub-section (same
`ingest_pdf.py` parser gap identified in Phase 4) is merged into 381's
chunk rather than existing separately. **The citation is not
hallucinated** — the model correctly read and attributed content that the
chunking defect had already folded into a different section's chunk. This
is genuinely reassuring evidence of grounding discipline, and simultaneously
sharpens Phase 4/5's findings: the *system* has no clean way to represent
"Section 381-A" as its own citable unit, even though the *model* handles
the merged content correctly. Every other citation in this answer (379,
380, 382, 439) matches the retrieved set exactly. **Zero hallucinated
citations across all three tests.**

## 9.6 Summary

| Audit brief question | Finding, with evidence |
|---|---|
| Does the LLM hallucinate? | **No fabricated facts found** in 3 tests — the one apparent case ("culpable homicide") was verified present in the actual retrieved text |
| Does it hallucinate citations? | **No** — every cited section across all 3 tests matches the retrieved set exactly, including one case (381-A) that required checking merged-chunk content directly to confirm |
| Does it ignore retrieval? | No — stays within retrieved content in every test, including the over-generalized one |
| Does it over-generalize? | **Yes, demonstrated concretely** (Test 1) — synthesizes a confident-sounding topic-specific answer from only general-principle sources, without flagging the gap |
| Does it answer despite missing evidence? | **Inconsistently** — correctly refuses when sources are obviously unrelated (Test 2), but not when sources are topically adjacent but still non-specific (Test 1) |

**This phase's central finding**: the prompt's core grounding discipline
(no fabrication, accurate citation) holds up under direct verification,
including a nuanced case that required checking actual source text rather
than trusting either the answer or a naive citation-string check. The
real gap is judgment-level, not fabrication-level: `LEGAL_SYSTEM_PROMPT`
currently asks the model to judge whether sources are "insufficient" as
a single binary check, with no explicit instruction to distinguish
*"this source is on-topic"* from *"this source actually answers the
specific question asked."* Phase 7 already showed retrieval itself
struggles with that same distinction — this phase shows the prompt
doesn't compensate for it either. A concrete, low-risk prompt addition
(explicitly instructing the model to check whether retrieved sources
state the *specific* fact asked for, not just a related general
principle, before treating them as sufficient) is a candidate for Phase
12 — not implemented here, since Phase 9's rule is to audit before
touching prompts.

---

**End of Phase 9.** No code was modified — three live generation calls
were made for evidence-gathering only.

Stopping here per your instruction to review before proceeding to Phase 10
(Citation Audit).
