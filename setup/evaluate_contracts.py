"""Validate the agent evaluation manifest and optional captured live results."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from productivity_intelligence.evaluation import (  # noqa: E402
    load_evaluation_cases,
    validate_evaluation_result,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("tests/eval_cases.json"),
    )
    parser.add_argument(
        "--results",
        type=Path,
        help="Optional JSON object keyed by evaluation case ID.",
    )
    args = parser.parse_args()

    cases = load_evaluation_cases(args.manifest)
    if args.results is None:
        print(f"[OK] Validated {len(cases)} deterministic evaluation cases")
        return

    captured = json.loads(args.results.read_text(encoding="utf-8"))
    failures: list[str] = []
    for case in cases:
        result = captured.get(case.case_id)
        if not isinstance(result, dict):
            failures.append(f"{case.case_id}: captured result is missing")
            continue
        failures.extend(
            f"{case.case_id}: {violation}"
            for violation in validate_evaluation_result(case, result)
        )
    if failures:
        raise SystemExit("\n".join(failures))
    print(f"[OK] {len(cases)} captured agent results satisfy the release contract")


if __name__ == "__main__":
    main()
