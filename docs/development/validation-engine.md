# Validation engine

ROMarrNG keeps pytest as its test runner and uses a small Python orchestration
layer to record which source and test inventory produced each result.

## Local use

```sh
python3.13 -m scripts.validation_engine.engine --plan --tests-only --json
python3.13 -m scripts.validation_engine.engine --task pytest-suite
python3.13 -m scripts.validation_engine.engine --tests-only
python3.13 -m scripts.validation_engine.engine
```

`--plan` discovers files and required commands without installing packages or
running pytest. An execution creates a disposable Python 3.13 virtual
environment under its private temporary directory, installs the repository
requirements and pytest there, then runs the native suite. The test task uses
`pytest.ini` as configured, including its default `not network`
marker, so tests that reach the public internet remain deselected. The engine
counts passed, skipped, failed, and deselected tests from pytest's summary and
does not call an empty run successful.

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
tasks' declared settings. Each task uses run-owned home, temporary, XDG, and pip
cache directories, and Python user-site packages are disabled. Test children receive
`CI=true`; ambient credentials, Python path injection, proxy settings, and
user configuration paths are not inherited.

The CI job exports a short-lived receipt from the Linux x64 pytest runner. The
image job checks its run ID, attempt, commit, runner identity, case count, and
inventory digest against the image job's own checkout before building an image.
This confirms the artifact came from the current workflow attempt and the same
source snapshot; it does not replace the local test evidence.

The workflow currently installs `requirements.txt` and pytest without a Python
dependency lockfile. The engine binds those manifests and the Python 3.13
runtime, but dependency versions are not yet reproducible from a lockfile.
