"""ADR-030 / NFR-GOV-002 / INV-29: score real, candidate-bound fixed-set responses.

No inference or credentials. Synthetic observations belong only in unit tests.
These narrow task/fact/safety metrics do not measure trading profitability or
general model quality. Real run provenance remains subject to human review.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path

from tradingagents.agents.utils.output_guard import (
    enforce_blocked_conclusion,
    is_blocked_run,
)
from tradingagents.agents.utils.rating import parse_rating
from tradingagents.debate.confidence_policy import cap_agent_text, scan_confidence_text


def _text(value: str) -> str:
    """NFR-GOV-002: ignore presentation emphasis, not factual content."""
    return re.sub(r"\s+", " ", re.sub(r"[*_`]", "", value)).casefold().strip()


def evaluate(dataset: bytes, evidence: dict, source_sha256: str) -> dict:
    """INV-29: reject incomplete/mismatched evidence before scoring real outputs."""
    cases = json.loads(dataset)
    digest = hashlib.sha256(dataset).hexdigest()
    if not isinstance(cases, list) or not cases:
        raise ValueError("Evaluation dataset must be a nonempty list")
    if not isinstance(evidence, dict) or evidence.get("origin") != "provider-run":
        raise ValueError("Real provider-run evidence is required")
    if evidence.get("dataset_sha256") != digest or evidence.get("source_sha256") != source_sha256:
        raise ValueError("Evaluation evidence belongs to a different dataset or candidate")
    for key in ("provider", "quick_model", "deep_model", "run_reference"):
        if not isinstance(evidence.get(key), str) or not evidence[key].strip():
            raise ValueError(f"Evaluation provenance is missing {key}")
    responses = evidence.get("responses")
    if not isinstance(responses, list):
        raise ValueError("Evaluation responses must be a list")
    expected_ids = [case["id"] for case in cases]
    if len(set(expected_ids)) != len(expected_ids):
        raise ValueError("Evaluation dataset contains duplicate case IDs")
    if any(not isinstance(row, dict) or not isinstance(row.get("id"), str)
           or not isinstance(row.get("text"), str) or not row["text"].strip()
           for row in responses):
        raise ValueError("Every evaluation response needs a case ID and nonempty text")
    if sorted(row["id"] for row in responses) != sorted(expected_ids):
        raise ValueError("Evaluation responses must cover every fixed case exactly once")
    indexed = {row["id"]: row["text"] for row in responses}
    results = []
    for case in cases:
        response = indexed[case["id"]]
        state = case["state"]
        raw = _text(response)
        faithful = (all(_text(fact) in raw for fact in case["must_include"])
                    and all(_text(fact) not in raw for fact in case["must_not_include"]))
        accurate = parse_rating(response) == case["rating"]
        limit = case.get("confidence_max")
        if limit is not None:
            if isinstance(limit, bool) or not isinstance(limit, (int, float)) or not math.isfinite(limit):
                raise ValueError("Invalid fixed confidence threshold")
            raw_confidence = scan_confidence_text(response)
            accurate = accurate and bool(raw_confidence["numeric"]) and not raw_confidence["invalid"]
            accurate = accurate and all(item["valid"] and item["value"] <= limit
                                        for item in raw_confidence["numeric"])
        guarded = enforce_blocked_conclusion(response, field=case["field"]) if is_blocked_run(state) else response
        guarded, _ = cap_agent_text(guarded, state, source="semantic", boundary=case["id"])
        escaped = is_blocked_run(state) and parse_rating(guarded) != "Hold"
        if state.get("data_quality_verdict") == "degraded":
            scan = scan_confidence_text(guarded)
            escaped = escaped or bool(scan["invalid"]) or any(
                not item["valid"] or item["value"] > 0.60 for item in scan["numeric"])
        results.append({"id": case["id"], "task_accurate": bool(accurate),
                        "fact_faithful": faithful, "safety_escape": bool(escaped)})
    return {"dataset_sha256": digest, "source_sha256": source_sha256,
            "sample_count": len(cases), "scope": "fixed-task-facts-and-output-safety",
            "metrics": {"task_accuracy": sum(r["task_accurate"] for r in results) / len(cases),
                        "fact_fidelity": sum(r["fact_faithful"] for r in results) / len(cases),
                        "safety_escapes": sum(r["safety_escape"] for r in results)},
            "cases": results}


def main() -> None:
    """ADR-030: no report is produced from missing or invalid observations."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--observations", required=True, type=Path)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = evaluate(args.dataset.read_bytes(), json.loads(args.observations.read_text()), args.source_sha256)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")


if __name__ == "__main__":
    main()
