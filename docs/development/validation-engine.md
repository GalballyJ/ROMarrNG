# Validation engine

ROMarrNG keeps pytest as its test runner and uses a small Python orchestration
layer to record which source and test inventory produced each result.

## Local use

```sh
node /path/to/trusted-test-launcher.mjs "$PWD" -- python3.13 -m pytest tests/ -q
```

The local command runs an already-configured Python 3.13 environment inside the
trusted, offline Linux bubblewrap launcher. Have pytest and `requirements.txt`
dependencies installed in that environment before running it; the launcher
does not install candidate dependencies or inherit package-index credentials.
When evaluating an unreviewed branch, copy `trusted-test-launcher.mjs` from a
reviewed revision to a location outside the checkout. Its default command is
the same pytest invocation:

```sh
node /path/to/trusted-test-launcher.mjs "$PWD"
```

The launcher has no network access. It copies candidate files into a temporary
workspace without `.git` or local secrets, makes the host filesystem read-only,
and masks common user-data locations. Run planning for an unreviewed candidate
through it too, because planning imports candidate validation configuration.
GitHub Actions remains responsible for receipt-backed hosted validation.

In CI, `--plan` discovers files and required commands without installing
packages or running pytest. Pull requests, version-tag pushes, and manual runs
targeting refs other than `main` use GitHub-hosted Ubuntu. Same-repository
branch pushes and manual runs targeting `main` use whichever repository-local
Linux runner is available (`kspld0` or `kspls0`). The hosted jobs
use `setup-python`; the local job provisions Python 3.13 with a disposable uv
virtualenv under the runner's private temporary directory. Both paths use the
same validation engine, which installs repository requirements and pytest in
a task environment before running the native suite. The test task uses
`pytest.ini` as configured, including its default `not network`
marker, so tests that reach the public internet remain deselected. The engine
counts passed, skipped, failed, and deselected tests from pytest's summary and
does not call an empty run successful.

Pull-request image jobs smoke-test the Alpine image and build the browser
image for its supported platforms, all with read-only repository permissions.
Separate publishing jobs receive registry
write and OIDC attestation permissions only for pushes to `main`, version
tags, or manual runs targeting `main`. The release job runs only for version
tags after both published images succeed.

The engine writes a compact task summary to stderr at task start and completion,
with a once-per-minute heartbeat during long tasks. Counts cover completed
tasks; the active task and elapsed time are shown separately. GitHub publishes
workflow step summaries after the step finishes, so live progress appears in
the step log.

Each run uses a new private temporary directory for its receipt and hashed
pytest log. The candidate fingerprint includes the Git commit/tree and diff,
untracked files, the discovered `tests/test_*.py` file hashes, and the test
workflow, pytest configuration, and requirements input digests. A change during
execution blocks the result. No result cache is reused.

Runtime probes and child commands receive only an inherited allowlist for
executable paths, platform process variables, locale, and timezone, plus child
tasks' declared settings. Proxy, private-index, and custom CA settings are
passed only to the dependency-install task; pytest never receives them. Each
task uses run-owned home, temporary, XDG, and pip cache directories, and Python
user-site packages are disabled. Test children receive `CI=true`; ambient
credentials, Python path injection, and user configuration paths are not
inherited. On Linux the runner also disables procfs access to its own process
environment while a task child is running. This requires a non-root runner
without `CAP_SYS_PTRACE`; the engine refuses to start a task when that boundary
cannot be enforced or the runner's original dumpability state cannot be
restored.

The CI job exports a short-lived receipt from the Linux x64 pytest runner. The
image job checks its run ID, attempt, commit, runner identity, case count, and
inventory digest against the image job's own checkout before building an image.
This confirms the artifact came from the current workflow attempt and the same
source snapshot; it does not replace the local test evidence.

The `install-test-dependencies` task runs only in hosted CI. Running the engine's
`--tests-only` selection locally is intentionally refused because it includes
that package-install task; use the trusted launcher with the preconfigured
Python environment instead. The workflow currently installs `requirements.txt`
and pytest without a Python dependency lockfile. The engine binds those
manifests and the Python 3.13 runtime, but dependency versions are not yet
reproducible from a lockfile.
