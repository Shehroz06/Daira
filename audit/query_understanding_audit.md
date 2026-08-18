# Phase 8 — Query Understanding / Preprocessing Audit

Status: **read-only audit, no code modified.** Every tokenization claim
below was produced by calling the actual live `_tokenize()` function and
the actual live `keyword_search()`, not inferred from reading the regex.

## 8.1 What preprocessing actually happens (confirmed by direct testing)

| Operation | BM25 path (`app/rag.py::_tokenize`) | Vector path | Query-understanding path (`legal_query.py`) |
|---|---|---|---|
| Lowercase | Yes | Opaque (delegated to Ollama/nomic-embed-text) | Yes (`.lower()` before substring checks) |
| Stemming | **No** | Opaque | No |
| Lemmatization | **No** | Opaque | No |
| Abbreviation expansion | **No** | Opaque, except the PPC title glossary (§8.4) | No |
| Spacing normalization | Implicit (regex splits on any non-alphanumeric) | Opaque | No |
| Punctuation removal | Yes — `[a-z0-9]+` treats all punctuation as a token boundary | Opaque | No |
| Stopword removal | **No** | Opaque | No |

The vector path's internal preprocessing is genuinely opaque from this
codebase (same acknowledged limitation as Phase 6 §6.1) — Ollama doesn't
expose it. Everything else in this table was confirmed directly.

## 8.2 Punctuation-as-boundary damages legal meaning — tested directly

Ran the actual tokenizer against the brief's query list plus two targeted
additions:

```
'Qatl'               -> ['qatl']
'Qatl-i-Amd'         -> ['qatl', 'i', 'amd']       <- compound term shredded
'qatl-e-amd'         -> ['qatl', 'e', 'amd']       <- same problem, other spelling
'337-A'              -> ['337', 'a']               <- loses the hyphenated structure
'Murder'             -> ['murder']
'Theft'              -> ['theft']
'Stealing'           -> ['stealing']
'Robbery'            -> ['robbery']
'Dacoity'            -> ['dacoity']
'Fraud'              -> ['fraud']
'Property'           -> ['property']
'Rights'              -> ['rights']
'Attempt'            -> ['attempt']
'Attempted murder'   -> ['attempted', 'murder']
'Murder punishment'  -> ['murder', 'punishment']
```

**"Qatl-i-Amd" is shredded into three separate tokens**, one of which —
`"i"` — is not a meaningful legal term at all; it's the byproduct of the
hyphenated Urdu/Arabic transliteration convention being split like English
punctuation. Checked whether this actually pollutes scoring, not just
whether it's theoretically possible:

```
document frequency of "i"    (out of 1268 docs): 114
document frequency of "amd"  (out of 1268 docs):  17
document frequency of "qatl" (out of 1268 docs):  29
```

114/1268 documents contain a standalone "i" token — common enough to
carry real (if modest) IDF weight in BM25, meaning any query containing a
hyphenated Qatl-* term is quietly also scoring against 114 unrelated
documents' use of the word "I" in ordinary prose. This is the **query-side
mirror of Phase 4's parser defect**: the same hyphenated-compound pattern
that causes `ingest_pdf.py`'s section-marker regex to fail on `"337-A."`
also causes the BM25 tokenizer to fail on the same compound structure at
query time. Two independent code paths, same blind spot.

## 8.3 No stemming — tested with the exact failure this predicts

**"stealing" vs. the corpus's own word "theft":**

```
BM25 for "stealing" (k=10): [('ppc-section-326', 10.29)]  <- only one hit, and it's wrong
```

Investigated the sole hit directly: `ppc-section-326` is **"Thug"**
(habitual association for robbery or *child-stealing*) — the word
"stealing" appears in the corpus exactly once, as part of the compound
"child-stealing," in a section about habitual criminal association, not
about theft itself. **A user typing the completely natural English word
"stealing" gets zero relevant results and one actively misleading one**,
purely because the corpus's own text says "theft" and there is no
mechanism connecting the two.

**"attempted" vs. the corpus's own word "attempt":**

```
BM25 for "attempted" (k=7): ppc-section-99, 388, 225, 353, 389, plc-148, 254
BM25 for "attempt"   (k=5): ppc-section-511, 391, 393, 325, 398
```

**Completely disjoint result sets.** Section 324 ("Attempt to commit
qatl-i-amd" — the section Symptom 3's original bug report specifically
named) does not appear in the top 7 for "attempted" at all, while "attempt"
(matching PPC's own phrasing convention, "Attempt to commit...") correctly
surfaces the Code's general attempt provision (511) and dacoity-attempt
sections. This is a direct, evidenced link between the missing-stemming
gap and the exact symptom category under investigation — "attempted
murder" is at least as natural a phrasing as "attempt murder" for a lay
user, and it retrieves an entirely different, wrong set of sections.

## 8.4 The one place abbreviation/synonym handling *does* exist

Confirmed again here (already established in Phase 6): the PPC ingestion
glossary (`scripts/ingest_pdf.py::SOURCE_CONFIGS["ppc"].glossary`)
appends English synonyms to 16 known Arabic/Urdu/Persian legal terms'
*titles* at ingestion time (qatl-i-amd→murder, qisas→retaliatory
punishment, etc.). This is a real, working mechanism — but it is
**one-directional and title-only**: it doesn't help the reverse case
(§8.3's "stealing"↔"theft," where the *corpus* term is already plain
English and it's the *query* that varies), and it doesn't touch body
text or query preprocessing at all. It's a narrow, source-specific patch,
not a general synonym-handling capability.

## 8.5 Remaining brief queries, checked for completeness

```
'Dacoity'            BM25 top3: ppc-396, ppc-399, ppc-395   -- correct, dacoity chapter
'Property'           BM25 top3: ppc-481, ppc-410, ppc-105   -- plausible, no single ground truth (Phase 6)
'Rights'             BM25 top3: plc-332, plc-334, plc-336   -- same weak result as Phase 7 §7.3
'Murder punishment'  BM25 top3: ppc-108, ppc-109, ppc-302   -- Section 302 present, but rank 3
```

**"Murder punishment" is a third, independent confirmation of Phase 7's
core finding.** Unlike Phase 7's two queries (situational, first-person
phrasing), this is a direct, keyword-style phrasing — the kind a user
searching rather than conversing might type — and *even here*, Section
302 is outranked by Sections 108 and 109 (Abettor / Punishment of
abetment), the same General Part pattern identified in Phase 7. This
rules out "it only happens with situational phrasing" as an explanation
— the General-Part-outranks-specific-offence pattern reproduces across at
least three distinct phrasing styles now (situational, negation-based,
and direct keyword).

## 8.6 Summary

| Question from the audit brief | Finding |
|---|---|
| Lowercase? | Yes, both BM25 and query-understanding heuristics |
| Stem/lemmatize? | No — confirmed to cause real, high-severity misses ("stealing", "attempted") |
| Expand abbreviations? | Only narrowly, for 16 PPC terms, title-only, one-directional (§8.4) |
| Normalize spacing? | Implicitly, via the tokenizer regex |
| Remove punctuation? | Yes — and this specifically damages hyphenated legal compounds (§8.2) |
| Does preprocessing damage legal meaning? | **Yes, demonstrated twice**: hyphenated terms shredded into noise tokens (§8.2), and missing stemming causes natural query phrasings to retrieve entirely wrong result sets (§8.3) |

Two new, precisely-evidenced findings this phase, both carried into Phase
12: (1) query-side tokenization has the exact same hyphenated-compound
blind spot as Phase 4's parser, independently confirmed with document-
frequency evidence of actual noise-token pollution; (2) the complete
absence of stemming is not a theoretical gap — it was shown to produce
disjoint, wrong result sets for two entirely natural English phrasings
("stealing," "attempted") of concepts the corpus already covers correctly
under their base forms.

---

**End of Phase 8.** No code was modified.

Stopping here per your instruction to review before proceeding to Phase 9
(Prompt Audit).
