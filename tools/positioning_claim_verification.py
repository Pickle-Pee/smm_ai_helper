"""Check an exported atomic POSITIONING review without sending a provider request.

Run as python -m tools.positioning_claim_verification BUNDLE. The bundle
contains draft, evidence and reviews. Print only bounded finding metadata.
"""

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from app.module_execution.errors import ModuleExecutionContractError
from app.module_execution.executors.claim_support import unique_object
from app.orchestration_runtime.claim_verification import (
    DraftStatement,
    OutputReview,
    ReviewEvidence,
    verify_claim_review,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    args = parser.parse_args()

    try:
        with args.bundle.open("rb") as stream:
            raw = stream.read(1_048_577)
        if len(raw) > 1_048_576:
            raise ValueError("Bundle exceeds size limit")
        bundle = json.loads(raw, object_pairs_hook=unique_object)
        draft = {
            name: DraftStatement(row["text"], frozenset(row["evidence_ids"]))
            for name, row in bundle["draft"].items()
        }
        evidence = {identity: ReviewEvidence(**row) for identity, row in bundle["evidence"].items()}
        reviews = tuple(OutputReview.model_validate(row) for row in bundle["reviews"])
        findings = verify_claim_review(draft, evidence, reviews)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError, ModuleExecutionContractError):
        print(json.dumps({"status": "invalid_bundle"}))
        return 2

    print(json.dumps({
        "status": "rejected" if findings else "no_deterministic_findings",
        "findings": [asdict(finding) for finding in findings],
    }))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
