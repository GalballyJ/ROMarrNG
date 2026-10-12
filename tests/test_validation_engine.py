from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.validation_engine.engine import (
    ValidationError,
    acquire_lock,
    capture_candidate,
    create_plan,
    format_validation_progress,
    inherited_toolchain_environment,
    inventory_files,
    isolated_task_environment,
    parse_counts,
    release_lock,
    run_task,
)
from scripts.validation_engine.reconcile import reconcile_receipts


def make_git_root(root: Path, files: dict[str, str]) -> Path:
    root.mkdir()
    for relative, contents in files.items():
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(contents, encoding="utf-8")
    for command in (
        ["git", "init", "--quiet"],
        ["git", "config", "user.email", "validation@example.invalid"],
        ["git", "config", "user.name", "Validation Test"],
        ["git", "add", "--all"],
        ["git", "commit", "--quiet", "-m", "baseline"],
    ):
        subprocess.run(command, cwd=root, check=True, stdout=subprocess.DEVNULL)
    return root


def test_inventory_hashes_native_pytest_files_and_rejects_empty_or_duplicate_ownership(tmp_path: Path) -> None:
    root = make_git_root(tmp_path / "repo", {
        "requirements.txt": "requests\n",
        "tests/test_a.py": "def test_ok(): pass\n",
        "tests/helper.py": "def helper(): pass\n",
    })
    rules = [{"id": "pytest", "glob": "tests/test_*.py", "framework": "pytest", "owner": "unit"}]
    entries, counts = inventory_files(root, rules)
    assert counts == {"pytest": 1}
    assert entries[0]["file"] == "tests/test_a.py"
    assert len(entries[0]["sha256"]) == 64
    with pytest.raises(ValidationError, match="inventory is empty"):
        inventory_files(root, [{**rules[0], "glob": "tests/missing_*.py"}])
    with pytest.raises(ValidationError, match="duplicate ownership"):
        inventory_files(root, [rules[0], {**rules[0], "id": "second"}])


def test_candidate_digest_changes_when_tracked_or_untracked_source_changes(tmp_path: Path) -> None:
    root = make_git_root(tmp_path / "repo", {"requirements.txt": "pytest\n", "tests/test_a.py": "def test_ok(): pass\n"})
    inventory, _ = inventory_files(root, [{"id": "pytest", "glob": "tests/test_*.py", "framework": "pytest", "owner": "unit"}])
    before = capture_candidate(root, ["requirements.txt"], inventory)
    (root / "requirements.txt").write_text("pytest==9\n", encoding="utf-8")
    changed_tracked = capture_candidate(root, ["requirements.txt"], inventory)
    assert before["sourceSha256"] != changed_tracked["sourceSha256"]
    (root / "new_fixture.txt").write_text("new input\n", encoding="utf-8")
    changed_untracked = capture_candidate(root, ["requirements.txt"], inventory)
    assert changed_tracked["sourceSha256"] != changed_untracked["sourceSha256"]


def test_pytest_summary_counts_passed_skipped_failures_and_network_deselection() -> None:
    counts = parse_counts(
        {"id": "pytest-suite", "parser": "pytest"},
        "test output\n12 passed, 2 skipped, 7 deselected in 4.15s\n",
    )
    assert counts == {"passed": 12, "skipped": 2, "failed": 0, "excluded": 7}
    failed = parse_counts({"id": "pytest-suite", "parser": "pytest"}, "1 failed, 4 passed, 2 errors in 3s\n")
    assert failed["failed"] == 3


def test_live_progress_summary_reports_completed_and_active_tasks() -> None:
    tasks = [
        {"id": "passed", "name": "Passed task"},
        {"id": "blocked", "name": "Blocked task"},
        {"id": "running", "name": "Long task"},
    ]
    results = {
        "passed": {"status": "passed", "startedAt": "2026-10-12T00:00:00Z"},
        "blocked": {"status": "blocked"},
    }
    assert format_validation_progress("sample", tasks, results, tasks[2], 65_000) == (
        "[validation] sample: 1/3 selected tasks complete "
        "(1 passed, 0 failed, 1 blocked, 1 pending); running Long task (1m05s)"
    )


def test_validation_child_environment_uses_allowlist_and_private_directories(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    run_root.mkdir(mode=0o700)
    environment = isolated_task_environment(
        {
            "id": "fixture",
            "kind": "test",
            "env": {"FIXTURE_SETTING": "expected"},
        },
        run_root,
        {
            "PATH": "/toolchain/bin",
            "HOME": "/operator/home",
            "TMPDIR": "/operator/tmp",
            "PYTHONPATH": "/operator/python",
            "PIP_INDEX_URL": "https://user:secret@packages.invalid/simple",
            "GITHUB_TOKEN": "synthetic-token",
            "AWS_SECRET_ACCESS_KEY": "synthetic-secret",
            "RANDOM_PRIVATE_VALUE": "synthetic-private-value",
            "XDG_CONFIG_HOME": "/operator/config",
        },
    )
    environment_root = run_root / "fixture-environment"
    assert environment["PATH"] == "/toolchain/bin"
    assert environment["HOME"] == str(environment_root / "home")
    assert environment["USERPROFILE"] == environment["HOME"]
    assert environment["TMPDIR"] == str(environment_root / "tmp")
    assert environment["XDG_CONFIG_HOME"] == str(environment_root / "xdg-config")
    assert environment["XDG_CACHE_HOME"] == str(environment_root / "xdg-cache")
    assert environment["PIP_CACHE_DIR"] == str(environment_root / "pip-cache")
    assert environment["PYTHONNOUSERSITE"] == "1"
    assert environment["CI"] == "true"
    assert environment["FIXTURE_SETTING"] == "expected"
    for key in ("PYTHONPATH", "PIP_INDEX_URL", "GITHUB_TOKEN", "AWS_SECRET_ACCESS_KEY", "RANDOM_PRIVATE_VALUE"):
        assert key not in environment
    with pytest.raises(ValidationError, match="unapproved inherited environment variable"):
        isolated_task_environment(
            {"id": "fixture", "kind": "test", "pass_env": ["GITHUB_TOKEN"]},
            run_root,
            {"GITHUB_TOKEN": "synthetic-token"},
        )
    with pytest.raises(ValidationError, match="safe lowercase identifier"):
        isolated_task_environment({"id": "../outside", "kind": "test"}, run_root, {"PATH": "/toolchain/bin"})
    if os.name != "nt":
        import stat

        assert stat.S_IMODE((environment_root / "home").stat().st_mode) == 0o700


def test_runtime_probe_environment_uses_the_toolchain_allowlist() -> None:
    environment = inherited_toolchain_environment({
        "PATH": "/toolchain/bin",
        "PYENV_ROOT": "/toolchain/pyenv",
        "PYTHONPATH": "/operator/python",
        "GITHUB_TOKEN": "synthetic-token",
        "HTTPS_PROXY": "http://proxy.invalid",
        "RANDOM_PRIVATE_VALUE": "synthetic-private-value",
    })
    assert environment == {
        "PATH": "/toolchain/bin",
        "PYENV_ROOT": "/toolchain/pyenv",
    }


def test_native_task_writes_private_log_and_records_result_counts(tmp_path: Path) -> None:
    task = {
        "id": "pytest-fixture",
        "kind": "test",
        "command": [sys.executable, "-c", "print('3 passed, 1 skipped, 2 deselected in 0.1s')"],
        "parser": "pytest",
        "minimum_cases": 1,
        "timeout_seconds": 10,
    }
    log = tmp_path / "pytest.log"
    result = run_task(tmp_path, task, log)
    assert result["status"] == "passed"
    assert result["activeCases"] == 3
    assert result["skippedCases"] == 1
    assert result["excludedCases"] == 2
    assert log.stat().st_mode & 0o777 == 0o600


def test_lock_rejects_overlap_and_never_deletes_a_replaced_lock(tmp_path: Path) -> None:
    first = acquire_lock(tmp_path)
    lock_path, content = first
    with pytest.raises(ValidationError, match="another validation run is active"):
        acquire_lock(tmp_path)
    lock_path.write_text('{"pid": -1}\n', encoding="utf-8")
    release_lock(first)
    assert lock_path.exists()
    lock_path.unlink()


def test_read_only_test_plan_discovers_repository_pytest_inventory() -> None:
    from scripts.validation_engine.engine import ROOT

    plan = create_plan(ROOT, {"tests_only": True})
    assert plan["selection"] == "tests-only"
    assert plan["inventoryCounts"]["pytest-suite"] >= 100
    assert plan["tasks"][0]["selected"] is True
    assert plan["runtimes"][0]["command"] == "python3.13"


def make_ci_receipt(run_attempt: str = "1") -> dict:
    sha = "a" * 40
    digest = "b" * 64
    task = {
        "taskId": "pytest-suite",
        "status": "passed",
        "activeCases": 100,
        "skippedCases": 2,
        "excludedCases": 10,
        "inventory": [{"lane": "pytest-suite", "discoveredFiles": 103, "inventorySha256": digest}],
    }
    return {
        "schemaVersion": 1,
        "repository": "romarrng",
        "selection": "tests-only",
        "candidate": {"commit": sha, "tree": "c" * 40, "sourceSha256": "d" * 64, "inventorySha256": "e" * 64},
        "executionContext": {
            "executor": "github-actions",
            "nodeId": "romarrng-pytest-linux",
            "runner": {"name": "GitHub Actions 1", "os": "Linux", "architecture": "X64"},
            "github": {"runId": "41", "runAttempt": run_attempt, "sha": sha},
        },
        "status": "passed",
        "inventoryCounts": {"pytest-suite": 103},
        "inventoryLaneDigests": {"pytest-suite": digest},
        "tasks": [task],
        "totals": {"activeCases": 100},
        "completedAt": "2026-10-11T00:00:00+00:00",
    }


def test_receipt_reconciler_binds_run_attempt_source_and_inventory() -> None:
    receipt = make_ci_receipt()
    summary = reconcile_receipts([receipt], "41", "1", "a" * 40)
    assert summary["activeCases"] == 100
    assert summary["excludedCases"] == 10
    with pytest.raises(ValidationError, match="different workflow run or attempt"):
        reconcile_receipts([receipt], "41", "2", "a" * 40)
    receipt["inventoryLaneDigests"]["pytest-suite"] = "f" * 64
    with pytest.raises(ValidationError, match="does not attest"):
        reconcile_receipts([receipt], "41", "1", "a" * 40)
