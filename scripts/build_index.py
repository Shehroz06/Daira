"""Build the Diara embeddings index.

Embeds every corpus file — the base data/documents.json plus every shard
under data/corpus/ — with the local Ollama embedding model, L2-normalizes,
and writes each one's own <name>.embeddings.npy next to it. See app/rag.py's
module docstring for how the base + shards are loaded together at runtime.

Incremental by default: a target is skipped if its embeddings file already
exists and has the right row count. This matters in practice — embedding
this project's original 324-chunk corpus took about 2 hours on typical
CPU-only Ollama hardware, so re-embedding everything on every new Act would
make ingestion increasingly expensive over time. Pass --force to re-embed
everything anyway (e.g. after editing existing chunk text).

Run:
    python scripts/build_index.py            # embed whatever's new/changed
    python scripts/build_index.py --force     # re-embed everything
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

# Allow importing project modules when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.llm import OLLAMA_EMBED_MODEL, ollama_embed  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
BATCH_SIZE = 16


def canonical_text(d: dict) -> str:
    """The text that gets embedded: title + section context + body."""
    parts = [d.get("title") or ""]
    if d.get("section"):
        parts.append(f"Section {d['section']}")
    if d.get("subsection"):
        parts.append(f"Subsection {d['subsection']}")
    parts.append(d.get("text") or "")
    return "\n".join(p for p in parts if p)


def embed_path_for(docs_path: Path) -> Path:
    if docs_path == DATA_DIR / "documents.json":
        return DATA_DIR / "embeddings.npy"  # legacy name, predates shards
    return docs_path.with_suffix("").with_suffix(".embeddings.npy")


def meta_path_for(docs_path: Path) -> Path:
    if docs_path == DATA_DIR / "documents.json":
        return DATA_DIR / "index_meta.json"  # legacy name, predates shards
    return docs_path.with_suffix("").with_suffix(".index_meta.json")


def targets() -> list[Path]:
    """Every corpus file to consider embedding: the base file, then every
    shard under data/corpus/, in the same order app/rag.py loads them.
    Excludes the *.index_meta.json sidecar this script itself writes —
    that's metadata, not a corpus shard."""
    result = [DATA_DIR / "documents.json"]
    corpus_dir = DATA_DIR / "corpus"
    if corpus_dir.is_dir():
        result.extend(
            p for p in sorted(corpus_dir.glob("*.json"))
            if not p.name.endswith(".index_meta.json")
        )
    return result


def is_up_to_date(docs_path: Path, docs: list[dict]) -> bool:
    embed_path = embed_path_for(docs_path)
    if not embed_path.exists():
        return False
    try:
        arr = np.load(embed_path)
    except (OSError, ValueError):
        return False
    return arr.ndim == 2 and arr.shape[0] == len(docs)


def embed_one(docs_path: Path, docs: list[dict]) -> None:
    texts = [canonical_text(d) for d in docs]
    print(f"Embedding {docs_path.name}: {len(texts)} chunks with '{OLLAMA_EMBED_MODEL}'...")

    t0 = time.time()
    vectors: list[list[float]] = []
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i:i + BATCH_SIZE]
        vectors.extend(ollama_embed(batch))
        print(f"  {min(i + BATCH_SIZE, len(texts))}/{len(texts)}")

    arr = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    arr = arr / norms

    embed_path = embed_path_for(docs_path)
    np.save(embed_path, arr)
    meta = {
        "embed_model": OLLAMA_EMBED_MODEL,
        "dim": int(arr.shape[1]),
        "count": int(arr.shape[0]),
        "doc_ids": [d.get("id") for d in docs],
    }
    meta_path_for(docs_path).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"Wrote {embed_path.name} {arr.shape} in {time.time() - t0:.1f}s")


def main() -> None:
    force = "--force" in sys.argv[1:]

    to_embed: list[tuple[Path, list[dict]]] = []
    skipped = 0
    for docs_path in targets():
        if not docs_path.exists():
            continue
        docs = json.loads(docs_path.read_text(encoding="utf-8"))
        if not docs:
            continue
        if not force and is_up_to_date(docs_path, docs):
            skipped += 1
            continue
        to_embed.append((docs_path, docs))

    if not to_embed:
        print(f"Nothing to do — all {skipped} corpus file(s) already have "
              f"up-to-date embeddings. Use --force to re-embed anyway.")
        return

    total_chunks = sum(len(docs) for _, docs in to_embed)
    print(f"{len(to_embed)} corpus file(s) need embedding ({total_chunks} chunks total), "
          f"{skipped} already up to date.")
    for docs_path, docs in to_embed:
        embed_one(docs_path, docs)


if __name__ == "__main__":
    main()
