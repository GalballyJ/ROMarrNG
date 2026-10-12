"""Verify the pytest node receipt belongs to the current ROMarrNG workflow."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from . import config
from .engine import ROOT, ValidationError, capture_candidate, inventory_files

NODE_ID = "romarrng-pytest-linux"
TASK_ID = "pytest-suite"
LANE_ID = "pytest-suite"


def reconcile_receipts(receipts: list[dict[str, Any]], run_id: str, run_attempt: str, sha: str, current_candidate: dict[str, Any] | None = None) -> dict[str, Any]:
    if not run_id or not run_attempt or not re.fullmatch(r"[a-f0-9]{40}", sha or ""):
        raise ValidationError("A GitHub run ID, attempt, and full source commit are required.")
    if len(receipts) != 1:
        raise ValidationError("Expected exactly one current ROMarrNG pytest node receipt.")
    receipt = receipts[0]
    context = receipt.get("executionContext") or {}
    github = context.get("github") or {}
    task = next((item for item in receipt.get("tasks", []) if item.get("taskId") == TASK_ID), None)
    if receipt.get("schemaVersion") != 1 or receipt.get("repository") != "romarrng":
        raise ValidationError("Receipt schema or repository does not match ROMarrNG.")
    if receipt.get("status") != "passed" or task is None or task.get("status") != "passed":
        raise ValidationError("Pytest node did not record a passing test task.")
    cases = task.get("activeCases")
    if not isinstance(cases, int) or cases < 1 or receipt.get("totals", {}).get("activeCases", 0) < cases:
        raise ValidationError("Pytest node has no positive passing case count.")
    if receipt.get("selection") not in {"tests-only", "task:" + TASK_ID}:
        raise ValidationError("Receipt has an unexpected test selection.")
    if context.get("executor") != "github-actions" or context.get("nodeId") != NODE_ID:
        raise ValidationError("Receipt was not produced by the expected GitHub pytest node.")
    runner = context.get("runner") or {}
    if runner.get("os") != "Linux" or runner.get("architecture") != "X64":
        raise ValidationError("Receipt runner OS or architecture does not match the configured node.")
    if str(github.get("runId")) != str(run_id) or str(github.get("runAttempt")) != str(run_attempt):
        raise ValidationError("Receipt belongs to a different workflow run or attempt.")
    if github.get("sha") != sha or receipt.get("candidate", {}).get("commit") != sha:
        raise ValidationError("Receipt belongs to a different source commit.")
    candidate = receipt.get("candidate") or {}
    if not re.fullmatch(r"[a-f0-9]{40}", candidate.get("tree", "")) or not re.fullmatch(r"[a-f0-9]{64}", candidate.get("sourceSha256", "")) or not re.fullmatch(r"[a-f0-9]{64}", candidate.get("inventorySha256", "")):
        raise ValidationError("Receipt has an invalid source snapshot identity.")
    if current_candidate is not None:
        identity = ("commit", "tree", "sourceSha256", "inventorySha256", "inputDigests")
        if any(candidate.get(key) != current_candidate.get(key) for key in identity):
            raise ValidationError("Receipt and image job do not share the same source snapshot.")
    count = receipt.get("inventoryCounts", {}).get(LANE_ID)
    digest = receipt.get("inventoryLaneDigests", {}).get(LANE_ID)
    if not isinstance(count, int) or count < 1 or not re.fullmatch(r"[a-f0-9]{64}", digest or ""):
        raise ValidationError("Receipt is missing the pytest inventory.")
    inventory = {item.get("lane"): item for item in task.get("inventory", [])}
    if inventory.get(LANE_ID, {}).get("discoveredFiles") != count or inventory.get(LANE_ID, {}).get("inventorySha256") != digest:
        raise ValidationError("Test task does not attest the discovered pytest inventory.")
    return {
        "schemaVersion": 1,
        "repository": "romarrng",
        "runId": str(run_id),
        "runAttempt": str(run_attempt),
        "sha": sha,
        "status": "passed",
        "activeCases": cases,
        "skippedCases": task.get("skippedCases", 0),
        "excludedCases": task.get("excludedCases", 0),
        "nodeId": NODE_ID,
        "runner": runner,
        "completedAt": receipt.get("completedAt"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reconcile a ROMarrNG CI test receipt")
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--sha", required=True)
    args = parser.parse_args(argv)
    receipt = json.loads(Path(args.receipt).read_text(encoding="utf-8"))
    inventory, _ = inventory_files(ROOT, config.INVENTORY)
    current_candidate = capture_candidate(ROOT, config.INPUTS, inventory)
    summary = reconcile_receipts([receipt], args.run_id, args.run_attempt, args.sha, current_candidate)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValidationError as error:
        print(str(error))
        raise SystemExit(1)
