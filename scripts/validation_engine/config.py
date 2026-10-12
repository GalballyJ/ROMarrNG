"""ROMarrNG's native pytest validation task and its input boundaries."""

REPOSITORY = "romarrng"
INPUTS = (
    ".gitignore",
    "pytest.ini",
    "requirements.txt",
    ".github/workflows/docker.yml",
    "release-notes/README.md",
    "release-notes/20261012-validation-environment-isolation.md",
    "docs/development/validation-engine.md",
    "scripts/validation_engine/__init__.py",
    "scripts/validation_engine/config.py",
    "scripts/validation_engine/engine.py",
    "scripts/validation_engine/reconcile.py",
    "tests/test_validation_engine.py",
    "release-notes/20261011-validation-engine.md",
)
INVENTORY = (
    {
        "id": "pytest-suite",
        "glob": "tests/test_*.py",
        "framework": "pytest",
        "owner": "romarrng-tests",
    },
)
TASKS = (
    {
        "id": "create-test-environment",
        "name": "Create disposable Python test environment",
        "stage": "prepare",
        "kind": "setup",
        "command": ["python3.13", "-m", "venv", "{VENV}"],
        "timeout_seconds": 180,
    },
    {
        "id": "install-test-dependencies",
        "name": "Install pytest dependencies into disposable environment",
        "stage": "prepare",
        "kind": "setup",
        "command": ["{PYTHON}", "-m", "pip", "install", "--disable-pip-version-check", "--no-cache-dir", "-r", "requirements.txt", "pytest"],
        "depends_on": ["create-test-environment"],
        "timeout_seconds": 1200,
    },
    {
        "id": "pytest-suite",
        "name": "Offline pytest suite",
        "stage": "repository",
        "kind": "test",
        "command": ["{PYTHON}", "-m", "pytest", "tests/", "-q"],
        "parser": "pytest",
        "minimum_cases": 1,
        "inventory_lanes": ["pytest-suite"],
        "depends_on": ["install-test-dependencies"],
        "timeout_seconds": 1800,
    },
)
