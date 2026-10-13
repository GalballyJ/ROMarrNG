from pathlib import Path
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
HOSTED_RUNNERS = {"ubuntu-latest", "macos-latest", "windows-latest"}


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
                violations.append(
                    f"{workflow.name}/{job_name}: reusable workflow runner is not "
                    "visible in this file"
                )
                continue

            runner = job.get("runs-on")
            runner_count += 1
            location = f"{workflow.name}/{job_name}"
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
                "public workflows must use hosted runners"
            )

    if runner_count == 0:
        violations.append("no checked-in workflow runner assignments were found")
    return violations


class WorkflowRunnerPolicyTests(unittest.TestCase):
    def test_public_workflows_use_only_hosted_runners(self) -> None:
        self.assertEqual(
            _runner_policy_violations(WORKFLOW_DIR),
            [],
            "public validation must use approved hosted runners",
        )

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
