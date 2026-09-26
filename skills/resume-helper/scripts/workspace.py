#!/usr/bin/env python3
"""Remember resume roots and inventory files without modifying resume contents."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

STATE = ".resume-helper"
VERSION = 1
SKIP = {"node_modules", "__pycache__", "venv", "tmp", "build"}


def read_json(path: Path) -> dict[str, Any]:
    value: Any = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict) or type(value.get("schema_version")) is not int:
        raise ValueError(f"Invalid state object: {path}")
    if value["schema_version"] != VERSION:
        raise ValueError(f"Unsupported schema version in {path}; do not reset it")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
        ) as output:
            temporary = Path(output.name)
            json.dump(value, output, indent=2, ensure_ascii=False, allow_nan=False)
            output.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def inside(root: Path, relative: str) -> Path:
    path = root / relative
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Path leaves the resume workspace: {relative}")
    return path


def registry_path() -> Path:
    configured = os.environ.get("RESUME_HELPER_HOME")
    directory = (
        Path(configured).expanduser() if configured else Path.home() / ".config/resume-helper"
    )
    return directory.resolve() / "workspaces.json"


def remember(root: Path) -> None:
    path = registry_path()
    value = read_json(path) if path.exists() else {"schema_version": VERSION, "roots": []}
    roots = value.get("roots")
    if not isinstance(roots, list) or not all(isinstance(item, str) for item in roots):
        raise ValueError(f"Invalid workspace registry: {path}")
    if str(root) not in roots:
        roots.append(str(root))
    value["active_root"] = str(root)
    write_json(path, value)


def read_profile(root: Path) -> dict[str, Any]:
    profile = read_json(inside(root, f"{STATE}/profile.json"))
    if "baseline" not in profile or "baseline_sha256" not in profile:
        raise ValueError("Profile is missing baseline fields; do not reset it")
    if profile.get("baseline") is not None and not isinstance(profile["baseline"], str):
        raise ValueError("Profile baseline must be a relative path or null")
    for field, expected in (("preferences", dict), ("skills", list), ("projects", list)):
        if not isinstance(profile.get(field), expected):
            raise ValueError(f"Invalid profile field: {field}")
    return profile


def locate(explicit: str | None = None, cwd: Path | None = None) -> Path:
    if explicit is not None:
        root = Path(explicit).expanduser().resolve()
    else:
        current = (cwd or Path.cwd()).resolve()
        local = next(
            (
                path
                for path in (current, *current.parents)
                if (path / STATE / "profile.json").is_file()
            ),
            None,
        )
        if local is not None:
            root = local
        else:
            path = registry_path()
            if not path.is_file():
                raise ValueError("No saved workspace; ask for a resume folder and run setup")
            registry = read_json(path)
            selected = registry.get("active_root")
            if not isinstance(selected, str) or not selected:
                raise ValueError("No active workspace; ask the user to select a folder")
            root = Path(selected).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Selected workspace is missing: {root}; ask for its new location")
    read_profile(root)
    return root


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def initialize(root: Path, base: str | None = None, replace_base: bool = False) -> dict[str, Any]:
    root = root.expanduser().resolve()
    profile_path = inside(root, f"{STATE}/profile.json")
    profile = read_profile(root) if profile_path.exists() else None
    selected: str | None = None
    if replace_base and base is None:
        raise ValueError("--replace-base requires --base")
    if base is not None:
        candidate = Path(base).expanduser()
        candidate = candidate if candidate.is_absolute() else root / candidate
        if candidate.is_symlink() or not candidate.resolve().is_relative_to(root):
            raise ValueError(
                "Base must be inside the resume folder; import it and its assets first"
            )
        candidate = candidate.resolve()
        if not candidate.is_file() or candidate.suffix.lower() not in {".tex", ".pdf"}:
            raise ValueError("Base must be an existing .tex or .pdf file")
        selected = candidate.relative_to(root).as_posix()
        if profile and profile.get("baseline") not in (None, selected) and not replace_base:
            raise ValueError(
                "Base already selected; use --replace-base only for an explicit change"
            )

    # Validate every generated destination before creating or changing anything.
    for child in ("tex", "pdf", STATE, f"{STATE}/context.md", f"{STATE}/runs"):
        target = inside(root, child)
        if target.exists() and child != f"{STATE}/context.md" and not target.is_dir():
            raise ValueError(f"Expected a directory: {target}")
        if child == f"{STATE}/context.md" and target.exists() and not target.is_file():
            raise ValueError(f"Expected a context file: {target}")
    registry = registry_path()
    if registry.exists():
        saved = read_json(registry)
        if not isinstance(saved.get("roots"), list) or not all(
            isinstance(item, str) for item in saved["roots"]
        ):
            raise ValueError("Invalid registry; preserve it and resolve the error first")

    for directory in ("tex", "pdf", f"{STATE}/runs"):
        inside(root, directory).mkdir(parents=True, exist_ok=True)
    if profile is None:
        profile = {
            "schema_version": VERSION,
            "baseline": None,
            "baseline_sha256": None,
            "preferences": {
                "project_slots": 3,
                "edit_mode": "suggest",
                "skill_categories": [],
                "section_order": [],
                "page_target": None,
            },
            "projects": [],
            "skills": [],
        }
    if selected is not None and (profile["baseline"] is None or replace_base):
        profile["baseline"] = selected
        profile["baseline_sha256"] = digest(inside(root, selected))
    write_json(profile_path, profile)
    context = inside(root, f"{STATE}/context.md")
    if not context.exists():
        context.write_text(
            "# Resume context\n\n## Confirmed preferences\n\n"
            "## Reusable decisions\n\n## Unresolved questions\n",
            encoding="utf-8",
        )
    remember(root)
    return {"root": str(root), "profile": profile, "registry": str(registry_path())}


def scan(root: Path) -> dict[str, Any]:
    root = root.expanduser().resolve()
    profile = read_profile(root)
    inventory_path = inside(root, f"{STATE}/inventory.json")
    previous = read_json(inventory_path) if inventory_path.exists() else {}
    old_entries = previous.get("files", [])
    if not isinstance(old_entries, list) or not all(
        isinstance(item, dict) and isinstance(item.get("path"), str) for item in old_entries
    ):
        raise ValueError("Invalid inventory; preserve it and resolve the error first")
    old = {item["path"]: item.get("sha256") for item in old_entries}
    files: list[dict[str, Any]] = []
    errors: list[str] = []

    def walk_error(error: OSError) -> None:
        errors.append(f"Cannot scan directory: {error.filename}: {error.strerror}")

    for parent, directories, names in os.walk(root, followlinks=False, onerror=walk_error):
        parent_path = Path(parent)
        directories[:] = sorted(
            name
            for name in directories
            if not name.startswith(".")
            and name not in SKIP
            and not (parent_path / name).is_symlink()
            and (parent_path / name).resolve().is_relative_to(root)
        )
        for name in sorted(names):
            path = parent_path / name
            if path.suffix.lower() not in {".tex", ".pdf"} or path.is_symlink():
                continue
            if not path.resolve().is_relative_to(root):
                continue
            relative = path.relative_to(root).as_posix()
            try:
                stat = path.stat()
                files.append(
                    {
                        "path": relative,
                        "size": stat.st_size,
                        "mtime_ns": stat.st_mtime_ns,
                        "sha256": digest(path),
                    }
                )
            except OSError as error:
                errors.append(f"{relative}: {error.strerror}")
    current = {item["path"]: item["sha256"] for item in files}
    baseline = profile.get("baseline")
    if baseline is not None:
        inside(root, baseline)
    result = {
        "schema_version": VERSION,
        "files": sorted(files, key=lambda item: item["path"]),
        "changed": sorted(path for path, sha in current.items() if old.get(path) != sha),
        "removed": sorted(set(old) - set(current)),
        "errors": errors,
        "baseline": baseline,
        "baseline_missing": baseline is not None and baseline not in current,
        "baseline_changed": baseline in current
        and current[baseline] != profile.get("baseline_sha256"),
    }
    # Failed reads must not erase a previously useful snapshot.
    if not errors:
        write_json(inventory_path, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser(
        "init", help="Create/preserve workspace state and remember the folder"
    )
    setup.add_argument("--root", required=True)
    setup.add_argument("--base")
    setup.add_argument("--replace-base", action="store_true")
    for command in ("locate", "scan"):
        command_parser = commands.add_parser(command)
        command_parser.add_argument("--root")
    args = parser.parse_args()
    try:
        if args.command == "init":
            result = initialize(Path(args.root), args.base, args.replace_base)
        else:
            root = locate(args.root)
            result = scan(root) if args.command == "scan" else {"root": str(root)}
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 1 if result.get("errors") else 0
    except (OSError, ValueError) as error:
        print(f"resume-helper: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
