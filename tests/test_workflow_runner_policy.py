import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
HOSTED_RUNNERS = {"ubuntu-latest", "macos-latest", "windows-latest"}
TRUSTED_MAIN_CONDITION = (
    "((github.event_name == 'push' && github.ref == 'refs/heads/main') "
    "|| (github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main'))"
)
TRUSTED_MAIN_RUNNER_JSON = '{"group":"trusted-main","labels":["self-hosted","Linux","X64","host"]}'
TRUSTED_MAIN_RUNNER = (
    "$" + "{{ (" + TRUSTED_MAIN_CONDITION
    + " && vars.TRUSTED_MAIN_RUNNERS_ENABLED == 'true' "
    + "&& fromJSON('" + TRUSTED_MAIN_RUNNER_JSON + "')) || 'ubuntu-latest' }}"
)


PUBLIC_FORK_VALIDATION_RUNNER = (
    "$" + "{{ github.event_name == 'pull_request' "
    "&& github.event.pull_request.head.repo.fork == true "
    "&& github.event.pull_request.head.repo.full_name != github.event.pull_request.base.repo.full_name "
    "&& github.event.pull_request.base.repo.full_name == 'snapetech-org/ROMarrNG' "
    "&& github.event.pull_request.base.ref == 'main' "
    "&& fromJSON('{\"group\":\"public-fork-jit\",\"labels\":[\"self-hosted\",\"linux\",\"x64\",\"public-pr-romarrng\"]}') "
    "|| 'ubuntu-latest' }}"
)
GVISOR_SANDBOX_RUNNER = {"group": "gvisor-sandbox", "labels": "gvisor-sandbox"}
PUBLIC_FORK_CALLER_CONDITION = (
    "github.event.pull_request.head.repo.fork == true && "
    "github.event.pull_request.head.repo.full_name != github.event.pull_request.base.repo.full_name && "
    "github.event.pull_request.base.repo.full_name == 'snapetech-org/ROMarrNG' && "
    "github.event.pull_request.base.ref == 'main'"
)
PUBLIC_FORK_CALLER_USES = (
    "snapetech-org/ROMarrNG/.github/workflows/fork-safe-validation.yml"
    "@5e8027f52c89f8089d13b97c5cd54a10998134ad"
)


def _is_approved_public_fork_caller(
    workflow: Path, job_name: str, job: dict, document: dict
) -> bool:
    workflow_events = document.get("on")
    if workflow_events is None:
        workflow_events = document.get(True)
    pull_request = {
        "branches": ["main"],
        "types": ["opened", "synchronize", "reopened", "ready_for_review"],
    }
    expected_concurrency = {
        "group": "public-fork-pr-" + "$" + "{{ github.event.pull_request.number }}",
        "cancel-in-progress": True,
    }
    return (
        workflow.name == "public-fork-pr.yml"
        and job_name == "validate"
        and set(document) == {"name", True, "permissions", "concurrency", "jobs"}
        and document.get("name") == "ROMarrNG fork PR validation"
        and workflow_events == {"pull_request": pull_request}
        and document.get("permissions") == {"contents": "read"}
        and document.get("concurrency") == expected_concurrency
        and set(job) == {"name", "if", "permissions", "uses"}
        and job.get("name") == "Run disposable fork validation"
        and job.get("if") == PUBLIC_FORK_CALLER_CONDITION
        and job.get("permissions") == {"contents": "read"}
        and job.get("uses") == PUBLIC_FORK_CALLER_USES
    )


def _is_approved_gvisor_sandbox_job(
    workflow: Path, job_name: str, job: dict, document: dict
) -> bool:
    workflow_events = document.get("on")
    if workflow_events is None and True in document:
        workflow_events = document[True]
    return (
        workflow.name == "gvisor-runner-smoke.yml"
        and job_name == "smoke"
        and document.get("name") == "gVisor runner smoke"
        and workflow_events == {"workflow_dispatch": None}
        and document.get("permissions") == {}
        and set(job) == {"if", "timeout-minutes", "runs-on", "steps"}
        and job.get("if") == "github.ref == 'refs/heads/main'"
        and job.get("timeout-minutes") == 5
        and job.get("runs-on") == GVISOR_SANDBOX_RUNNER
    )


def _runner_policy_violations(workflow_dir: Path) -> list[str]:
    workflow_files = sorted(
        path
        for suffix in ("*.yml", "*.yaml")
        for path in workflow_dir.glob(suffix)
        if path.is_file()
    )
    if not workflow_files:
        return ["workflow files must be present"]

    violations: list[str] = []
    runner_count = 0
    for workflow in workflow_files:
        document = yaml.safe_load(workflow.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            violations.append(f"{workflow.name}: workflow must be a YAML mapping")
            continue

        jobs = document.get("jobs")
        if not isinstance(jobs, dict):
            violations.append(f"{workflow.name}: jobs must be a YAML mapping")
            continue

        for job_name, job in jobs.items():
            if not isinstance(job, dict):
                violations.append(
                    f"{workflow.name}/{job_name}: job must be a YAML mapping"
                )
                continue
            if "uses" in job and "runs-on" not in job:
                if _is_approved_public_fork_caller(workflow, job_name, job, document):
                    runner_count += 1
                    continue
                violations.append(
                    f"{workflow.name}/{job_name}: reusable workflow runner is not "
                    "visible in this file"
                )
                continue

            runner = job.get("runs-on")
            runner_count += 1
            location = f"{workflow.name}/{job_name}"
            if _is_approved_gvisor_sandbox_job(workflow, job_name, job, document):
                continue
            if (
                workflow.name == "fork-safe-validation.yml"
                and job_name == "validate"
                and runner == PUBLIC_FORK_VALIDATION_RUNNER
            ):
                continue
            if (
                workflow.name == "docker.yml"
                and job_name == "test"
                and runner == TRUSTED_MAIN_RUNNER
            ):
                continue
            if runner == "ubuntu-latest":
                continue
            if runner == "${{ matrix.os }}":
                strategy = job.get("strategy")
                matrix = strategy.get("matrix") if isinstance(strategy, dict) else None
                matrix_os = matrix.get("os") if isinstance(matrix, dict) else None
                if (
                    isinstance(matrix_os, list)
                    and matrix_os
                    and all(
                        isinstance(label, str) and label in HOSTED_RUNNERS
                        for label in matrix_os
                    )
                    and "include" not in matrix
                ):
                    continue
                violations.append(
                    f"{location}: matrix.os must contain only hosted runner labels"
                )
                continue

            violations.append(
                f"{location}: unsupported runner assignment {runner!r}; "
                "public workflows must use hosted runners except for the exact trusted-main or external-fork JIT job"
            )

    if runner_count == 0:
        violations.append("no checked-in workflow runner assignments were found")
    return violations


class WorkflowRunnerPolicyTests(unittest.TestCase):
    def test_dependency_review_runs_use_pull_request_scoped_cancellation(self) -> None:
        workflow = yaml.safe_load(
            (WORKFLOW_DIR / "dependency-review.yml").read_text(encoding="utf-8")
        )

        self.assertEqual(
            workflow["concurrency"],
            {
                "group": "${{ github.workflow }}-${{ github.event.pull_request.number || github.run_id }}",
                "cancel-in-progress": True,
            },
        )

    def test_public_workflows_use_hosted_runners_except_exact_runner_groups(self) -> None:
        self.assertEqual(
            _runner_policy_violations(WORKFLOW_DIR),
            [],
            "only the exact trusted-main, external-fork JIT, or main-only gVisor smoke job may select runner groups",
        )

    def test_fork_jit_runner_is_rejected_outside_the_approved_workflow(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workflow_dir = Path(temporary_directory)
            (workflow_dir / "unrelated.yml").write_text(
                yaml.safe_dump(
                    {"jobs": {"validate": {"runs-on": PUBLIC_FORK_VALIDATION_RUNNER}}},
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            violations = _runner_policy_violations(workflow_dir)

        self.assertEqual(len(violations), 1)
        self.assertIn("unsupported runner assignment", violations[0])

    def test_fork_jit_runner_requires_the_exact_approval_condition(self) -> None:
        unsafe_runner = PUBLIC_FORK_VALIDATION_RUNNER.replace(
            "github.event.pull_request.base.ref == 'main'",
            "github.event.pull_request.base.ref != 'main'",
        )
        with tempfile.TemporaryDirectory() as temporary_directory:
            workflow_dir = Path(temporary_directory)
            (workflow_dir / "fork-safe-validation.yml").write_text(
                yaml.safe_dump(
                    {"jobs": {"validate": {"runs-on": unsafe_runner}}},
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            violations = _runner_policy_violations(workflow_dir)

        self.assertEqual(len(violations), 1)
        self.assertIn("unsupported runner assignment", violations[0])

    def test_quoted_runner_key_in_yaml_file_is_checked(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workflow_dir = Path(temporary_directory)
            (workflow_dir / "quoted-runner.yaml").write_text(
                "name: runner policy regression\n"
                "on: push\n"
                "jobs:\n"
                "  test:\n"
                "    \"runs-on\": self-hosted\n"
                "    steps: []\n",
                encoding="utf-8",
            )

            violations = _runner_policy_violations(workflow_dir)

        self.assertEqual(len(violations), 1)
        self.assertIn("unsupported runner assignment 'self-hosted'", violations[0])

    def test_matrix_include_cannot_add_a_persistent_runner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workflow_dir = Path(temporary_directory)
            (workflow_dir / "matrix.yml").write_text(
                "jobs:\n"
                "  test:\n"
                "    runs-on: ${{ matrix.os }}\n"
                "    strategy:\n"
                "      matrix:\n"
                "        os: [ubuntu-latest]\n"
                "        include:\n"
                "          - os: self-hosted\n",
                encoding="utf-8",
            )

            violations = _runner_policy_violations(workflow_dir)

        self.assertEqual(len(violations), 1)
        self.assertIn("matrix.os must contain only hosted runner labels", violations[0])


if __name__ == "__main__":
    unittest.main()
