#!/usr/bin/env python3
"""Private workspace setup and lossless Markdown updates; no network or login code."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

SKILL = Path(__file__).resolve().parents[1]
IST = timezone(timedelta(hours=5, minutes=30))
HEADER = "| Applied | Match | Company | Role / ID | Apply link |\n| --- | --- | --- | --- | --- |\n"
DATE = re.compile(r"^## (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) IST$", re.M)
LINK = re.compile(r"\[[^\]]*\]\((https?://[^\s)]+)\)")


def atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".write-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def locked(root: Path) -> Iterator[None]:
    folder = root / ".job-tracker"
    folder.mkdir(parents=True, exist_ok=True)
    lock = folder / "write.lock"
    with lock.open("x", encoding="utf-8") as stream:
        stream.write(str(os.getpid()))
    try:
        yield
    finally:
        lock.unlink()


def canonical(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in {"https", "http"} or not parts.hostname or parts.username:
        raise ValueError("Expected a public job/source HTTP(S) URL without credentials")
    query = [(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith("utm_")]
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path.rstrip("/"),
            urlencode(sorted(query)),
            "",
        )
    )


def cell(text: str) -> str:
    # Escape Markdown controls from job titles and labels, preserving plain text.
    for char in "\\`*_{}[]<>~":
        text = text.replace(char, "\\" + char)
    return " ".join(text.split()).replace("|", "&#124;")


def unstrike(text: str) -> str:
    return text[2:-2] if text.startswith("~~") and text.endswith("~~") else text


def rows(text: str) -> list[tuple[str, list[str]]]:
    found = []
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) != 5:
            raise ValueError("Expected five columns; preserve and repair existing user edits first")
        if re.fullmatch(r"\[[ xX]\]", unstrike(cells[0])):
            found.append((line, cells))
    return found


def urls(cells: list[str]) -> set[str]:
    return {canonical(m) for m in LINK.findall(cells[4])}


def read_lists(root: Path) -> dict[str, str]:
    result = {
        kind: (root / f"{kind}.md").read_text(encoding="utf-8") for kind in ("jobs", "internships")
    }
    for text in result.values():
        rows(text)
        dates = DATE.findall(text)
        if dates != sorted(set(dates), reverse=True):
            raise ValueError("Discovery sections must be unique and newest first")
    return result


def setup(root: Path, host: str) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    created, conflicts = [], []
    templates = {
        name: (SKILL / "assets" / name).read_text(encoding="utf-8")
        for name in ("me.md", "source.md")
    }
    for kind in ("jobs", "internships"):
        templates[f"{kind}.md"] = (
            f"# {kind.title()}\n\n"
            "* = provisional fit or eligibility. Struck rows are confirmed closed.\n"
        )
    with locked(root):
        for name, text in templates.items():
            path = root / name
            if not path.exists():
                atomic(path, text)
                created.append(name)
        # Keep personal data private even if this tracker is in a Git workspace.
        ignore = root / ".gitignore"
        old = ignore.read_text(encoding="utf-8") if ignore.exists() else ""
        entries = [
            "/me.md",
            "/jobs.md",
            "/internships.md",
            "/.job-tracker/",
            "/resume/",
            "*.session",
            "*.session-journal",
            ".env",
            ".env.*",
        ]
        missing = [entry for entry in entries if entry not in old.splitlines()]
        if missing:
            atomic(ignore, old.rstrip() + "\n" + "\n".join(missing) + "\n")
        hosts = ["codex", "claude"] if host == "both" else ([] if host == "none" else [host])
        for target in hosts:
            parent = root / (".claude" if target == "claude" else ".agents") / "skills"
            for mode in ("setup", "scrap", "validate", "repair"):
                path = parent / mode / "SKILL.md"
                content = (
                    f"---\nname: {mode}\ndescription: Run the India software job tracker {mode} workflow in this workspace.\n---\n\n"
                    f"Read [{SKILL.name}](<{(SKILL / 'SKILL.md').as_posix()}>) and follow /{mode}. "
                    "Resolve its references relative to that skill. Tracker root is this workspace. "
                    "If the installed skill moved, locate india-software-jobs or ask for its path; do not guess instructions.\n"
                )
                if path.exists():
                    if path.read_text(encoding="utf-8") != content:
                        conflicts.append(str(path.relative_to(root)))
                else:
                    atomic(path, content)
                    created.append(str(path.relative_to(root)))
    return {
        "created": created,
        "preserved_command_conflicts": conflicts,
        "note": "Profile not filled; access not tested. Use the main skill if a command conflicts.",
    }


def apply(root: Path, payload: dict[str, Any]) -> dict[str, int]:
    """Apply a reviewed batch. Audit is write-ahead; retries deduplicate against Markdown."""
    additions = payload.get("add", [])
    changes = payload.get("status", [])
    discovery = payload.get("discovery", datetime.now(IST).strftime("%Y-%m-%d %H:%M"))
    datetime.strptime(discovery, "%Y-%m-%d %H:%M")
    counts = {"new_jobs": 0, "new_internships": 0, "duplicates": 0, "closed": 0, "reopened": 0}
    with locked(root):
        original = read_lists(root)
        updated = original.copy()
        history = root / ".job-tracker" / "events"
        aliases: dict[str, set[str]] = {}
        for path in sorted(history.glob("*.json")):
            event = json.loads(path.read_text(encoding="utf-8"))
            for item in event.get("request", {}).get("add", []):
                primary = canonical(item["url"])
                aliases.setdefault(primary, set()).update(
                    canonical(u) for u in item.get("aliases", [])
                )
        for item in additions:
            kind = item["kind"]
            if kind not in updated:
                raise ValueError("kind must be jobs or internships")
            for key in ("company", "role", "url", "evidence", "fit", "eligibility", "pay_company"):
                if not item.get(key):
                    raise ValueError(f"Missing reviewed decision field: {key}")
            url = canonical(item["url"])
            incoming = {url, *(canonical(u) for u in item.get("aliases", []))}
            duplicate = False
            company = cell(item["company"])
            role = cell(item["role"])
            for text in updated.values():
                for _, cells in rows(text):
                    existing = urls(cells)
                    for address in list(existing):
                        existing.update(aliases.get(address, set()))
                    same_identity = (
                        unstrike(cells[2]).casefold() == company.casefold()
                        and unstrike(cells[3]).casefold() == role.casefold()
                    )
                    exact_destination = (
                        item.get("exact_link") is True and "unverified" not in cells[4].lower()
                    )
                    if (exact_destination and incoming & existing) or same_identity:
                        duplicate = True
            if duplicate:
                counts["duplicates"] += 1
                continue
            score = item.get("score")
            if score is None:
                match = "Unscored*"
            else:
                maxima = {"skills": 35, "experience": 30, "duties": 20, "eligibility": 15}
                if set(score) != set(maxima) or any(
                    type(score[k]) is not int or not 0 <= score[k] <= v for k, v in maxima.items()
                ):
                    raise ValueError("Invalid match components")
                total = sum(score.values())
                if item.get("evidence_level") == "alert_only" and total > 60:
                    raise ValueError("Alert-only fit is capped at60")
                provisional = (
                    item.get("provisional", True) or item.get("evidence_level") == "alert_only"
                )
                match = f"{total}/100" + ("*" if provisional else "")
            label = item.get("link_label", "Apply")
            if item.get("exact_link", False) is not True and "unverified" not in label.lower():
                raise ValueError("An uncertain link needs an explicit unverified label")
            target = url.replace("(", "%28").replace(")", "%29").replace("|", "%7C")
            line = f"| [ ] | {match} | {company} | {role} | [{cell(label)}]({target}) |\n"
            text = updated[kind]
            heading = f"## {discovery} IST\n"
            marker = heading + "\n" + HEADER
            if heading in text:
                if marker not in text:
                    raise ValueError(
                        "Existing run section differs; merge manually without dropping edits"
                    )
                start = text.index(marker) + len(marker)
                end = start
                for existing_line in text[start:].splitlines(keepends=True):
                    if not existing_line.startswith("|"):
                        break
                    end += len(existing_line)
                text = text[:end].rstrip("\n") + "\n" + line + text[end:]
            else:
                sections = list(DATE.finditer(text))
                insertion = next((m.start() for m in sections if m.group(1) < discovery), len(text))
                text = text[:insertion].rstrip() + "\n\n" + marker + line + "\n" + text[insertion:]
            updated[kind] = text
            aliases.setdefault(url, set()).update(incoming)
            counts[f"new_{kind}"] += 1
        for change in changes:
            state = change["state"]
            if state not in {"closed", "open", "uncertain"}:
                raise ValueError("Invalid availability state")
            evidence = change.get("evidence", {})
            if not all(evidence.get(k) for k in ("url", "observed_at", "reason")):
                raise ValueError("Availability evidence requires url, observed_at and reason")
            if state != "uncertain" and evidence.get("kind") not in (
                {"employer_closed_notice", "employer_deadline_confirmed"}
                if state == "closed"
                else {"employer_accepting_applications"}
            ):
                raise ValueError(
                    "Affirmative employer evidence required; HTTP errors are not closure"
                )
            needle = canonical(change["url"])
            matches = [
                (kind, line, cells)
                for kind, text in updated.items()
                for line, cells in rows(text)
                if (
                    needle in urls(cells)
                    or any(needle in aliases.get(u, set()) for u in urls(cells))
                )
                and (not change.get("role") or unstrike(cells[3]) == cell(change["role"]))
                and (not change.get("company") or unstrike(cells[2]) == cell(change["company"]))
            ]
            if len(matches) != 1:
                raise ValueError("Status target must identify exactly one existing row")
            kind, line, cells = matches[0]
            if state == "uncertain":
                continue
            closed = all(c.startswith("~~") and c.endswith("~~") for c in cells)
            if closed == (state == "closed"):
                continue
            cells = [unstrike(c) for c in cells]
            if state == "closed":
                cells = [f"~~{c}~~" for c in cells]
            updated[kind] = updated[kind].replace(line, "| " + " | ".join(cells) + " |", 1)
            counts["closed" if state == "closed" else "reopened"] += 1
        # Reject malformed updates before writing any list.
        for text in updated.values():
            rows(text)
            if DATE.findall(text) != sorted(set(DATE.findall(text)), reverse=True):
                raise ValueError("Invalid discovery order")
        event_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        event_path = history / f"{event_id}.json"
        event = {"request": payload, "counts": counts, "complete": False}
        atomic(event_path, json.dumps(event, ensure_ascii=False, indent=2) + "\n")
        for kind, text in updated.items():
            if text != original[kind]:
                atomic(root / ".job-tracker" / "backups" / event_id / f"{kind}.md", original[kind])
                atomic(root / f"{kind}.md", text)
        event["complete"] = True
        atomic(event_path, json.dumps(event, ensure_ascii=False, indent=2) + "\n")
    return counts


def check(root: Path) -> dict[str, Any]:
    lists = read_lists(root)
    result: dict[str, Any] = {kind: len(rows(text)) for kind, text in lists.items()}
    result["incomplete_writes"] = [
        p.name
        for p in (root / ".job-tracker/events").glob("*.json")
        if not json.loads(p.read_text(encoding="utf-8")).get("complete")
    ]
    result["sha256"] = {
        kind: hashlib.sha256(text.encode()).hexdigest() for kind, text in lists.items()
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("setup", "apply", "check"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--host", choices=("codex", "claude", "both", "none"), default="none")
    parser.add_argument("--input", type=Path)
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    if args.command == "setup":
        result = setup(root, args.host)
    elif args.command == "apply":
        if not args.input:
            parser.error("apply requires --input reviewed-decisions.json")
        result = apply(root, json.loads(args.input.read_text(encoding="utf-8")))
    else:
        result = check(root)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
