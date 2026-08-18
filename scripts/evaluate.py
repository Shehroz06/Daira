"""Retrieval evaluation for Diara.

Runs the golden query set (tests/golden_dataset.json) through the live retrieval
pipeline (rag.index.retrieve) and reports Recall@1/3/5, Hit Rate, jurisdiction
accuracy, relevance-threshold accuracy, and retrieval latency.

This measures retrieval/ranking *mechanics* against whatever corpus currently
exists in data/documents.json (a small demonstration corpus) — it is not a
measure of legal completeness.

Requires a running Ollama instance with the configured embedding model, and an
already-built index (run scripts/build_index.py first if data/embeddings.npy is
missing).

Run:  python scripts/evaluate.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow importing project modules when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.rag import index  # noqa: E402

GOLDEN_PATH = Path(__file__).resolve().parent.parent / "tests" / "golden_dataset.json"


def load_cases() -> list[dict]:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def evaluate_case(case: dict) -> dict:
    result = index.retrieve(
        case["query"],
        jurisdiction=case.get("jurisdiction"),
        province_or_state=case.get("province_or_state"),
    )
    retrieved_ids = [d["id"] for d in result["sources"]]
    expected = set(case.get("expected_document_ids") or [])
    is_negative = not expected

    metrics: dict = {
        "id": case["id"],
        "retrieved_ids": retrieved_ids,
        "expected_ids": sorted(expected),
        "relevant": result["relevant"],
        "latency": result["debug"].get("total_time", 0.0),
        "is_negative": is_negative,
    }

    if is_negative:
        metrics["correct_rejection"] = not result["relevant"]
        return metrics

    for k in (1, 3, 5):
        hit_set = set(retrieved_ids[:k]) & expected
        metrics[f"recall@{k}"] = len(hit_set) / len(expected)
    metrics["hit@5"] = 1.0 if set(retrieved_ids[:5]) & expected else 0.0
    metrics["correctly_relevant"] = result["relevant"]

    jurisdiction = case.get("jurisdiction")
    if jurisdiction:
        known = [d for d in result["sources"] if d.get("jurisdiction")]
        matches = [d for d in known if d["jurisdiction"] == jurisdiction]
        metrics["jurisdiction_accuracy"] = (len(matches) / len(known)) if known else None

    return metrics


def print_case(case: dict, metrics: dict) -> None:
    print(f"Query: {case['query']}")
    loc = case.get("jurisdiction")
    if case.get("province_or_state"):
        loc = f"{case['province_or_state']}, {loc}" if loc else case["province_or_state"]
    print(f"Jurisdiction filter: {loc or '(none)'}")
    print("Retrieved:")
    if metrics["retrieved_ids"]:
        for i, doc_id in enumerate(metrics["retrieved_ids"], 1):
            print(f"  {i}. {doc_id}")
    else:
        print("  (none)")
    print(f"Expected: {metrics['expected_ids'] or '(none — should be rejected)'}")
    print(f"Relevant: {metrics['relevant']}")
    if not metrics["is_negative"]:
        hit3 = bool(set(metrics["retrieved_ids"][:3]) & set(metrics["expected_ids"]))
        print(f"Hit@3: {'YES' if hit3 else 'NO'}")
    print()


def summarize(all_metrics: list[dict]) -> None:
    positives = [m for m in all_metrics if not m["is_negative"]]
    negatives = [m for m in all_metrics if m["is_negative"]]

    print("=== Summary ===")
    print(f"Cases: {len(all_metrics)} ({len(positives)} positive, {len(negatives)} negative)")

    if positives:
        for k in (1, 3, 5):
            avg = sum(m[f"recall@{k}"] for m in positives) / len(positives)
            print(f"Recall@{k}: {avg:.2f}")
        hit_rate = sum(m["hit@5"] for m in positives) / len(positives)
        print(f"Hit Rate (@5): {hit_rate:.2f}")

        jur_scores = [m["jurisdiction_accuracy"] for m in positives
                      if m.get("jurisdiction_accuracy") is not None]
        if jur_scores:
            print(f"Jurisdiction Accuracy: {sum(jur_scores) / len(jur_scores):.2f}")

    threshold_correct = sum(1 for m in positives if m["correctly_relevant"])
    threshold_correct += sum(1 for m in negatives if m["correct_rejection"])
    print(f"Relevance Threshold Accuracy: {threshold_correct / len(all_metrics):.2f}")

    avg_latency = sum(m["latency"] for m in all_metrics) / len(all_metrics)
    print(f"Avg retrieval latency: {avg_latency:.3f}s")


def main() -> None:
    index.load()
    if not index.docs:
        print("No documents loaded — run scripts/prepare_documents.py and "
              "scripts/build_index.py first.")
        sys.exit(1)
    if not index.embed_ok:
        print("Warning: vector search is disabled (no embeddings.npy). Evaluation "
              "will run keyword-only; results will differ from production.\n")

    all_metrics = []
    for case in load_cases():
        metrics = evaluate_case(case)
        print_case(case, metrics)
        all_metrics.append(metrics)

    summarize(all_metrics)


if __name__ == "__main__":
    main()
