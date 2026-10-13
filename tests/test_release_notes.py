from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return result.stdout.strip()


def test_release_tag_check_ignores_future_tags(tmp_path):
    repository = tmp_path / "repository"
    scripts = repository / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(ROOT / "scripts" / "release_notes.py", scripts / "release_notes.py")
    (repository / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [0.14.7] - 2026-10-12\n\nOlder release.\n",
        encoding="utf-8",
    )

    git(repository, "init", "--quiet")
    git(repository, "config", "user.name", "Release Check Test")
    git(repository, "config", "user.email", "release-check@example.invalid")
    git(repository, "add", "scripts/release_notes.py", "CHANGELOG.md")
    git(repository, "commit", "--quiet", "-m", "release v0.14.7")
    git(repository, "tag", "v0.14.7")
    release_head = git(repository, "rev-parse", "HEAD")

    with (repository / "CHANGELOG.md").open("a", encoding="utf-8") as changelog:
        changelog.write("\n## [0.14.8] - 2026-10-13\n\nNewer release.\n")
    git(repository, "add", "CHANGELOG.md")
    git(repository, "commit", "--quiet", "-m", "release v0.14.8")
    git(repository, "tag", "v0.14.8")
    git(repository, "checkout", "--quiet", "--detach", release_head)

    result = subprocess.run(
        [sys.executable, str(scripts / "release_notes.py"), "check-changelog-tags"],
        cwd=repository,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.returncode == 0, result.stderr
    assert "covers all 1 ROMarrNG published release tag(s)" in result.stdout
