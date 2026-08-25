#!/usr/bin/env python3
"""Run the complete local and CI validation contract for the skills repository."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"


def run(*arguments: str, cwd: Path = ROOT) -> None:
    command = [sys.executable, *arguments]
    print(f"+ {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def skill_directories() -> list[Path]:
    return sorted(
        (path for path in SKILLS.iterdir() if path.is_dir() and (path / "SKILL.md").is_file()),
        key=lambda path: path.name,
    )


def main() -> int:
    skills = skill_directories()
    if not skills:
        raise RuntimeError("No skills were found")

    run(str(ROOT / "tools" / "validate_repo.py"))
    run("-m", "ruff", "format", "--check", ".")
    run("-m", "ruff", "check", "--no-cache", ".")
    run("-m", "mypy", "--strict", "--no-incremental", str(ROOT / "tools"))

    for skill in skills:
        python_targets = [
            path.name for path in (skill / "scripts", skill / "tests") if path.is_dir()
        ]
        if python_targets:
            run("-m", "mypy", "--strict", "--no-incremental", *python_targets, cwd=skill)
        tests = skill / "tests"
        if tests.is_dir():
            run("-m", "unittest", "discover", "-s", "tests", "-v", cwd=skill)

    print(f"Repository checks passed for {len(skills)} skill(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
