#!/usr/bin/env python3
"""Audit project-authored text for release-blocking prose and secret risks."""

from __future__ import annotations

import argparse
import codecs
import fnmatch
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

GIT_PROGRAM: str | None = None
GIT_PROGRAM_IDENTITY: tuple[int, int, int, int, int] | None = None
MAX_LOCAL_GIT_CONTROL_BYTES = 1_000_000

DEFAULT_EXCLUDES = (
    ".git/**",
    "node_modules/**",
    "vendor/**",
    "dist/**",
    "build/**",
    "coverage/**",
    "htmlcov/**",
    "docs/_build/**",
)
GIT_ENVIRONMENT_OVERRIDES = {
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_ATTR_SOURCE",
    "GIT_CEILING_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_CONFIG",
    "GIT_CONFIG_COUNT",
    "GIT_CONFIG_GLOBAL",
    "GIT_CONFIG_NOSYSTEM",
    "GIT_CONFIG_PARAMETERS",
    "GIT_CONFIG_SYSTEM",
    "GIT_DIR",
    "GIT_DISCOVERY_ACROSS_FILESYSTEM",
    "GIT_EXEC_PATH",
    "GIT_INDEX_FILE",
    "GIT_NAMESPACE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_REPLACE_REF_BASE",
    "GIT_SHALLOW_FILE",
    "GIT_WORK_TREE",
}

PLACEHOLDER_PATTERNS = {
    "unresolved TODO": re.compile(r"\b(?:TODO|FIXME|XXX)\b", re.IGNORECASE),
    "template marker": re.compile(
        r"(?:REPLACE[_ -]?ME|YOUR[_ -]?(?:USERNAME|ORG|ORGANIZATION|NAME)|"
        r"<PROJECT[_ -]?NAME>|\{\{\s*PROJECT[_ -]?NAME\s*\}\}|OWNER/REPO|example\.invalid)",
        re.IGNORECASE,
    ),
    "placeholder prose": re.compile(
        r"(?:lorem ipsum|coming soon|insert .{0,30} here)", re.IGNORECASE
    ),
    "AI attribution": re.compile(
        r"(?:generated (?:by|with) (?:AI|ChatGPT|Claude|Codex)|AI-generated)",
        re.IGNORECASE,
    ),
    "unsupported marketing phrase": re.compile(
        r"\b(?:revolutionary|effortless|seamless(?:ly)?|cutting-edge|enterprise-ready|"
        r"production-grade|blazing fast)\b",
        re.IGNORECASE,
    ),
}

SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\bgh[opsu]_[A-Za-z0-9]{20,}\b"),
    "PyPI token": re.compile(r"\bpypi-[A-Za-z0-9_-]{20,}\b"),
    "npm token": re.compile(r"\bnpm_[A-Za-z0-9]{20,}\b"),
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "generic bearer token": re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{24,}=*\b", re.IGNORECASE),
}

CONFLICT_PATTERNS = {
    "merge conflict marker": re.compile(r"^(?:<{7}|={7}|>{7})(?:\s|$)", re.MULTILINE),
}

TEXT_SUFFIXES = {
    "",
    ".c",
    ".cfg",
    ".conf",
    ".cpp",
    ".cs",
    ".css",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".kt",
    ".md",
    ".mjs",
    ".php",
    ".properties",
    ".py",
    ".rb",
    ".rs",
    ".sh",
    ".swift",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    category: str
    source: str


def git_environment() -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("GIT_")
        and key.upper()
        not in {"SSH_ASKPASS", "SSH_ASKPASS_REQUIRE", "PAGER", "EDITOR", "VISUAL", "LESS", "LV"}
    }
    environment.update(
        {
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        }
    )
    return environment


def terminal_safe(value: str) -> str:
    """Escape control and non-ASCII characters before writing audit logs."""
    redacted = value
    for pattern in SECRET_PATTERNS.values():
        redacted = pattern.sub("<redacted secret>", redacted)
    if re.search(
        r"\b(?:codename|confidential|internal|private|secret|unreleased)\b", redacted, re.I
    ):
        redacted = "<redacted sensitive diagnostic>"
    return json.dumps(redacted, ensure_ascii=True)[1:-1]


def parse_absolute_program(value: str) -> str:
    path = Path(value).expanduser()
    if not path.is_absolute() or not path.is_file():
        raise argparse.ArgumentTypeError("Expected an absolute path to an existing program")
    return str(path.resolve())


def executable_identity(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def verify_git_program(
    path_value: str, approved_sha256: str
) -> tuple[str, tuple[int, int, int, int, int]]:
    path = Path(path_value).resolve(strict=True)
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or not os.access(path, os.X_OK):
        raise RuntimeError("approved Git executable must be a regular executable")
    if any(ord(character) < 32 or ord(character) == 127 for character in str(path)):
        raise RuntimeError("approved Git executable path contains a control character")
    digest = hashlib.sha256()
    before = executable_identity(metadata)
    with path.open("rb") as handle:
        opened = executable_identity(os.fstat(handle.fileno()))
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
        after_open = executable_identity(os.fstat(handle.fileno()))
    after_path = executable_identity(path.lstat())
    if before != opened or opened != after_open or after_open != after_path:
        raise RuntimeError("approved Git executable changed while its SHA-256 was verified")
    if digest.hexdigest() != approved_sha256:
        raise RuntimeError("approved Git executable SHA-256 does not match")
    return str(path), after_path


def parse_sha256(value: str) -> str:
    digest = value.strip().casefold()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise argparse.ArgumentTypeError("Expected a 64-digit SHA-256 digest")
    return digest


def run_git(repo: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    if GIT_PROGRAM is None or GIT_PROGRAM_IDENTITY is None:
        raise RuntimeError("A trusted absolute Git executable has not been configured")
    try:
        observed_identity = executable_identity(Path(GIT_PROGRAM).lstat())
    except OSError as error:
        raise RuntimeError("The approved Git executable is no longer available") from error
    if observed_identity != GIT_PROGRAM_IDENTITY:
        raise RuntimeError("The approved Git executable changed after verification")
    result = subprocess.run(
        [
            GIT_PROGRAM,
            "-C",
            str(repo),
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.hooksPath=",
            *arguments,
        ],
        check=False,
        capture_output=True,
        env=git_environment(),
    )
    try:
        observed_after = executable_identity(Path(GIT_PROGRAM).lstat())
    except OSError as error:
        raise RuntimeError("The approved Git executable is no longer available") from error
    if observed_after != GIT_PROGRAM_IDENTITY:
        raise RuntimeError("The approved Git executable changed after verification")
    return result


def repository_root(candidate: Path) -> Path:
    result = run_git(candidate, "rev-parse", "--show-toplevel")
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(detail or "Could not locate the Git worktree")
    return Path(result.stdout.decode("utf-8", errors="surrogateescape").strip()).resolve()


def path_is_within(path: Path, directory: Path) -> bool:
    try:
        common = os.path.commonpath((str(path.resolve()), str(directory.resolve())))
    except ValueError:
        return False
    return os.path.normcase(common) == os.path.normcase(str(directory.resolve()))


def detectable_worktree_root(candidate: Path) -> Path | None:
    current = candidate
    while not current.exists() and current != current.parent:
        current = current.parent
    if current.is_file():
        current = current.parent
    while True:
        try:
            (current / ".git").lstat()
        except FileNotFoundError:
            pass
        except OSError as error:
            raise RuntimeError("Could not inspect the candidate worktree boundary") from error
        else:
            return current.resolve()
        if current == current.parent:
            return None
        current = current.parent


def read_plain_git_control_file(path: Path, maximum_bytes: int) -> bytes:
    before = path.lstat()
    attributes = getattr(before, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or (reparse_flag and attributes & reparse_flag)
        or before.st_size > maximum_bytes
    ):
        raise RuntimeError("Git control file is not a bounded plain regular file")
    with path.open("rb") as handle:
        opened = os.fstat(handle.fileno())
        if executable_identity(opened) != executable_identity(before):
            raise RuntimeError("Git control file changed before inspection")
        data = handle.read(maximum_bytes + 1)
        after_open = os.fstat(handle.fileno())
    after_path = path.lstat()
    if (
        len(data) > maximum_bytes
        or executable_identity(opened) != executable_identity(after_open)
        or executable_identity(opened) != executable_identity(after_path)
    ):
        raise RuntimeError("Git control file changed during inspection")
    return data


def preflight_local_git_config(candidate: Path) -> None:
    root = detectable_worktree_root(candidate)
    if root is None:
        return
    marker = root / ".git"
    marker_metadata = marker.lstat()
    marker_attributes = getattr(marker_metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if stat.S_ISDIR(marker_metadata.st_mode):
        if stat.S_ISLNK(marker_metadata.st_mode) or (
            reparse_flag and marker_attributes & reparse_flag
        ):
            raise RuntimeError("Git directory cannot be a symlink or reparse point")
        git_directory = marker.resolve(strict=True)
    elif stat.S_ISREG(marker_metadata.st_mode):
        raw_marker = read_plain_git_control_file(marker, 4096)
        try:
            marker_text = raw_marker.decode("utf-8").strip()
        except UnicodeDecodeError as error:
            raise RuntimeError("Git worktree marker is not UTF-8") from error
        match = re.fullmatch(r"gitdir:\s*(.+)", marker_text, re.IGNORECASE)
        if match is None or any(ord(character) < 32 for character in match.group(1)):
            raise RuntimeError("Git worktree marker is malformed")
        reported = Path(match.group(1))
        git_directory = (reported if reported.is_absolute() else root / reported).resolve(
            strict=True
        )
    else:
        raise RuntimeError("Git worktree marker is not a plain file or directory")
    common_directory = git_directory
    commondir_path = git_directory / "commondir"
    if commondir_path.exists():
        raw_common = read_plain_git_control_file(commondir_path, 4096)
        try:
            common_text = raw_common.decode("utf-8").strip()
        except UnicodeDecodeError as error:
            raise RuntimeError("Git common-directory marker is not UTF-8") from error
        if not common_text or any(ord(character) < 32 for character in common_text):
            raise RuntimeError("Git common-directory marker is malformed")
        reported_common = Path(common_text)
        common_directory = (
            reported_common if reported_common.is_absolute() else git_directory / reported_common
        ).resolve(strict=True)
    unsafe_section = re.compile(
        r"(?im)^\s*\[\s*(?:include(?:if)?|filter|diff|merge|credential|alias)\b"
    )
    unsafe_key = re.compile(
        r"(?im)^\s*(?:include(?:if)?|clean|smudge|process|command|textconv|driver|"
        r"helper|askpass|sshcommand|fsmonitor|hookspath|attributesfile|excludesfile|"
        r"program|promisor)\s*="
    )
    for config_path in (common_directory / "config", git_directory / "config.worktree"):
        if not config_path.exists():
            continue
        config_text = read_plain_git_control_file(config_path, MAX_LOCAL_GIT_CONTROL_BYTES).decode(
            "utf-8", errors="surrogateescape"
        )
        if unsafe_section.search(config_text) or unsafe_key.search(config_text):
            raise RuntimeError(
                "repository-local Git config contains includes or execution-capable settings"
            )


def preflight_git_location(program: str, candidate: Path) -> None:
    detectable_root = detectable_worktree_root(candidate)
    if detectable_root is not None and path_is_within(Path(program), detectable_root):
        raise RuntimeError("The approved Git executable must be outside the audited worktree")


def ensure_program_outside_repo(program: str, repo: Path) -> None:
    if path_is_within(Path(program), repo):
        raise RuntimeError("The approved Git executable must be outside the audited worktree")


def git_file_list(repo: Path, *selection: str) -> list[str]:
    result = run_git(repo, "ls-files", "-z", *selection)
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(detail or "Could not list repository files")
    return [
        item.decode("utf-8", errors="surrogateescape")
        for item in result.stdout.split(b"\0")
        if item
    ]


def git_index_entries(repo: Path) -> dict[str, str]:
    result = run_git(repo, "ls-files", "--stage", "-z")
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(detail or "Could not inspect repository index modes")
    entries: dict[str, str] = {}
    for raw_item in (item for item in result.stdout.split(b"\0") if item):
        item = raw_item.decode("utf-8", errors="surrogateescape")
        metadata, separator, path = item.partition("\t")
        fields = metadata.split()
        if not separator or len(fields) != 3:
            raise RuntimeError("Could not parse a repository index entry")
        mode, _, stage = fields
        if stage != "0":
            raise RuntimeError(f"Unmerged index entry cannot be audited safely: {path}")
        entries[path] = mode
    return entries


def excluded(path: str, patterns: tuple[str, ...]) -> bool:
    normalized = path.replace("\\", "/")
    return any(fnmatch.fnmatchcase(normalized, pattern) for pattern in patterns)


def text_like(path: str) -> bool:
    return Path(path).suffix.casefold() in TEXT_SUFFIXES


def decode_text(data: bytes, path: str) -> tuple[str | None, str | None]:
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        try:
            return data.decode("utf-16"), None
        except UnicodeDecodeError:
            return None, "invalid BOM-marked UTF-16 text"
    if data.startswith(codecs.BOM_UTF8):
        try:
            return data.decode("utf-8-sig"), None
        except UnicodeDecodeError:
            return None, "invalid BOM-marked UTF-8 text"
    if b"\0" in data:
        return (None, "binary or unsupported text encoding") if text_like(path) else (None, None)
    try:
        return data.decode("utf-8"), None
    except UnicodeDecodeError:
        return (None, "text is not UTF-8 or BOM-marked UTF-16") if text_like(path) else (None, None)


def read_worktree_text(path: Path, max_bytes: int) -> tuple[str | None, str | None]:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None, None
    except OSError as error:
        return None, f"could not inspect worktree file: {error}"
    if stat.S_ISLNK(metadata.st_mode):
        return None, "worktree symlink was not followed"
    if not stat.S_ISREG(metadata.st_mode):
        return None, "worktree entry is not a regular file"
    if metadata.st_size > max_bytes:
        return (None, "text file exceeds scan limit") if text_like(path.name) else (None, None)
    try:
        with path.open("rb") as handle:
            data = handle.read(max_bytes + 1)
    except OSError as error:
        return None, f"could not read worktree file: {error}"
    if len(data) > max_bytes:
        return (None, "text file exceeds scan limit") if text_like(path.name) else (None, None)
    return decode_text(data, path.name)


def read_index_text(repo: Path, relative: str, max_bytes: int) -> tuple[str | None, str | None]:
    size_result = run_git(repo, "cat-file", "-s", f":{relative}")
    if size_result.returncode != 0:
        detail = size_result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(detail or f"Could not inspect index entry {relative}")
    try:
        size = int(size_result.stdout.strip())
    except ValueError as error:
        raise RuntimeError(f"Invalid size for index entry {relative}") from error
    if size > max_bytes:
        return (None, "text file exceeds scan limit") if text_like(relative) else (None, None)

    content_result = run_git(repo, "cat-file", "blob", f":{relative}")
    if content_result.returncode != 0:
        detail = content_result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(detail or f"Could not read index entry {relative}")
    return decode_text(content_result.stdout, relative)


def line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def add_matches(
    findings: list[Finding],
    path: str,
    text: str,
    category: str,
    pattern: re.Pattern[str],
    source: str,
) -> None:
    for match in pattern.finditer(text):
        findings.append(Finding(path, line_number(text, match.start()), category, source))


def audit_text(
    findings: list[Finding],
    relative: str,
    text: str,
    source: str,
    forbid_en_dash: bool,
    stale_patterns: dict[str, re.Pattern[str]],
) -> None:
    for match in re.finditer("\u2014", text):
        findings.append(
            Finding(relative, line_number(text, match.start()), "Unicode em dash", source)
        )
    if forbid_en_dash:
        for match in re.finditer("\u2013", text):
            findings.append(
                Finding(relative, line_number(text, match.start()), "Unicode en dash", source)
            )

    for category, pattern in PLACEHOLDER_PATTERNS.items():
        add_matches(findings, relative, text, category, pattern, source)
    for category, pattern in CONFLICT_PATTERNS.items():
        add_matches(findings, relative, text, category, pattern, source)
    for category, pattern in SECRET_PATTERNS.items():
        add_matches(findings, relative, text, f"possible {category}", pattern, source)
    for category, pattern in stale_patterns.items():
        add_matches(findings, relative, text, category, pattern, source)


def parse_exclusion(value: str) -> tuple[str, str]:
    pattern, separator, reason = value.partition("=")
    normalized = pattern.replace("\\", "/").strip()
    reason = reason.strip()
    protected = (
        "README.md",
        "LICENSE",
        "NOTICE",
        "CHANGELOG.md",
        "CONTRIBUTING.md",
        "CODE_OF_CONDUCT.md",
        "SECURITY.md",
    )
    if (
        not separator
        or not normalized
        or len(reason) < 10
        or normalized in {"*", "**", "**/*", ".", "./**"}
        or normalized.startswith(("/", "../"))
        or ".." in Path(normalized).parts
        or any(ord(character) < 32 or ord(character) == 127 for character in normalized + reason)
        or any(fnmatch.fnmatchcase(path, normalized) for path in protected)
    ):
        raise argparse.ArgumentTypeError(
            "Expected scoped PATTERN=REASON; required project files cannot be excluded"
        )
    return normalized, reason


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scan tracked and untracked project text without printing matched secrets."
    )
    parser.add_argument("repo", nargs="?", type=Path, default=Path.cwd())
    parser.add_argument(
        "--git-program",
        required=True,
        type=parse_absolute_program,
        help="Approved absolute path to Git, outside the audited worktree",
    )
    parser.add_argument(
        "--git-program-sha256",
        required=True,
        type=parse_sha256,
        help="Approved SHA-256 of the Git executable",
    )
    parser.add_argument("--expected-brand", help="Expected public project name")
    parser.add_argument(
        "--stale-brand",
        action="append",
        default=[],
        help="Old or template brand name that must not remain; repeat as needed",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        type=parse_exclusion,
        metavar="PATTERN=REASON",
        help="Scoped repository-relative exclusion and its substantive reason",
    )
    parser.add_argument("--forbid-en-dash", action="store_true")
    parser.add_argument(
        "--allow-symlink",
        action="append",
        default=[],
        help="Approved repository-relative tracked symlink; repeat as needed",
    )
    parser.add_argument("--max-bytes", type=int, default=2_000_000)
    return parser.parse_args()


def main() -> int:
    global GIT_PROGRAM, GIT_PROGRAM_IDENTITY
    args = parse_args()
    try:
        GIT_PROGRAM, GIT_PROGRAM_IDENTITY = verify_git_program(
            args.git_program, args.git_program_sha256
        )
        repo_candidate = args.repo.resolve()
        preflight_git_location(GIT_PROGRAM, repo_candidate)
        preflight_local_git_config(repo_candidate)
        repo = repository_root(repo_candidate)
        ensure_program_outside_repo(GIT_PROGRAM, repo)
        git_version_result = run_git(repo, "--version")
        if git_version_result.returncode != 0:
            raise RuntimeError("Could not read the approved Git executable version")
        git_version = git_version_result.stdout.decode("utf-8", errors="replace").strip()
        if (
            not git_version.startswith("git version ")
            or len(git_version) > 256
            or any(ord(character) < 32 or ord(character) == 127 for character in git_version)
        ):
            raise RuntimeError("The approved executable did not return a valid Git version")
    except RuntimeError as error:
        print(f"ERROR: {terminal_safe(str(error))}", file=sys.stderr)
        return 2
    user_exclusions: list[tuple[str, str]] = args.exclude
    excludes = (*DEFAULT_EXCLUDES, *(pattern for pattern, _ in user_exclusions))
    exclusion_counts = {pattern: 0 for pattern, _ in user_exclusions}
    findings: list[Finding] = []
    scanned = 0

    try:
        tracked_entries = git_index_entries(repo)
        tracked_paths = list(tracked_entries)
        untracked_paths = git_file_list(repo, "--others")
    except RuntimeError as error:
        print(f"ERROR: {terminal_safe(str(error))}", file=sys.stderr)
        return 2

    stale_patterns = {
        f"stale brand name: {brand}": re.compile(re.escape(brand), re.IGNORECASE)
        for brand in args.stale_brand
        if brand.strip()
    }
    expected_brand_pattern = (
        re.compile(re.escape(args.expected_brand), re.IGNORECASE) if args.expected_brand else None
    )
    allowed_symlinks = {path.replace("\\", "/") for path in args.allow_symlink}
    for allowed_symlink in sorted(allowed_symlinks, key=str.casefold):
        if tracked_entries.get(allowed_symlink) != "120000":
            findings.append(
                Finding(
                    allowed_symlink,
                    1,
                    "symlink allowance does not name a tracked symlink",
                    "arguments",
                )
            )

    for relative in sorted(tracked_paths, key=str.casefold):
        if excluded(relative, excludes):
            for pattern in exclusion_counts:
                if excluded(relative, (pattern,)):
                    exclusion_counts[pattern] += 1
            continue
        index_mode = tracked_entries[relative]
        if index_mode == "160000":
            findings.append(Finding(relative, 1, "tracked Git submodule is not audited", "index"))
            continue
        if index_mode == "120000" and relative not in allowed_symlinks:
            findings.append(
                Finding(
                    relative,
                    1,
                    "tracked symlink lacks an explicit cross-platform allowance",
                    "index",
                )
            )
        elif index_mode not in {"100644", "100755", "120000"}:
            findings.append(Finding(relative, 1, f"unsupported index mode {index_mode}", "index"))
            continue
        try:
            index_text, index_issue = read_index_text(repo, relative, args.max_bytes)
        except RuntimeError as error:
            print(f"ERROR: {terminal_safe(str(error))}", file=sys.stderr)
            return 2
        if index_issue:
            findings.append(Finding(relative, 1, index_issue, "index"))
        if index_text is not None:
            scanned += 1
            audit_text(
                findings,
                relative,
                index_text,
                "index",
                args.forbid_en_dash,
                stale_patterns,
            )
            if (
                expected_brand_pattern
                and relative.casefold() == "readme.md"
                and not expected_brand_pattern.search(index_text)
            ):
                findings.append(Finding(relative, 1, "expected brand is missing", "index"))

        if index_mode == "120000":
            continue
        working_text, working_issue = read_worktree_text(repo / relative, args.max_bytes)
        if working_issue:
            findings.append(Finding(relative, 1, working_issue, "worktree"))
        if expected_brand_pattern and relative.casefold() == "readme.md" and working_text is None:
            findings.append(Finding(relative, 1, "expected brand is missing", "worktree"))
        if working_text is not None and working_text != index_text:
            scanned += 1
            audit_text(
                findings,
                relative,
                working_text,
                "worktree",
                args.forbid_en_dash,
                stale_patterns,
            )
            if (
                expected_brand_pattern
                and relative.casefold() == "readme.md"
                and not expected_brand_pattern.search(working_text)
            ):
                findings.append(Finding(relative, 1, "expected brand is missing", "worktree"))

    for relative in sorted(untracked_paths, key=str.casefold):
        if excluded(relative, excludes):
            for pattern in exclusion_counts:
                if excluded(relative, (pattern,)):
                    exclusion_counts[pattern] += 1
            continue
        working_text, working_issue = read_worktree_text(repo / relative, args.max_bytes)
        if working_issue:
            findings.append(Finding(relative, 1, working_issue, "worktree"))
        if working_text is not None:
            scanned += 1
            audit_text(
                findings,
                relative,
                working_text,
                "worktree",
                args.forbid_en_dash,
                stale_patterns,
            )
            if (
                expected_brand_pattern
                and relative.casefold() == "readme.md"
                and not expected_brand_pattern.search(working_text)
            ):
                findings.append(Finding(relative, 1, "expected brand is missing", "worktree"))

    if expected_brand_pattern and not any(
        relative.casefold() == "readme.md" for relative in tracked_paths
    ):
        findings.append(Finding("README.md", 1, "tracked README is missing", "index"))
    if scanned == 0:
        findings.append(Finding("<audit>", 1, "no substantive text snapshot was scanned", "audit"))
    for pattern, count in exclusion_counts.items():
        if count == 0:
            findings.append(
                Finding(
                    pattern, 1, "user exclusion pattern matched no repository paths", "arguments"
                )
            )

    if findings:
        print(f"Authored-text audit found {len(findings)} issue(s) in {scanned} text snapshot(s):")
        for finding in sorted(
            findings,
            key=lambda item: (item.path.casefold(), item.line, item.source, item.category),
        ):
            rendered = f"{finding.path}:{finding.line} [{finding.source}]: {finding.category}"
            print(f"  {terminal_safe(rendered)}")
        print("Matched text is intentionally omitted so possible secrets are not echoed.")
        print(
            "Git verifier: "
            f"{terminal_safe(GIT_PROGRAM)} ({terminal_safe(git_version)}; "
            f"sha256 {args.git_program_sha256})"
        )
        for pattern, reason in user_exclusions:
            print(
                "Exclusion evidence: "
                f"{terminal_safe(pattern)} matched {exclusion_counts[pattern]} path(s); "
                f"reason: {terminal_safe(reason)}"
            )
        return 1

    brand_note = f" for {terminal_safe(args.expected_brand)}" if args.expected_brand else ""
    print(f"Authored-text audit passed{brand_note}: {scanned} text snapshot(s) scanned")
    print(
        "Git verifier: "
        f"{terminal_safe(GIT_PROGRAM)} ({terminal_safe(git_version)}; "
        f"sha256 {args.git_program_sha256})"
    )
    for pattern, reason in user_exclusions:
        print(
            "Exclusion evidence: "
            f"{terminal_safe(pattern)} matched {exclusion_counts[pattern]} path(s); "
            f"reason: {terminal_safe(reason)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
