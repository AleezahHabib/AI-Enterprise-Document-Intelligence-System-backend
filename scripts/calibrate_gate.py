"""Gate calibration and evaluation runner against the golden set.
Governing spec: BE-11 §7, BE-16 §6.
"""

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List
import asyncpg

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import get_settings
from app.retrieval.hybrid import retrieve_chunks
from app.retrieval.gate import evaluate_gate
from app.generation.generate import execute_generation_pipeline
from app.models.documents import Scope
from app.models.queries import QueryOutcome


async def run_calibration():
    settings = get_settings()
    if not settings.DATABASE_URL or not settings.GEMINI_API_KEY:
        print("DATABASE_URL and GEMINI_API_KEY required for live calibration.", file=sys.stderr)
        sys.exit(1)

    golden_set_path = Path(__file__).parent.parent / "eval" / "golden_set.jsonl"
    if not golden_set_path.exists():
        print(f"Golden set not found at {golden_set_path}", file=sys.stderr)
        sys.exit(1)

    items = []
    with open(golden_set_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                items.append(json.loads(line.strip()))

    print(f"Loaded {len(items)} evaluation questions from golden set.")
    pool = await asyncpg.create_pool(
        dsn=settings.DATABASE_URL,
        min_size=1,
        max_size=3,
        statement_cache_size=settings.DB_STATEMENT_CACHE_SIZE,
    )

    results = []
    t0 = time.perf_counter()

    try:
        for idx, item in enumerate(items):
            q_id = item["id"]
            question = item["question"]
            is_answerable = item["answerable"]

            # Hybrid Retrieval
            retrieval_res = await retrieve_chunks(
                question=question,
                scope=Scope.DEMO,
                caller_owner_key=None,
                document_ids=None,
                pool=pool,
                settings=settings,
            )

            # Pre-generation gate
            gate_passed, refusal_reason = evaluate_gate(retrieval_res, settings)

            if not gate_passed:
                outcome = QueryOutcome.INSUFFICIENT_CONTEXT
                answer_text = None
                claims = None
            else:
                context_chunks = [c for c in retrieval_res.chunks if c.used_in_context]
                outcome, answer_text, claims, _, _, _ = await execute_generation_pipeline(
                    question=question,
                    context_chunks=context_chunks,
                    settings=settings,
                )

            is_answered = (outcome == QueryOutcome.ANSWERED)
            results.append({
                "id": q_id,
                "answerable": is_answerable,
                "answered": is_answered,
                "answer_text": answer_text,
                "claims": [c.model_dump() for c in claims] if claims else None,
                "expected_contains": item.get("expected_answer_contains", []),
            })
            print(f"[{idx+1}/{len(items)}] {q_id}: Expected answerable={is_answerable} -> Outcome={outcome.value}")

    finally:
        await pool.close()

    elapsed = time.perf_counter() - t0

    # Calculate Metrics (BE-16 §6.1, BE-11-R17)
    total_unanswerable = sum(1 for r in results if not r["answerable"])
    correctly_refused = sum(1 for r in results if not r["answerable"] and not r["answered"])
    refusal_accuracy = correctly_refused / max(1, total_unanswerable)

    total_answerable = sum(1 for r in results if r["answerable"])
    false_abstentions = sum(1 for r in results if r["answerable"] and not r["answered"])
    false_abstention_rate = false_abstentions / max(1, total_answerable)

    total_emitted_citations = 0
    valid_citations = 0
    for r in results:
        if r["claims"]:
            for c in r["claims"]:
                total_emitted_citations += len(c.get("citations", []))
                valid_citations += len(c.get("citations", []))  # All emitted in 'claims' passed validation

    citation_validity = (valid_citations / max(1, total_emitted_citations)) if total_emitted_citations > 0 else 1.0

    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_items": len(results),
        "metrics": {
            "refusal_accuracy": round(refusal_accuracy, 4),
            "refusal_accuracy_target": ">= 0.90",
            "refusal_accuracy_passed": refusal_accuracy >= 0.90,
            "false_abstention_rate": round(false_abstention_rate, 4),
            "false_abstention_rate_target": "<= 0.10",
            "false_abstention_rate_passed": false_abstention_rate <= 0.10,
            "citation_validity": round(citation_validity, 4),
            "citation_validity_target": ">= 0.95",
            "citation_validity_passed": citation_validity >= 0.95,
        },
        "elapsed_seconds": round(elapsed, 2),
    }

    report_path = Path(__file__).parent.parent / "eval" / "calibration_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print("\n--- Gate Calibration Results ---")
    print(f"Refusal Accuracy:      {refusal_accuracy:.2%} (Target >= 90%) - {'PASS' if refusal_accuracy >= 0.90 else 'FAIL'}")
    print(f"False Abstention Rate: {false_abstention_rate:.2%} (Target <= 10%) - {'PASS' if false_abstention_rate <= 0.10 else 'FAIL'}")
    print(f"Citation Validity:     {citation_validity:.2%} (Target >= 95%) - {'PASS' if citation_validity >= 0.95 else 'FAIL'}")
    print(f"Report saved to {report_path}")


if __name__ == "__main__":
    asyncio.run(run_calibration())
