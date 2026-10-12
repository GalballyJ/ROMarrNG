"""ROMarrNG's source-bound, native Python validation runner.

It leaves pytest collection, markers, fixtures, and assertions authoritative.
The engine records a discoverable candidate, fresh process execution, result
counts, and private logs so local and hosted results can be compared safely.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from . import config

ENGINE_VERSION = 1
ROOT = Path(__file__).resolve().parents[2]
INHERITED_ENVIRONMENT_KEYS = frozenset({
    "ASDF_DATA_DIR", "ASDF_DIR", "COMSPEC", "LANG", "LC_ALL", "LC_CTYPE",
    "MISE_DATA_DIR", "MISE_HOME", "PATH", "PATHEXT", "PYENV_ROOT",
    "SYSTEMROOT", "TZ", "WINDIR",
})
APPROVED_TASK_PASS_ENVIRONMENT: dict[str, frozenset[str]] = {}
IGNORED_DIRS = {".git", ".pytest_cache", "__pycache__", ".venv", "venv", "node_modules", "_output", "_tests", "TestResults", "coverage"}
PROGRESS_INTERVAL_SECONDS = 60


class ValidationError(RuntimeError):
    """Raised when the selected plan cannot be executed safely."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_file(root: Path, relative: str) -> str:
    file_path = root / relative
    if file_path.is_symlink() or not file_path.is_file():
        raise ValidationError(f"Candidate input is not a regular file: {relative}")
    return digest_bytes(file_path.read_bytes())


def stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def run_git(root: Path, args: list[str]) -> bytes:
    result = subprocess.run(["git", *args], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode:
        raise ValidationError("Unable to bind validation to Git source: " + result.stderr.decode("utf-8", "replace").strip())
    return result.stdout


def inventory_files(root: Path, rules: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    entries: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    owned: set[str] = set()
    for rule in rules:
        matches = sorted(root.glob(rule["glob"]))
        matches = [item for item in matches if not any(part in IGNORED_DIRS for part in item.relative_to(root).parts)]
        if rule.get("required", True) and not matches:
            raise ValidationError(f"Required test inventory is empty: {rule['id']}")
        counts[rule["id"]] = len(matches)
        for file_path in matches:
            relative = file_path.relative_to(root).as_posix()
            if file_path.is_symlink() or not file_path.is_file():
                raise ValidationError(f"Symlink or non-file in test inventory: {relative}")
            if relative in owned:
                raise ValidationError(f"Test file has duplicate ownership: {relative}")
            owned.add(relative)
            entries.append({
                "file": relative,
                "framework": rule["framework"],
                "owner": rule["owner"],
                "lane": rule["id"],
                "sha256": digest_file(root, relative),
            })
    return sorted(entries, key=lambda item: item["file"]), counts


def untracked_digests(root: Path) -> list[dict[str, str]]:
    raw = run_git(root, ["ls-files", "--others", "--exclude-standard", "-z"])
    paths = sorted(part.decode("utf-8", "surrogateescape") for part in raw.split(b"\0") if part)
    result = []
    for relative in paths:
        item = root / relative
        if item.is_symlink():
            value = "symlink:" + os.readlink(item)
            file_digest = digest_bytes(value.encode())
        elif item.is_file():
            file_digest = digest_file(root, relative)
        else:
            file_digest = "not-regular"
        result.append({"file": relative, "sha256": file_digest})
    return result


def capture_candidate(root: Path, inputs: Iterable[str], inventory: list[dict[str, Any]]) -> dict[str, Any]:
    commit = run_git(root, ["rev-parse", "HEAD"]).decode().strip()
    tree = run_git(root, ["rev-parse", "HEAD^{tree}"]).decode().strip()
    diff = digest_bytes(run_git(root, ["diff", "--binary", "HEAD"]))
    untracked = untracked_digests(root)
    input_digests = [{"file": item, "sha256": digest_file(root, item)} for item in inputs]
    inventory_sha = digest_bytes(stable_json(inventory).encode())
    source_sha = digest_bytes(stable_json({
        "commit": commit,
        "tree": tree,
        "diffSha256": diff,
        "untracked": untracked,
        "inputDigests": input_digests,
        "inventorySha256": inventory_sha,
    }).encode())
    status = run_git(root, ["status", "--porcelain=v1", "--untracked-files=all"]).decode().strip()
    return {
        "commit": commit,
        "tree": tree,
        "sourceSha256": source_sha,
        "inventorySha256": inventory_sha,
        "inputDigests": input_digests,
        "dirty": bool(status),
        "untrackedCount": len(untracked),
    }


def command_available(command: str) -> bool:
    from shutil import which

    return which(command) is not None


def inherited_toolchain_environment(inherited: dict[str, str] | None = None) -> dict[str, str]:
    source = os.environ if inherited is None else inherited
    values: dict[str, str] = {}
    for key, value in source.items():
        normalized = key.upper()
        if normalized not in INHERITED_ENVIRONMENT_KEYS or not isinstance(value, str):
            continue
        if normalized not in values or key == normalized:
            values[normalized] = value
    return values


def validate_config() -> None:
    task_ids = [task.get("id") for task in config.TASKS]
    if any(
        not isinstance(item, str) or re.fullmatch(r"[a-z0-9][a-z0-9-]*", item) is None
        for item in task_ids
    ) or len(set(task_ids)) != len(task_ids):
        raise ValidationError("Validation task IDs must be unique safe lowercase identifiers.")
    lane_ids = {rule.get("id") for rule in config.INVENTORY}
    if len(lane_ids) != len(config.INVENTORY):
        raise ValidationError("Test inventory lane IDs must be unique.")
    owned: set[str] = set()
    for task in config.TASKS:
        command = task.get("command")
        if not isinstance(command, list) or not command or any(not isinstance(item, str) or not item for item in command):
            raise ValidationError("Validation tasks must use a native executable and argument array: " + str(task.get("id")))
        if task.get("kind") == "test" and (task.get("minimum_cases", 0) < 1 or task.get("parser") != "pytest"):
            raise ValidationError("Test tasks require a native result parser and a positive case minimum: " + task["id"])
        pass_env = task.get("pass_env", [])
        if not isinstance(pass_env, list) or any(
            not isinstance(name, str) or name not in APPROVED_TASK_PASS_ENVIRONMENT.get(task["id"], frozenset())
            for name in pass_env
        ):
            raise ValidationError("Validation task requests an unapproved inherited environment variable: " + task["id"])
        for lane in task.get("inventory_lanes", []):
            if lane not in lane_ids:
                raise ValidationError(f"Unknown inventory lane: {task['id']}/{lane}")
            owned.add(lane)
        for dependency in task.get("depends_on", []):
            if dependency not in task_ids:
                raise ValidationError(f"Unknown task dependency: {task['id']}/{dependency}")
    visiting: set[str] = set()
    visited: set[str] = set()
    by_id = {task["id"]: task for task in config.TASKS}
    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise ValidationError("Validation task dependency cycle includes: " + task_id)
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency in by_id[task_id].get("depends_on", []):
            visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)
    for task_id in task_ids:
        visit(task_id)
    for rule in config.INVENTORY:
        if rule.get("required", True) and rule["id"] not in owned:
            raise ValidationError("Required test inventory has no registered task: " + rule["id"])


def runtime_receipt(root: Path) -> dict[str, Any]:
    command = ["python3.13", "--version"]
    available = command_available(command[0])
    output = ""
    status = None
    if available:
        result = subprocess.run(
            command,
            cwd=root,
            env=inherited_toolchain_environment(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        output, status = result.stdout.strip(), result.returncode
    compatible = bool(re.match(r"^Python 3\.13\.\d+$", output))
    return {
        "command": command[0],
        "available": available and status == 0,
        "version": output or None,
        "versionCompatible": compatible,
        "required": True,
        "exitCode": status,
    }


def create_plan(root: Path, options: dict[str, Any]) -> dict[str, Any]:
    validate_config()
    inventory, counts = inventory_files(root, config.INVENTORY)
    candidate = capture_candidate(root, config.INPUTS, inventory)
    lanes = {rule["id"] for rule in config.INVENTORY}
    task_by_id = {task["id"]: task for task in config.TASKS}
    if options.get("task") and options["task"] not in task_by_id:
        raise ValidationError("Unknown validation task: " + options["task"])
    selected_ids: set[str] = set()
    def select(task_id: str) -> None:
        if task_id in selected_ids:
            return
        selected_ids.add(task_id)
        for dependency in task_by_id[task_id].get("depends_on", []):
            select(dependency)
    if options.get("task"):
        select(options["task"])
    elif options.get("tests_only"):
        for task in config.TASKS:
            if task["kind"] == "test":
                select(task["id"])
    else:
        for task in config.TASKS:
            select(task["id"])
    tasks = []
    for task in config.TASKS:
        for lane in task.get("inventory_lanes", []):
            if lane not in lanes:
                raise ValidationError(f"Unknown inventory lane: {task['id']}/{lane}")
        tasks.append({
            "id": task["id"],
            "name": task["name"],
            "stage": task["stage"],
            "kind": task["kind"],
            "selected": task["id"] in selected_ids,
            "command": task["command"],
            "minimumCases": task.get("minimum_cases"),
            "inventoryLanes": task.get("inventory_lanes", []),
            "dependsOn": task.get("depends_on", []),
            "timeoutSeconds": task.get("timeout_seconds", 1800),
        })
    if options.get("tests_only") and not any(task["selected"] for task in tasks):
        raise ValidationError("No test tasks are registered.")
    selected = [task for task in tasks if task["selected"]]
    commands = sorted({"python3.13" if task["command"][0] in {"{PYTHON}"} else task["command"][0] for task in selected})
    prerequisites = [{"command": item, "available": command_available(item)} for item in sorted({"git", *commands})]
    runtime = runtime_receipt(root)
    execution = {
        "executor": "github-actions" if os.environ.get("GITHUB_ACTIONS") == "true" else "local",
        "platform": sys.platform,
        "architecture": os.uname().machine if hasattr(os, "uname") else "unknown",
        "pythonVersion": sys.version.split()[0],
        "nodeId": os.environ.get("VALIDATION_NODE_ID"),
        "runner": {
            "name": os.environ.get("RUNNER_NAME"),
            "os": os.environ.get("RUNNER_OS", sys.platform),
            "architecture": os.environ.get("RUNNER_ARCH", "unknown"),
        } if os.environ.get("GITHUB_ACTIONS") == "true" else None,
        "github": {
            "workflow": os.environ.get("GITHUB_WORKFLOW"),
            "job": os.environ.get("GITHUB_JOB"),
            "runId": os.environ.get("GITHUB_RUN_ID"),
            "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
            "eventName": os.environ.get("GITHUB_EVENT_NAME"),
            "sha": os.environ.get("GITHUB_SHA"),
        } if os.environ.get("GITHUB_ACTIONS") == "true" else None,
    }
    body = {
        "schemaVersion": ENGINE_VERSION,
        "repository": config.REPOSITORY,
        "selection": "task:" + options["task"] if options.get("task") else "tests-only" if options.get("tests_only") else "full",
        "candidate": candidate,
        "inventory": inventory,
        "inventoryCounts": counts,
        "inventoryLaneDigests": {
            rule["id"]: digest_bytes(stable_json([item for item in inventory if item["lane"] == rule["id"]]).encode())
            for rule in config.INVENTORY
        },
        "prerequisites": prerequisites,
        "runtimes": [runtime],
        "executionContext": execution,
        "tasks": tasks,
    }
    body["planSha256"] = digest_bytes(stable_json(body).encode())
    return body


def isolated_task_environment(
    task: dict[str, Any],
    run_root: Path,
    inherited: dict[str, str] | None = None,
) -> dict[str, str]:
    task_id = task.get("id")
    if not isinstance(task_id, str) or re.fullmatch(r"[a-z0-9][a-z0-9-]*", task_id) is None:
        raise ValidationError("Validation task ID must be a safe lowercase identifier.")
    source = os.environ if inherited is None else inherited
    environment = inherited_toolchain_environment(source)

    approved_pass_env = APPROVED_TASK_PASS_ENVIRONMENT.get(task.get("id"), frozenset())
    pass_env = task.get("pass_env", [])
    if not isinstance(pass_env, list) or any(
        not isinstance(name, str) or name not in approved_pass_env for name in pass_env
    ):
        raise ValidationError("Validation task requests an unapproved inherited environment variable: " + str(task.get("id")))
    for name in pass_env:
        match = next((value for key, value in source.items() if key.upper() == name.upper()), None)
        if isinstance(match, str):
            environment[name] = match
    environment.update({key: value for key, value in task.get("env", {}).items() if isinstance(value, str)})

    environment_root = run_root / f"{task_id}-environment"
    directories = {
        "HOME": environment_root / "home",
        "USERPROFILE": environment_root / "home",
        "TMPDIR": environment_root / "tmp",
        "TMP": environment_root / "tmp",
        "TEMP": environment_root / "tmp",
        "XDG_CONFIG_HOME": environment_root / "xdg-config",
        "XDG_CACHE_HOME": environment_root / "xdg-cache",
        "APPDATA": environment_root / "AppData" / "Roaming",
        "LOCALAPPDATA": environment_root / "AppData" / "Local",
        "PIP_CACHE_DIR": environment_root / "pip-cache",
    }
    for directory in set(directories.values()):
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    environment.update({key: str(value) for key, value in directories.items()})
    environment.update({"CI": "true", "NO_COLOR": "1", "PYTHONNOUSERSITE": "1"})
    return environment


def parse_counts(task: dict[str, Any], output: str) -> dict[str, int]:
    if task.get("parser") == "pytest":
        summaries = [line for line in output.splitlines() if re.search(r"\d+\s+(?:passed|failed|skipped|deselected|errors?)\b", line)]
        line = summaries[-1] if summaries else ""
        def count(name: str) -> int:
            found = re.search(rf"(\d+)\s+{name}\b", line)
            return int(found.group(1)) if found else 0
        return {
            "passed": count("passed"),
            "skipped": count("skipped"),
            "failed": count("failed") + count("error") + count("errors"),
            "excluded": count("deselected"),
        }
    raise ValidationError("No native result parser is registered for task: " + task["id"])


def format_validation_progress(repository: str, tasks: list[dict[str, Any]], results: dict[str, dict[str, Any]], current_task: dict[str, Any] | None = None, elapsed_ms: int = 0) -> str:
    receipts = [results[task["id"]] for task in tasks if task["id"] in results]
    passed = sum(receipt["status"] == "passed" for receipt in receipts)
    failed = sum(receipt["status"] in {"failed", "incomplete"} for receipt in receipts)
    blocked = sum(receipt["status"] in {"blocked", "not-run"} for receipt in receipts)
    completed = passed + failed
    pending = max(0, len(tasks) - completed - blocked)
    active = ""
    if current_task is not None:
        seconds = elapsed_ms // 1000
        active = f"; running {current_task.get('name', current_task['id'])} ({seconds // 60}m{seconds % 60:02d}s)"
    return f"[validation] {repository}: {completed}/{len(tasks)} selected tasks complete ({passed} passed, {failed} failed, {blocked} blocked, {pending} pending){active}"


def run_task(root: Path, task: dict[str, Any], log_path: Path) -> dict[str, Any]:
    start = time.monotonic()
    started_at = utc_now()
    env = isolated_task_environment(task, log_path.parent)
    proc = subprocess.Popen(
        task["command"],
        cwd=root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=(os.name != "nt"),
    )
    timed_out = False
    try:
        output_bytes, _ = proc.communicate(timeout=task.get("timeout_seconds", 1800))
    except subprocess.TimeoutExpired:
        timed_out = True
        if os.name != "nt":
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=2)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        else:
            proc.kill()
        output_bytes, _ = proc.communicate()
    output = output_bytes.decode("utf-8", "replace")
    with log_path.open("wb") as log:
        os.chmod(log_path, 0o600)
        log.write(output_bytes)
    counts = parse_counts(task, output) if task.get("kind") == "test" else {"passed": 0, "skipped": 0, "failed": 0, "excluded": 0}
    passed = proc.returncode == 0 and not timed_out and (task.get("kind") != "test" or counts["passed"] >= task.get("minimum_cases", 1))
    status = "failed" if timed_out or proc.returncode != 0 else "passed" if passed else "incomplete"
    return {
        "taskId": task["id"],
        "status": status,
        "startedAt": started_at,
        "durationMs": int((time.monotonic() - start) * 1000),
        "exitCode": proc.returncode,
        "timedOut": timed_out,
        "outputBytes": len(output_bytes),
        "logSha256": digest_bytes(output_bytes),
        "logFile": log_path.name,
        "activeCases": counts["passed"] if task.get("kind") == "test" else None,
        "passedCases": counts["passed"] if task.get("kind") == "test" else None,
        "skippedCases": counts["skipped"],
        "failedCases": counts["failed"],
        "excludedCases": counts["excluded"],
        "required": task.get("required", True),
    }


def acquire_lock(root: Path) -> tuple[Path, str]:
    key = digest_bytes(str(root.resolve()).encode())[:16]
    lock = Path(tempfile.gettempdir()) / f"{config.REPOSITORY}-validation-{key}.lock"
    try:
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        try:
            data = json.loads(lock.read_text())
        except Exception as read_error:
            raise ValidationError(f"Validation lock exists but cannot be read safely: {lock}") from read_error
        alive = False
        if isinstance(data.get("pid"), int) and data["pid"] > 0:
            try:
                os.kill(data["pid"], 0)
                alive = True
            except PermissionError:
                alive = True
            except ProcessLookupError:
                pass
        status = f"another validation run is active (pid {data.get('pid')})" if alive else "a stale validation lock exists; verify its process is gone before removing it"
        raise ValidationError(f"{status}: {lock}") from error
    content = json.dumps({"pid": os.getpid(), "startedAt": utc_now()}) + "\n"
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        file.write(content)
    return lock, content


def release_lock(lock: tuple[Path, str]) -> None:
    path, content = lock
    try:
        if path.read_text(encoding="utf-8") == content:
            path.unlink()
    except FileNotFoundError:
        pass


def execute(root: Path, plan: dict[str, Any], on_progress: Any = None) -> tuple[dict[str, Any], Path, int]:
    plan_body = dict(plan)
    plan_digest = plan_body.pop("planSha256", None)
    if plan_digest != digest_bytes(stable_json(plan_body).encode()):
        raise ValidationError("Validation plan digest does not match its contents.")
    selected = [item for item in plan["tasks"] if item["selected"]]
    missing = [item for item in plan["prerequisites"] if not item["available"]]
    missing.extend(item for item in plan["runtimes"] if item.get("required", True) and (not item["available"] or not item["versionCompatible"]))
    github = plan["executionContext"].get("github")
    if plan["executionContext"].get("executor") == "github-actions" and github.get("sha") != plan["candidate"]["commit"]:
        missing.append({"command": "GITHUB_SHA", "available": False, "expected": plan["candidate"]["commit"], "actual": github.get("sha")})
    run_root = Path(tempfile.mkdtemp(prefix=config.REPOSITORY + "-validation-"))
    os.chmod(run_root, 0o700)
    run_id = str(uuid.uuid4())
    started_at = utc_now()
    by_id: dict[str, dict[str, Any]] = {}
    for task in plan["tasks"]:
        if not task["selected"]:
            by_id[task["id"]] = {"taskId": task["id"], "status": "excluded", "reason": plan["selection"], "required": task.get("required", True)}

    progress_state: dict[str, str] = {}

    def report_progress(current_task: dict[str, Any] | None = None, started: float = 0.0) -> None:
        if on_progress is None:
            return
        elapsed_ms = int((time.monotonic() - started) * 1000) if current_task is not None else 0
        summary = format_validation_progress(config.REPOSITORY, selected, by_id, current_task, elapsed_ms)
        if progress_state.get("last") == summary:
            return
        progress_state["last"] = summary
        on_progress(summary)

    if missing:
        for task in selected:
            by_id[task["id"]] = {"taskId": task["id"], "status": "not-run", "reason": "required command or runtime is unavailable", "required": task.get("required", True)}
        report_progress()
        receipt = make_receipt(plan, run_id, started_at, by_id, run_root, missing)
        return receipt, run_root, 1

    source_changed = False
    for task in selected:
        failed_dependency = next((by_id.get(dependency) for dependency in task.get("dependsOn", []) if by_id.get(dependency, {}).get("status") != "passed"), None)
        if failed_dependency:
            by_id[task["id"]] = {"taskId": task["id"], "status": "blocked", "reason": "dependency did not pass", "required": True}
            report_progress()
            continue
        if capture_candidate(root, config.INPUTS, plan["inventory"])["sourceSha256"] != plan["candidate"]["sourceSha256"]:
            by_id[task["id"]] = {"taskId": task["id"], "status": "blocked", "reason": "candidate source changed after planning", "required": True}
            report_progress()
            source_changed = True
            break
        configured = next(item for item in config.TASKS if item["id"] == task["id"])
        venv = run_root / "venv"
        python_bin = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        command = [
            item.replace("{VENV}", str(venv)).replace("{PYTHON}", str(python_bin))
            for item in configured["command"]
        ]
        executable_task = {**configured, "command": command}
        if configured["id"] == "install-test-dependencies":
            executable_task["env"] = {"PIP_NO_CACHE_DIR": "1"}
        task_started = time.monotonic()
        report_progress(task, task_started)
        heartbeat_stop = threading.Event()

        def heartbeat() -> None:
            while not heartbeat_stop.wait(PROGRESS_INTERVAL_SECONDS):
                report_progress(task, task_started)

        heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
        heartbeat_thread.start()
        try:
            result = run_task(root, executable_task, run_root / (task["id"] + ".log"))
        finally:
            heartbeat_stop.set()
            heartbeat_thread.join()
        result["inventory"] = [{
            "lane": lane,
            "discoveredFiles": plan["inventoryCounts"].get(lane, 0),
            "inventorySha256": plan["inventoryLaneDigests"][lane],
        } for lane in configured.get("inventory_lanes", [])]
        by_id[task["id"]] = result
        report_progress()
        if capture_candidate(root, config.INPUTS, plan["inventory"])["sourceSha256"] != plan["candidate"]["sourceSha256"]:
            source_changed = True
            break
    for task in plan["tasks"]:
        if task["id"] not in by_id:
            by_id[task["id"]] = {"taskId": task["id"], "status": "blocked" if source_changed else "excluded", "reason": "candidate source changed during execution" if source_changed else "not selected", "required": True}
    report_progress()
    receipt = make_receipt(plan, run_id, started_at, by_id, run_root, missing, source_changed)
    return receipt, run_root, 0 if receipt["status"] == "passed" else 1


def make_receipt(plan: dict[str, Any], run_id: str, started_at: str, by_id: dict[str, dict[str, Any]], run_root: Path, missing: list[dict[str, Any]], source_changed: bool = False) -> dict[str, Any]:
    tasks = [by_id[item["id"]] for item in plan["tasks"]]
    totals = {
        "planned": sum(bool(item["selected"]) for item in plan["tasks"]),
        "executed": sum("startedAt" in item for item in tasks),
        "passed": sum(item["status"] == "passed" for item in tasks),
        "failed": sum(item["status"] in {"failed", "incomplete"} for item in tasks),
        "blocked": sum(item["status"] == "blocked" for item in tasks),
        "excluded": sum(item["status"] == "excluded" for item in tasks),
        "activeCases": sum(item.get("activeCases") or 0 for item in tasks),
        "passedCases": sum(item.get("passedCases") or 0 for item in tasks),
        "skippedCases": sum(item.get("skippedCases") or 0 for item in tasks),
        "failedCases": sum(item.get("failedCases") or 0 for item in tasks),
        "excludedCases": sum(item.get("excludedCases") or 0 for item in tasks),
    }
    status = "failed" if source_changed or missing or any(item["selected"] and item.get("required", True) and by_id[item["id"]]["status"] != "passed" for item in plan["tasks"]) else "passed"
    receipt = {
        "schemaVersion": ENGINE_VERSION,
        "repository": config.REPOSITORY,
        "selection": plan["selection"],
        "runId": run_id,
        "startedAt": started_at,
        "completedAt": utc_now(),
        "planSha256": plan["planSha256"],
        "candidate": plan["candidate"],
        "inventoryCounts": plan["inventoryCounts"],
        "inventoryLaneDigests": plan["inventoryLaneDigests"],
        "executionContext": plan["executionContext"],
        "status": status,
        "prerequisites": {"missing": missing, "sourceChanged": source_changed},
        "runtimes": plan["runtimes"],
        "tasks": tasks,
        "totals": totals,
    }
    (run_root / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    os.chmod(run_root / "receipt.json", 0o600)
    return receipt


def export_receipt(receipt: dict[str, Any], destination: str) -> None:
    raw_target = Path(destination).absolute()
    if raw_target.is_symlink():
        raise ValidationError("Validation receipt export cannot replace a symbolic link.")
    target = raw_target.resolve()
    roots = [Path(tempfile.gettempdir()).resolve()]
    if os.environ.get("RUNNER_TEMP"):
        roots.append(Path(os.environ["RUNNER_TEMP"]).resolve())
    if not any(target != root and root in target.parents for root in roots):
        raise ValidationError("Validation receipts may only be exported beneath a system or runner temporary directory.")
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    target.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    os.chmod(target, 0o600)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ROMarrNG source-bound test inventory and receipt engine")
    parser.add_argument("--plan", action="store_true", help="discover and report without executing native tasks")
    parser.add_argument("--tests-only", action="store_true", help="select registered test tasks")
    parser.add_argument("--task", help="select one registered task")
    parser.add_argument("--json", action="store_true", help="print the complete plan or receipt")
    args = parser.parse_args(argv)
    if args.task and args.tests_only:
        parser.error("--task and --tests-only cannot be combined")
    plan = create_plan(ROOT, {"task": args.task, "tests_only": args.tests_only})
    if args.plan:
        print(json.dumps(plan, indent=2) if args.json else f"{config.REPOSITORY}: {len(plan['inventory'])} test files; {sum(item['selected'] for item in plan['tasks'])} tasks selected; {sum(item['available'] for item in plan['prerequisites'])}/{len(plan['prerequisites'])} commands available")
        return 0
    lock = acquire_lock(ROOT)
    try:
        receipt, run_root, exit_code = execute(
            ROOT,
            plan,
            on_progress=lambda summary: print(summary, file=sys.stderr),
        )
    finally:
        release_lock(lock)
    export_path = os.environ.get("VALIDATION_RECEIPT_EXPORT")
    if export_path:
        export_receipt(receipt, export_path)
    summary = {
        "repository": receipt["repository"],
        "status": receipt["status"],
        "selection": receipt["selection"],
        "planSha256": receipt["planSha256"],
        "totals": receipt["totals"],
        "evidenceDirectory": str(run_root),
    }
    print(json.dumps(receipt if args.json else summary, indent=2))
    return exit_code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValidationError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
