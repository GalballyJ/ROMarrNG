import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
HOSTED_RUNNERS = {"ubuntu-latest", "macos-latest", "windows-latest"}
TRUSTED_MAIN_WORKFLOWS = {
    "docker.yml",
    "semgrep-community.yml",
    "trivy-filesystem.yml",
}
TRUSTED_MAIN_RUNNER_PAYLOAD = (
    "fromJSON(format('{{\"group\":\"ng-shared-main-jit\","
    "\"labels\":[\"self-hosted\",\"linux\",\"x64\","
    "\"ng-shared-main-romarrng\",\"ng-main-run-{0}\"]}}', github.run_id))"
)
TRUSTED_MAIN_EVENT_CONDITIONS = {
    "(github.event_name == 'push' || github.event_name == 'workflow_dispatch') "
    "&& github.ref == 'refs/heads/main'",
    "(github.event_name == 'push' || github.event_name == 'workflow_dispatch' "
    "|| github.event_name == 'schedule') && github.ref == 'refs/heads/main'",
    "(contains(fromJSON('[\"push\",\"workflow_dispatch\",\"schedule\",\"release\",\"repository_dispatch\"]'), github.event_name) "
    "&& (github.ref == 'refs/heads/main' || (github.ref_type == 'tag' && startsWith(github.ref_name, 'v'))))",
}


GVISOR_SANDBOX_RUNNER = {"group": "gvisor-sandbox", "labels": "gvisor-sandbox"}
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


def _is_trusted_main_runner(workflow: Path, runner: object) -> bool:
    if workflow.name not in TRUSTED_MAIN_WORKFLOWS or not isinstance(runner, str):
        return False
    if not (runner.startswith("${{ ") and runner.endswith(" }}")):
        return False

    expression = runner[4:-3]
    expression = expression.removeprefix("(vars.NG_HOSTED_FIRST != 'true' || vars.NG_FORCE_JIT == 'true' || github.run_attempt > 1) && ")
    condition, separator, fallback = expression.partition(
        " && " + TRUSTED_MAIN_RUNNER_PAYLOAD
    )
    if not separator:
        return False
    matrix_runner = condition.startswith("matrix.os == 'ubuntu-latest' && ")
    if matrix_runner:
        condition = condition.removeprefix("matrix.os == 'ubuntu-latest' && ")
    if condition not in TRUSTED_MAIN_EVENT_CONDITIONS:
        return False
    expected_fallback = " || matrix.os" if matrix_runner else " || 'ubuntu-latest'"
    return fallback == expected_fallback


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
            if _is_approved_gvisor_sandbox_job(workflow, job_name, job, document):
                continue
            if _is_trusted_main_runner(workflow, runner):
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

    if runner_count == 0 and not violations:
        violations.append("no checked-in workflow runner assignments were found")
    return violations


class WorkflowRunnerPolicyTests(unittest.TestCase):
    def test_main_and_release_buildkit_use_the_proxy_with_hosted_fallback(self) -> None:
        workflow = yaml.safe_load(
            (WORKFLOW_DIR / "docker.yml").read_text(encoding="utf-8")
        )
        image_job = workflow["jobs"]["image"]
        expected_proxy_gate = (
            "${{ (vars.NG_HOSTED_FIRST != 'true' || vars.NG_FORCE_JIT == 'true' || github.run_attempt > 1) && (contains(fromJSON('[\"push\",\"workflow_dispatch\",\"schedule\",\"release\",\"repository_dispatch\"]'), github.event_name) && (github.ref == 'refs/heads/main' || (github.ref_type == 'tag' && startsWith(github.ref_name, 'v')))) && "
            "'http://10.0.2.100:3128' || '' }}"
        )

        self.assertEqual(
            image_job["env"]["BUILDKIT_EGRESS_PROXY"], expected_proxy_gate
        )
        buildx = next(
            step
            for step in image_job["steps"]
            if "setup-buildx-action" in step.get("uses", "")
        )
        driver_opts = buildx["with"]["driver-opts"]
        for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            self.assertIn(
                f"env.{key}=${{{{ env.BUILDKIT_EGRESS_PROXY }}}}", driver_opts
            )
        self.assertNotIn(",", driver_opts)

        builds = [
            step
            for step in image_job["steps"]
            if "build-push-action" in step.get("uses", "")
        ]
        self.assertEqual(len(builds), 2)
        for build in builds:
            for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
                self.assertIn(
                    f"{key}=${{{{ env.BUILDKIT_EGRESS_PROXY }}}}",
                    build["with"]["build-args"],
                )
            for key in ("NO_PROXY", "no_proxy"):
                self.assertIn(
                    f"{key}=localhost,127.0.0.1",
                    build["with"]["build-args"],
                )

        for job_name in ("image-browser", "image_publish", "image_browser_publish"):
            with self.subTest(job=job_name):
                job = workflow["jobs"][job_name]
                self.assertNotIn("BUILDKIT_EGRESS_PROXY", job.get("env", {}))
                self.assertNotIn("10.0.2.100:3128", str(job))
                if job_name == "image-browser":
                    self.assertIn("github.event_name == 'pull_request'", job["if"])
                    self.assertIn("|| 'ubuntu-latest'", job["runs-on"])

    def test_publishers_and_release_use_the_trusted_runner_route(self) -> None:
        workflow = yaml.safe_load(
            (WORKFLOW_DIR / "docker.yml").read_text(encoding="utf-8")
        )

        for job_name in ("image_publish", "image_browser_publish", "release"):
            with self.subTest(job=job_name):
                self.assertTrue(
                    _is_trusted_main_runner(
                        Path("docker.yml"), workflow["jobs"][job_name]["runs-on"]
                    )
                )

    def test_dependency_review_runs_use_run_scoped_non_cancelling_concurrency(self) -> None:
        workflow = yaml.safe_load(
            (WORKFLOW_DIR / "dependency-review.yml").read_text(encoding="utf-8")
        )

        self.assertEqual(
            workflow["concurrency"],
            {
                "group": "${{ github.workflow }}-${{ github.run_id }}",
                "cancel-in-progress": False,
            },
        )

    def test_public_workflows_use_hosted_runners_except_exact_runner_groups(self) -> None:
        self.assertEqual(
            _runner_policy_violations(WORKFLOW_DIR),
            [],
            "only the exact trusted-main or main-only gVisor smoke job may select runner groups",
        )

    def test_trusted_main_runner_is_scoped_to_this_project_and_run(self) -> None:
        condition = next(iter(TRUSTED_MAIN_EVENT_CONDITIONS))
        valid_runner = (
            "${{ " + condition + " && " + TRUSTED_MAIN_RUNNER_PAYLOAD
            + " || 'ubuntu-latest' }}"
        )

        self.assertTrue(_is_trusted_main_runner(Path("docker.yml"), valid_runner))
        self.assertFalse(_is_trusted_main_runner(Path("unrelated.yml"), valid_runner))
        self.assertFalse(
            _is_trusted_main_runner(
                Path("docker.yml"),
                valid_runner.replace("ng-main-run-{0}", "ng-main-run-123"),
            )
        )
        self.assertFalse(
            _is_trusted_main_runner(
                Path("docker.yml"),
                valid_runner.replace("refs/heads/main", "refs/heads/other"),
            )
        )

    def test_reusable_workflows_must_keep_runner_policy_visible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workflow_dir = Path(temporary_directory)
            (workflow_dir / "reusable.yml").write_text(
                yaml.safe_dump(
                    {"jobs": {"validate": {"uses": "org/repo/.github/workflows/ci.yml@main"}}},
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            violations = _runner_policy_violations(workflow_dir)

        self.assertEqual(len(violations), 1)
        self.assertIn("reusable workflow runner is not visible", violations[0])

    def test_workflow_without_runner_assignments_keeps_the_catch_all_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            workflow_dir = Path(temporary_directory)
            (workflow_dir / "empty-jobs.yml").write_text(
                "jobs: {}\n",
                encoding="utf-8",
            )

            violations = _runner_policy_violations(workflow_dir)

        self.assertEqual(
            violations,
            ["no checked-in workflow runner assignments were found"],
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

