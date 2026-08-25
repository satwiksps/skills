#!/usr/bin/env python3
"""Validate public repository structure and skill metadata without exposing file content."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any, cast

import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
REQUIRED_ROOT_FILES = (
    "README.md",
    "LICENSE",
    "NOTICE",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
)
PRIVATE_FILENAMES = {"idea.md", "plan.md"}
CACHE_DIRECTORIES = {"__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
TEXT_SUFFIXES = {
    "",
    ".cff",
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".py",
    ".svg",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
WINDOWS_ABSOLUTE_PATH = re.compile(r"(?i)(?<![a-z0-9])[a-z]:[\\/][^\s`\"'<>]+")
SAFE_WINDOWS_EXAMPLE_PREFIXES = ("c:/path/to/",)


def publication_paths() -> list[Path]:
    """Return tracked and non-ignored untracked files that could enter a commit."""
    result = subprocess.run(
        [
            "git",
            "-C",
            str(ROOT),
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ],
        check=True,
        capture_output=True,
    )
    return [ROOT / Path(item.decode("utf-8")) for item in result.stdout.split(b"\0") if item]


def contains_local_path(text: str) -> bool:
    normalized = text.casefold().replace("\\", "/")
    dynamic_markers = {
        str(Path.home()).casefold().replace("\\", "/"),
        str(ROOT).casefold().replace("\\", "/"),
    }
    if any(marker and marker in normalized for marker in dynamic_markers):
        return True
    return any(
        not match.group(0).casefold().replace("\\", "/").startswith(SAFE_WINDOWS_EXAMPLE_PREFIXES)
        for match in WINDOWS_ABSOLUTE_PATH.finditer(text)
    )


def load_yaml(path: Path, text: str) -> dict[str, Any]:
    value: object = yaml.safe_load(text)
    if not isinstance(value, dict):
        raise ValueError(f"{path.relative_to(ROOT)} must contain a YAML mapping")
    return cast(dict[str, Any], value)


def read_skill_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise ValueError(f"{path.relative_to(ROOT)} must start with YAML frontmatter")
    try:
        boundary = lines.index("---", 1)
    except ValueError as error:
        raise ValueError(f"{path.relative_to(ROOT)} has unclosed frontmatter") from error
    body = "\n".join(lines[boundary + 1 :]).strip()
    if not body:
        raise ValueError(f"{path.relative_to(ROOT)} has an empty instruction body")
    return load_yaml(path, "\n".join(lines[1:boundary])), body


def normalized_license(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").rstrip() + "\n"


def validate_skill(skill: Path, root_license: str) -> list[str]:
    issues: list[str] = []
    skill_file = skill / "SKILL.md"
    try:
        metadata, _ = read_skill_frontmatter(skill_file)
    except (OSError, UnicodeError, ValueError) as error:
        return [str(error)]

    name = metadata.get("name")
    description = metadata.get("description")
    if name != skill.name or not isinstance(name, str) or NAME_PATTERN.fullmatch(name) is None:
        issues.append(f"{skill_file.relative_to(ROOT)} has an invalid or mismatched name")
    if not isinstance(description, str) or not description.strip() or len(description) > 1024:
        issues.append(f"{skill_file.relative_to(ROOT)} has an invalid description")

    agent_file = skill / "agents" / "openai.yaml"
    if agent_file.is_file():
        try:
            agent = load_yaml(agent_file, agent_file.read_text(encoding="utf-8"))
            interface = agent.get("interface")
            if not isinstance(interface, dict):
                issues.append(f"{agent_file.relative_to(ROOT)} is missing interface metadata")
            else:
                prompt = interface.get("default_prompt")
                if not isinstance(prompt, str) or f"${skill.name}" not in prompt:
                    issues.append(
                        f"{agent_file.relative_to(ROOT)} default_prompt must invoke ${skill.name}"
                    )
        except (OSError, UnicodeError, ValueError) as error:
            issues.append(str(error))

    apache_asset = skill / "assets" / "APACHE-2.0.txt"
    if apache_asset.is_file() and normalized_license(apache_asset) != root_license:
        issues.append(f"{apache_asset.relative_to(ROOT)} differs from the repository LICENSE")
    if not (skill / "tests").is_dir():
        issues.append(f"{skill.relative_to(ROOT)} has no tests directory")
    return issues


def repository_issues() -> list[str]:
    issues: list[str] = []
    for required in REQUIRED_ROOT_FILES:
        if not (ROOT / required).is_file():
            issues.append(f"Missing required repository file: {required}")

    if not SKILLS.is_dir():
        return [*issues, "Missing skills directory"]

    for path in publication_paths():
        relative = path.relative_to(ROOT)
        if any(part in CACHE_DIRECTORIES for part in relative.parts):
            issues.append(f"Generated cache directory is present: {relative}")
            continue
        if not path.is_file():
            continue
        if path.name.casefold() in PRIVATE_FILENAMES:
            issues.append(f"Private planning filename is present: {relative}")
        if path.suffix.casefold() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeError:
            continue
        if "\N{EM DASH}" in text:
            issues.append(f"Unicode em dash is present: {relative}")
        if contains_local_path(text):
            issues.append(f"Local machine path is present: {relative}")

    root_license = normalized_license(ROOT / "LICENSE")
    skills = sorted(
        (path for path in SKILLS.iterdir() if path.is_dir()), key=lambda path: path.name
    )
    if not skills:
        issues.append("No skill directories were found")
    for skill in skills:
        if not (skill / "SKILL.md").is_file():
            issues.append(f"Skill directory has no SKILL.md: {skill.relative_to(ROOT)}")
            continue
        issues.extend(validate_skill(skill, root_license))
    return issues


def main() -> int:
    issues = repository_issues()
    if issues:
        print(f"Repository validation failed with {len(issues)} issue(s):")
        for issue in issues:
            print(f"  ERROR: {issue}")
        return 1
    skill_count = sum(1 for path in SKILLS.iterdir() if (path / "SKILL.md").is_file())
    print(f"Repository validation passed for {skill_count} skill(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
