"""Ingest a legal PDF into the Diara corpus, chunked by Section/Article.

Generalized from the original Constitution-only script: each source is a
SourceConfig describing its metadata (Act name, jurisdiction, domain, year,
numbering label...) plus any source-specific quirks (extra noise patterns,
a stop boundary, one-off known fixups). The extraction engine itself is
shared across all sources.

Sections are found as "markers" — lines starting with "N." (optionally
amendment-bracketed). Two conventions exist in the wild, and are handled
per-marker rather than globally, since some Acts (Pakistan Penal Code) mix
them and others (CrPC, Companies Act, Punjab Labour Code) use only one:

  - "dual":   a marginal heading line for N, followed later by a second
              N-numbered line that starts the real body (Constitution, PPC).
  - "single": title and body are on the same first line, split by the
              first ". " / ".— " / ".– " (CrPC, Companies Act, Punjab
              Labour Code).

If the marker immediately following N is *also* numbered N, that's the
"dual" case; otherwise "single". No per-source mode flag needed.

Two-step, on purpose — layout-based PDF text extraction is inherently lossy
(footnotes, amendment brackets, page headers bleed into the text), so this
never silently overwrites the corpus:

    1. Extract -> data/sources/extracted/<name>_extracted.json (for a human to skim)
    2. Merge    -> writes data/corpus/<shard>.json              (explicit --merge flag)

New sources are written to their own shard under data/corpus/ — never to
the base data/documents.json — so ingesting one more Act can never affect
anything that already works. See app/rag.py's module docstring for how
shards are loaded.

Run:
    python scripts/ingest_pdf.py <source_key>
    # skim data/sources/extracted/<name>_extracted.json, then:
    python scripts/ingest_pdf.py <source_key> --merge

Requires the `pdftotext` binary (poppler-utils) on PATH — no Python PDF
dependency needed.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CORPUS_DIR = DATA_DIR / "corpus"

MARKER_RE = re.compile(r"^\s*(?:\[\s*)*(\d{1,3}(?:-[A-Z]|[A-Z])?)\.\s*(.*)$")
TOC_LEADER_RE = re.compile(r"\.{3,}")
FOOTNOTE_PREFIX_RE = re.compile(
    r"^\s*(Subs\.|Ins\.|Omitted|New Article|New Section|Added by|Renumbered|"
    r"Corrected by|The words?|Cl\.\s|Sub-Article|Sub-Section|Substituted|Inserted)"
)
BARE_NUMBER_LINE_RE = re.compile(r"^\s*\d{1,3}\s*$")
BRACKET_CHARS_RE = re.compile(r"[\[\]]")
WHITESPACE_RE = re.compile(r"\s+")
# Splits a single-marker line's remainder into title / body-start.
COLON_SPLIT_RE = re.compile(r":\s*")
PERIOD_SPLIT_RE = re.compile(r"\.\s*[—–-]\s*|\.\s+")


# --------------------------------------------------------------------------
# Source configuration
# --------------------------------------------------------------------------

@dataclass
class SourceConfig:
    key: str
    pdf_path: str                    # relative to project root
    shard_name: str                  # -> data/corpus/{shard_name}.json
    id_prefix: str                   # e.g. "ppc-section"
    act_title: str                   # e.g. "Pakistan Penal Code, 1860"
    section_label: str               # "Section" | "Article" | "Rule"
    jurisdiction: str
    legal_domain: str
    year: int
    province_or_state: Optional[str] = None
    document_type: str = "statute"
    authority_level: str = "primary"
    status: str = "active"
    source_label: str = ""
    source_url: str = ""
    extra_noise_patterns: list[str] = field(default_factory=list)
    stop_patterns: list[str] = field(default_factory=list)
    fixups: list[Callable[[list[str], dict], None]] = field(default_factory=list)
    # Term -> common English equivalent, applied to the title (case-
    # insensitive whole-word match). Needed when a source uses vocabulary
    # a general-purpose embedding model doesn't strongly associate with
    # how an English-speaking user would actually ask the question — e.g.
    # PPC's "qatl-i-amd" (murder) barely embeds near "murder" at all, so a
    # "minimum punishment for murder" query never found it via either BM25
    # (zero token overlap) or vector search (cosine ~0.61, below several
    # unrelated sections). This only enriches the searchable title/text
    # surface — the authoritative body text is left exactly as extracted.
    glossary: dict[str, str] = field(default_factory=dict)
    # Legacy: the Constitution still writes into the base documents.json
    # rather than a shard (it was ingested before shards existed, and
    # re-migrating a working 300+ doc corpus isn't worth the risk).
    legacy_merge_into_base: bool = False


def _fix_article_25_25a_swap(lines: list[str], articles: dict[str, dict]) -> None:
    """Correct a known transposition in the Constitution PDF's marginal
    headings (Articles 25/25A print with swapped labels in this edition).
    Verified against the well-established public text of the Constitution.
    """
    try:
        body_start = next(
            i for i, l in enumerate(lines)
            if l.strip().startswith("25.") and "All citizens are equal" in l)
        heading2 = next(
            i for i, l in enumerate(lines)
            if l.strip().startswith("25.") and "Right to education" in l)
        next_article = next(
            i for i, l in enumerate(lines)
            if l.strip().startswith("26.") and "Non-discrimination" in l)
    except StopIteration:
        return

    def clean_join(ls: list[str]) -> str:
        text = " ".join(l for l in ls if l.strip())
        text = BRACKET_CHARS_RE.sub("", text)
        return WHITESPACE_RE.sub(" ", text).strip()

    art25_text = clean_join(lines[body_start:heading2]).replace("sex 1*.", "sex.")
    art25a_text = clean_join(lines[heading2 + 1:next_article])
    articles["25"] = {"number": "25", "title": "Equality of citizens", "text": art25_text}
    articles["25A"] = {"number": "25A", "title": "Right to education", "text": art25a_text}


SOURCE_CONFIGS: dict[str, SourceConfig] = {
    "constitution": SourceConfig(
        key="constitution",
        pdf_path="data/sources/pdfs/pakistan_constitution_1973.pdf",
        shard_name="constitution",  # unused: legacy_merge_into_base=True
        id_prefix="constitution-pk-article",
        act_title="Constitution of the Islamic Republic of Pakistan, 1973",
        section_label="Article",
        jurisdiction="Pakistan",
        legal_domain="constitutional_law",
        document_type="constitution",
        authority_level="constitutional",
        year=1973,
        source_label=("Constitution of the Islamic Republic of Pakistan, "
                       "National Assembly of Pakistan (Sixth Edition, as "
                       "modified up to 28th February 2012)"),
        stop_patterns=[r"^\s*(?:\[\s*)*FIRST\s+SCHEDULE\s*\]?\s*$"],
        fixups=[_fix_article_25_25a_swap],
        legacy_merge_into_base=True,
    ),
    "ppc": SourceConfig(
        key="ppc",
        pdf_path="data/sources/pdfs/02.-Pakistan-Penal-Code-XIV-of-1860.pdf",
        shard_name="ppc",
        id_prefix="ppc-section",
        act_title="Pakistan Penal Code, 1860",
        section_label="Section",
        jurisdiction="Pakistan",
        legal_domain="criminal_law",
        year=1860,
        source_label="Pakistan Penal Code (Act XLV of 1860), as amended",
        glossary={
            "qatl-e-amd": "murder", "qatl-i-amd": "murder",
            "qatl-i-khata": "unintentional killing", "qatl bis-sabab": "indirect homicide",
            "qatl-bis-sabab": "indirect homicide", "shibh-i-amd": "quasi-intentional killing",
            "qatl shibh-i-amd": "quasi-intentional killing",
            "qisas": "retaliatory punishment", "diyat": "compensation / blood money",
            "ta'zir": "discretionary punishment", "tazir": "discretionary punishment",
            "hadd": "fixed mandatory punishment", "hudood": "fixed mandatory punishment",
            "zina-bil-jabr": "rape", "zina": "unlawful sexual intercourse",
            "qazf": "false accusation of zina", "wali": "legal heir",
        },
    ),
    "crpc": SourceConfig(
        key="crpc",
        pdf_path="data/sources/pdfs/01.-Code-of-Criminal-Procedure-1898-Amended-by-Act-II-of-1997.pdf",
        shard_name="crpc",
        id_prefix="crpc-section",
        act_title="Code of Criminal Procedure, 1898",
        section_label="Section",
        jurisdiction="Pakistan",
        legal_domain="criminal_law",
        year=1898,
        source_label="The Code of Criminal Procedure, 1898, as amended by Act II of 1997",
        stop_patterns=[r"^\s*SCHEDULE\s*\d*\s*$"],
    ),
    "punjab_labour_code": SourceConfig(
        key="punjab_labour_code",
        pdf_path="data/sources/pdfs/labor-law-in punjab.pdf",
        shard_name="punjab_labour_code_2026",
        id_prefix="punjab-labour-code-section",
        act_title="The Punjab Labour Code, 2026",
        section_label="Section",
        jurisdiction="Pakistan",
        province_or_state="Punjab",
        legal_domain="employment",
        year=2026,
        source_label="The Punjab Labour Code, 2026 (Act IX of 2026)",
    ),
    "companies_act": SourceConfig(
        key="companies_act",
        pdf_path="data/sources/pdfs/The-Company-Act-2017-updated-18.8.2022.pdf",
        shard_name="companies_act_2017",
        id_prefix="companies-act-section",
        act_title="The Companies Act, 2017",
        section_label="Section",
        jurisdiction="Pakistan",
        legal_domain="company_law",
        year=2017,
        source_label="The Companies Act, 2017, as updated 18.8.2022",
    ),
}


# --------------------------------------------------------------------------
# Extraction engine (source-agnostic)
# --------------------------------------------------------------------------

def extract_text(pdf_path: Path) -> str:
    result = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        capture_output=True, text=True, check=True,
    )
    return result.stdout


def clean_lines(raw_text: str, extra_noise_patterns: list[str]) -> list[str]:
    """Drop table-of-contents lines, footnote text, and any source-specific noise."""
    extra_res = [re.compile(p, re.IGNORECASE) for p in extra_noise_patterns]
    lines = []
    for line in raw_text.split("\n"):
        if not line.strip():
            lines.append("")
            continue
        if TOC_LEADER_RE.search(line):
            continue
        if BARE_NUMBER_LINE_RE.match(line):
            continue
        if FOOTNOTE_PREFIX_RE.match(line):
            continue
        if any(r.match(line) for r in extra_res):
            continue
        lines.append(line)
    return lines


def find_stop_boundary(lines: list[str], stop_patterns: list[str]) -> int:
    """First line matching any stop pattern — schedules/appendices that
    reuse "N." numbering for unrelated lists aren't Sections/Articles."""
    if not stop_patterns:
        return len(lines)
    stop_res = [re.compile(p, re.IGNORECASE) for p in stop_patterns]
    for i, line in enumerate(lines):
        if any(r.match(line) for r in stop_res):
            return i
    return len(lines)


def split_title_body(rest: str) -> tuple[str, str]:
    """Single-marker mode: split "Title.— body..." or '"Term": body...'
    into (title, body_start).

    An early colon is preferred over the first period: definition-style
    entries ('"Special law": A special law is...') use a colon, and titles
    can themselves contain a period inside an abbreviation ('Definition of
    "Queen": [Omitted by A. O., 1961...') which would otherwise cause a
    naive first-period split to cut the title short.
    """
    colon_m = COLON_SPLIT_RE.search(rest[:100])
    if colon_m:
        return rest[:colon_m.start()].strip(), rest[colon_m.end():].strip()
    period_m = PERIOD_SPLIT_RE.search(rest)
    if not period_m:
        return rest.strip(), ""
    return rest[:period_m.start()].strip(), rest[period_m.end():].strip()


def parse_sections(lines: list[str], stop_patterns: list[str]) -> dict[str, dict]:
    """Pair markers into sections, deciding dual- vs single-marker mode
    independently for each one (see module docstring)."""
    end = find_stop_boundary(lines, stop_patterns)
    lines = lines[:end]

    markers: list[tuple[int, str, str]] = []
    for i, line in enumerate(lines):
        m = MARKER_RE.match(line)
        if m:
            markers.append((i, m.group(1), m.group(2)))

    sections: dict[str, dict] = {}
    k = 0
    while k < len(markers):
        idx, number, rest = markers[k]

        if k + 1 < len(markers) and markers[k + 1][1] == number:
            # Dual-marker: this line is a heading; the next same-numbered
            # marker starts the real body.
            title = WHITESPACE_RE.sub(" ", rest).strip()
            body_start_idx = markers[k + 1][0]
            body_end_idx = markers[k + 2][0] if k + 2 < len(markers) else len(lines)
            body_lines = lines[body_start_idx:body_end_idx]
            text = " ".join(l for l in body_lines if l.strip())
            k += 2
        else:
            # Single-marker: title and body-start share this line; body
            # continues until the next marker of any number.
            title, body_first = split_title_body(rest)
            next_idx = markers[k + 1][0] if k + 1 < len(markers) else len(lines)
            body_lines = ([body_first] if body_first else []) + lines[idx + 1:next_idx]
            text = " ".join(l for l in body_lines if l.strip())
            k += 1

        text = BRACKET_CHARS_RE.sub("", text)
        text = WHITESPACE_RE.sub(" ", text).strip()
        if text and title:
            # Source PDFs are sometimes inconsistent about capitalizing a
            # title between its heading and body occurrences — normalize
            # rather than let it depend on which occurrence won.
            if title[0].isalpha():
                title = title[0].upper() + title[1:]
            existing = sections.get(number)
            if existing is None or len(text) > len(existing["text"]):
                sections[number] = {"number": number, "title": title, "text": text}

    return sections


def apply_glossary(title: str, glossary: dict[str, str]) -> str:
    """Append common English equivalents for any glossary terms found in the
    title, so BM25 and embeddings can find the section via the term a user
    would actually type. Longest terms first, so "qatl-i-amd" matches before
    a shorter substring would. Body text is left untouched — this only
    widens the searchable surface, it doesn't alter the authoritative text.
    """
    found = []
    lower_title = title.lower()
    for term in sorted(glossary, key=len, reverse=True):
        if term in lower_title:
            synonym = glossary[term]
            if synonym not in found:
                found.append(synonym)
    if not found:
        return title
    return f"{title} [{', '.join(found)}]"


def build_doc(section: dict, cfg: SourceConfig) -> dict:
    number = section["number"]
    title = apply_glossary(section["title"], cfg.glossary) if cfg.glossary else section["title"]
    return {
        "id": f"{cfg.id_prefix}-{number.lower()}",
        "title": f"{cfg.act_title} — {cfg.section_label} {number} ({title})",
        "text": section["text"],
        "jurisdiction": cfg.jurisdiction,
        "province_or_state": cfg.province_or_state,
        "legal_domain": cfg.legal_domain,
        "document_type": cfg.document_type,
        "authority_level": cfg.authority_level,
        "year": cfg.year,
        "status": cfg.status,
        "source": cfg.source_label,
        "source_url": cfg.source_url,
        "section": f"{cfg.section_label} {number}",
        "subsection": None,
        "parent_document": cfg.act_title,
        "effective_date": None,
        "effective_until": None,
        "last_verified": None,
    }


def merge_into_base(docs: list[dict]) -> None:
    """Legacy path — the Constitution only; upserts into data/documents.json."""
    docs_path = DATA_DIR / "documents.json"
    existing = json.loads(docs_path.read_text(encoding="utf-8"))
    by_id = {d["id"]: d for d in existing}
    added, replaced = 0, 0
    for doc in docs:
        if doc["id"] in by_id:
            replaced += 1
        else:
            added += 1
        by_id[doc["id"]] = doc
    merged = list(by_id.values())
    docs_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Merged into {docs_path}: {added} added, {replaced} replaced "
          f"({len(merged)} total documents).")
    print("Note: data/embeddings.npy is now stale for the new/changed chunks — "
          "re-run scripts/build_index.py before serving.")


def write_shard(docs: list[dict], shard_name: str) -> None:
    """New path — every source other than the legacy Constitution. Writes
    (or overwrites) exactly one shard file; never touches documents.json
    or any other shard."""
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    shard_path = CORPUS_DIR / f"{shard_name}.json"
    shard_path.write_text(json.dumps(docs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote shard {shard_path}: {len(docs)} documents.")
    print(f"Note: {shard_name}.embeddings.npy doesn't exist yet for this shard — "
          "vector search will fall back to BM25-only for it until you run "
          "scripts/build_index.py.")


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in SOURCE_CONFIGS:
        print("Usage: python scripts/ingest_pdf.py <source_key> [--merge]")
        print(f"Known source keys: {', '.join(sorted(SOURCE_CONFIGS))}")
        sys.exit(1)

    cfg = SOURCE_CONFIGS[sys.argv[1]]
    do_merge = "--merge" in sys.argv[2:]
    pdf_path = ROOT / cfg.pdf_path
    if not pdf_path.exists():
        print(f"Not found: {pdf_path}")
        sys.exit(1)

    raw = extract_text(pdf_path)
    lines = clean_lines(raw, cfg.extra_noise_patterns)
    sections = parse_sections(lines, cfg.stop_patterns)
    for fixup in cfg.fixups:
        fixup(lines, sections)

    if not sections:
        print("No sections extracted — check the PDF structure against "
              "MARKER_RE / split_title_body() in this script.")
        sys.exit(1)

    ordered = sorted(sections.values(), key=lambda a: (
        int(re.match(r"\d+", a["number"]).group()), a["number"]))

    extracted_dir = DATA_DIR / "sources" / "extracted"
    extracted_dir.mkdir(parents=True, exist_ok=True)
    extracted_path = extracted_dir / f"{cfg.key}_extracted.json"
    extracted_path.write_text(
        json.dumps(ordered, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Extracted {len(ordered)} sections -> {extracted_path}")
    print("Spot-check a few entries against the official text before merging.")

    if do_merge:
        docs = [build_doc(s, cfg) for s in ordered]
        if cfg.legacy_merge_into_base:
            merge_into_base(docs)
        else:
            write_shard(docs, cfg.shard_name)


if __name__ == "__main__":
    main()
