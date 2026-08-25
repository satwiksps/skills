#!/usr/bin/env python3
"""Check generic repository and artifact invariants for a release candidate."""

from __future__ import annotations

import argparse
import bz2
import codecs
import gzip
import hashlib
import importlib
import io
import json
import lzma
import os
import re
import shutil
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
import unicodedata
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any
from xml.etree import ElementTree

GIT_PROGRAM: str | None = None
GIT_PROGRAM_IDENTITY: tuple[int, int, int, int, int] | None = None
TRUSTED_PROGRAM_IDENTITIES: dict[str, tuple[int, int, int, int, int]] = {}
LOG_PRIVATE_BYTE_PATTERN: re.Pattern[bytes] | None = None

toml_parser: Any
try:
    toml_parser = importlib.import_module("tomllib")
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    try:
        toml_parser = importlib.import_module("tomli")
    except ModuleNotFoundError:
        toml_parser = None


REQUIRED_FILES = (
    "README.md",
    "LICENSE",
    "NOTICE",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
)
PRIVATE_NAMES = {"idea.md", "plan.md"}
ARCHIVE_SUFFIXES = (
    ".crate",
    ".gem",
    ".jar",
    ".nupkg",
    ".tar",
    ".tar.bz2",
    ".tar.gz",
    ".tar.xz",
    ".tgz",
    ".whl",
    ".zip",
)
APACHE_2_NORMALIZED_SHA256 = "43070e2d4e532684de521b885f385d0841030efa2b1a20bafb76133a5e1379c1"
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
ARCHIVE_SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\bgh[opsu]_[A-Za-z0-9]{20,}\b"),
    "PyPI token": re.compile(r"\bpypi-[A-Za-z0-9_-]{20,}\b"),
    "npm token": re.compile(r"\bnpm_[A-Za-z0-9]{20,}\b"),
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "generic bearer token": re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{24,}=*\b", re.IGNORECASE),
}
MAX_ARCHIVE_ENTRIES = 100_000
MAX_ZIP_CENTRAL_DIRECTORY_BYTES = 64_000_000
MAX_LOCAL_GIT_CONTROL_BYTES = 1_000_000
MAX_ARCHIVE_MEMBER_BYTES = 20_000_000
MAX_ARCHIVE_TOTAL_BYTES = 500_000_000
MAX_PRIVATE_INPUT_BYTES = 100_000_000
MAX_PRIVATE_PATTERN_BYTES = 32_000_000
MAX_PRIVATE_FRAGMENT_CHARS = 16_384
LONG_PRIVATE_WINDOW_CHARS = 48
LONG_PRIVATE_WINDOW_STRIDE = 16
MAX_NONARCHIVE_SCAN_BYTES = 100_000_000
MAX_NESTED_ARCHIVE_DEPTH = 2
MAX_TAR_PADDING_BYTES = 10_000_000
MAX_COMPRESSION_RATIO = 500
MIN_RATIO_CHECK_BYTES = 1_000_000
COMMON_PRIVATE_FRAGMENT_ALLOWLIST = {
    "license: apache-2.0",
    "commit-signing policy: required by default",
    "release-tag signing policy: required by default",
    "none found with evidence",
}
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
    "GIT_NO_LAZY_FETCH",
    "GIT_NAMESPACE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_REPLACE_REF_BASE",
    "GIT_SHALLOW_FILE",
    "GIT_TERMINAL_PROMPT",
    "GIT_WORK_TREE",
}
WINDOWS_RESERVED_NAMES = {
    "aux",
    "con",
    "nul",
    "prn",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
    "com¹",
    "com²",
    "com³",
    "lpt¹",
    "lpt²",
    "lpt³",
}


@dataclass
class ArchiveBudget:
    entries: int = 0
    uncompressed_bytes: int = 0
    private_exact_hashes: set[str] = field(default_factory=set)
    private_normalized_documents: set[str] = field(default_factory=set)
    private_fragments: set[str] = field(default_factory=set)
    private_byte_fragments: set[bytes] = field(default_factory=set)
    private_byte_pattern: re.Pattern[bytes] | None = field(init=False, default=None)
    longest_private_byte_fragment: int = field(init=False, default=0)
    expected_notice_bytes: bytes = b""
    expected_license_members: set[str] = field(default_factory=set)
    expected_notice_members: set[str] = field(default_factory=set)
    canonical_license_members: set[str] = field(default_factory=set)
    approved_notice_members: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.private_byte_pattern, self.longest_private_byte_fragment = (
            compile_private_byte_pattern(self.private_byte_fragments)
        )


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


def executable_identity(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def verify_trusted_program(
    program_value: str, approved_sha256: str, label: str
) -> tuple[str, tuple[int, int, int, int, int]]:
    program = Path(program_value).resolve(strict=True)
    metadata = program.lstat()
    if not stat.S_ISREG(metadata.st_mode) or not os.access(program, os.X_OK):
        raise RuntimeError(f"approved {label} must be a regular executable")
    if any(ord(character) < 32 or ord(character) == 127 for character in str(program)):
        raise RuntimeError(f"approved {label} path contains a control character")
    digest = hashlib.sha256()
    before = executable_identity(metadata)
    with program.open("rb") as handle:
        opened = executable_identity(os.fstat(handle.fileno()))
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
        after_open = executable_identity(os.fstat(handle.fileno()))
    after_path = executable_identity(program.lstat())
    if before != opened or opened != after_open or after_open != after_path:
        raise RuntimeError(f"approved {label} changed while its SHA-256 was verified")
    if digest.hexdigest() != approved_sha256:
        raise RuntimeError(f"approved {label} SHA-256 does not match")
    resolved = str(program)
    TRUSTED_PROGRAM_IDENTITIES[resolved] = after_path
    return resolved, after_path


def assert_trusted_program_unchanged(program: str, label: str) -> None:
    expected = TRUSTED_PROGRAM_IDENTITIES.get(program)
    if expected is None:
        raise RuntimeError(f"approved {label} identity was not registered")
    try:
        observed = executable_identity(Path(program).lstat())
    except OSError as error:
        raise RuntimeError(f"approved {label} is no longer available") from error
    if observed != expected:
        raise RuntimeError(f"approved {label} changed after verification")


def run_git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    if GIT_PROGRAM is None or GIT_PROGRAM_IDENTITY is None:
        raise RuntimeError("A trusted absolute Git executable has not been configured")
    assert_trusted_program_unchanged(GIT_PROGRAM, "Git executable")
    result = subprocess.run(
        [
            GIT_PROGRAM,
            "-C",
            str(repo),
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.hooksPath=",
            *args,
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=git_environment(),
    )
    assert_trusted_program_unchanged(GIT_PROGRAM, "Git executable")
    if check and result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Git command failed")
    return result


def run_git_bytes(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    if GIT_PROGRAM is None or GIT_PROGRAM_IDENTITY is None:
        raise RuntimeError("A trusted absolute Git executable has not been configured")
    assert_trusted_program_unchanged(GIT_PROGRAM, "Git executable")
    result = subprocess.run(
        [
            GIT_PROGRAM,
            "-C",
            str(repo),
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.hooksPath=",
            *args,
        ],
        check=False,
        capture_output=True,
        env=git_environment(),
    )
    assert_trusted_program_unchanged(GIT_PROGRAM, "Git executable")
    if check and result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(detail or "Git command failed")
    return result


def repo_root(candidate: Path) -> Path:
    return Path(run_git(candidate, "rev-parse", "--show-toplevel").stdout.strip()).resolve()


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
        raw_config = read_plain_git_control_file(config_path, MAX_LOCAL_GIT_CONTROL_BYTES)
        config_text = raw_config.decode("utf-8", errors="surrogateescape")
        if unsafe_section.search(config_text) or unsafe_key.search(config_text):
            raise RuntimeError(
                "repository-local Git config contains includes or execution-capable settings"
            )


def preflight_program_location(program: str, candidate: Path, label: str) -> None:
    detectable_root = detectable_worktree_root(candidate)
    if detectable_root is not None and path_is_within(Path(program), detectable_root):
        raise RuntimeError(f"approved {label} must be outside the audited worktree")


def ensure_program_outside_repo(program: str, repo: Path) -> None:
    try:
        Path(program).resolve().relative_to(repo.resolve())
    except ValueError:
        return
    raise RuntimeError("The approved Git executable must be outside the audited worktree")


def path_is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def terminal_safe(value: str) -> str:
    """Escape control and non-ASCII characters before writing audit logs."""
    redacted = value
    for pattern in ARCHIVE_SECRET_PATTERNS.values():
        redacted = pattern.sub("<redacted secret>", redacted)
    if LOG_PRIVATE_BYTE_PATTERN is not None:
        encoded = unicodedata.normalize("NFC", redacted).encode("utf-8", errors="surrogatepass")
        if LOG_PRIVATE_BYTE_PATTERN.search(encoded) is not None:
            redacted = "<redacted private diagnostic>"
    return json.dumps(redacted, ensure_ascii=True)[1:-1]


def reject_grafts(repo: Path) -> None:
    result = run_git(
        repo,
        "rev-parse",
        "--git-path",
        "info/grafts",
    )
    grafts_path = Path(result.stdout.strip())
    if not grafts_path.is_absolute():
        grafts_path = repo / grafts_path
    grafts_path = grafts_path.resolve()
    try:
        if grafts_path.is_file() and grafts_path.stat().st_size:
            raise RuntimeError("Cannot prove release history while .git/info/grafts is nonempty")
    except OSError as error:
        raise RuntimeError(f"Could not inspect Git grafts file: {error}") from error


def reject_partial_clone(repo: Path) -> None:
    partial = run_git(repo, "config", "--local", "--get", "extensions.partialClone", check=False)
    promisors = run_git(
        repo,
        "config",
        "--local",
        "--get-regexp",
        r"^remote\..*\.promisor$",
        check=False,
    )
    if partial.returncode == 0 and partial.stdout.strip():
        raise RuntimeError("Cannot prove an offline release from a partial clone")
    if promisors.returncode == 0 and promisors.stdout.strip():
        raise RuntimeError("Cannot prove an offline release while a promisor remote is configured")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_file_identity(metadata: os.stat_result) -> tuple[int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
    )


def snapshot_artifact(
    source: Path, staging_directory: Path, maximum_bytes: int
) -> tuple[Path, str]:
    staging_directory.mkdir(parents=True, exist_ok=True)
    staging_metadata = staging_directory.lstat()
    file_attributes = getattr(staging_metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if stat.S_ISLNK(staging_metadata.st_mode) or (reparse_flag and file_attributes & reparse_flag):
        raise RuntimeError("artifact staging directory cannot be a symlink or reparse point")
    if not stat.S_ISDIR(staging_metadata.st_mode):
        raise RuntimeError("artifact staging path is not a directory")

    source_metadata = source.lstat()
    source_attributes = getattr(source_metadata, "st_file_attributes", 0)
    if (
        stat.S_ISLNK(source_metadata.st_mode)
        or (reparse_flag and source_attributes & reparse_flag)
        or not stat.S_ISREG(source_metadata.st_mode)
    ):
        raise RuntimeError("artifact source must be a plain regular file")
    if source_metadata.st_size > maximum_bytes:
        raise RuntimeError("artifact exceeds the approved maximum byte size")
    free_bytes = shutil.disk_usage(staging_directory).free
    reserve = min(maximum_bytes, 16 * 1024 * 1024)
    if free_bytes < source_metadata.st_size + reserve:
        raise RuntimeError("artifact staging filesystem lacks the required free-space reserve")

    temporary_fd, temporary_name = tempfile.mkstemp(
        prefix="artifact-snapshot-", dir=str(staging_directory)
    )
    digest = hashlib.sha256()
    try:
        path_before = source.lstat()
        source_attributes = getattr(path_before, "st_file_attributes", 0)
        if stat.S_ISLNK(path_before.st_mode) or (reparse_flag and source_attributes & reparse_flag):
            raise RuntimeError(f"artifact path is a symlink or reparse point: {source}")
        with source.open("rb") as source_handle, os.fdopen(temporary_fd, "wb") as snapshot_handle:
            before = os.fstat(source_handle.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise RuntimeError("artifact source is not a regular file")
            if before.st_size > maximum_bytes:
                raise RuntimeError("artifact exceeds the approved maximum byte size")
            copied = 0
            for block in iter(lambda: source_handle.read(1024 * 1024), b""):
                copied += len(block)
                if copied > maximum_bytes:
                    raise RuntimeError("artifact grew beyond the approved maximum byte size")
                snapshot_handle.write(block)
                digest.update(block)
            snapshot_handle.flush()
            os.fsync(snapshot_handle.fileno())
            after = os.fstat(source_handle.fileno())
        path_after = source.lstat()
        if (
            stable_file_identity(before) != stable_file_identity(after)
            or stable_file_identity(before) != stable_file_identity(source_metadata)
            or stable_file_identity(before) != stable_file_identity(path_before)
            or stable_file_identity(before) != stable_file_identity(path_after)
            or copied != before.st_size
        ):
            raise RuntimeError("artifact changed while it was being snapshotted")

        digest_value = digest.hexdigest()
        digest_directory = staging_directory / digest_value
        digest_directory.mkdir(exist_ok=True)
        digest_metadata = digest_directory.lstat()
        digest_attributes = getattr(digest_metadata, "st_file_attributes", 0)
        if (
            stat.S_ISLNK(digest_metadata.st_mode)
            or (reparse_flag and digest_attributes & reparse_flag)
            or not stat.S_ISDIR(digest_metadata.st_mode)
        ):
            raise RuntimeError(f"artifact snapshot directory is unsafe: {digest_directory}")
        destination = digest_directory / source.name
        if destination.exists():
            raise RuntimeError("artifact snapshot target already exists")
        try:
            os.link(temporary_name, destination)
        except FileExistsError:
            raise RuntimeError("artifact snapshot target was created concurrently") from None
        Path(temporary_name).unlink()
        os.chmod(destination, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        destination_metadata = destination.lstat()
        destination_attributes = getattr(destination_metadata, "st_file_attributes", 0)
        if (
            not stat.S_ISREG(destination_metadata.st_mode)
            or stat.S_ISLNK(destination_metadata.st_mode)
            or (reparse_flag and destination_attributes & reparse_flag)
            or destination_metadata.st_nlink != 1
            or sha256(destination) != digest_value
        ):
            raise RuntimeError("artifact snapshot identity or digest is unsafe")
        return destination.resolve(), digest_value
    except BaseException:
        try:
            Path(temporary_name).unlink()
        except FileNotFoundError:
            pass
        raise


def normalize_prose(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip().casefold()


def without_allowlisted_public_lines(text: str) -> str:
    kept: list[str] = []
    for raw_line in text.splitlines():
        candidate = re.sub(r"^\s*(?:#{1,6}|[-*+] |\d+[.)] )", "", raw_line)
        if normalize_prose(candidate) in COMMON_PRIVATE_FRAGMENT_ALLOWLIST:
            continue
        kept.append(raw_line)
    return "\n".join(kept)


def strong_private_values(text: str) -> list[str]:
    values: list[str] = []
    field_pattern = re.compile(
        r"\b(?:(?:secret|private|internal)\s+)?(?:codename|credential|"
        r"(?:(?:api|access|auth)\s*)?token|password|(?:api|ssh|signing)\s+key|"
        r"secret\s+(?:value|key|identifier))\b\s*[:=]\s*(.+)$",
        re.IGNORECASE,
    )
    for raw_line in text.splitlines():
        assignment = field_pattern.search(raw_line)
        if assignment is None:
            continue
        value = assignment.group(1).strip().rstrip(".,;").strip().strip("`'\"").strip()
        normalized = normalize_prose(value)
        if len(normalized) >= 8 and normalized not in COMMON_PRIVATE_FRAGMENT_ALLOWLIST:
            values.extend((value, normalized))
    return values


def private_byte_fragments(text: str) -> set[bytes]:
    candidates = distinctive_fragments(text)
    candidates.update(strong_private_values(text))
    for raw_line in unicodedata.normalize("NFC", text).splitlines():
        line = re.sub(r"^\s*(?:#{1,6}|[-*+] |\d+[.)] )", "", raw_line).strip()
        normalized_line = normalize_prose(line)
        strong_private = re.search(
            r"\b(?:codename|confidential|internal|private|secret|unreleased)\b",
            normalized_line,
        )
        if (
            len(line) >= 64 or (strong_private and len(normalized_line) >= 8)
        ) and normalized_line not in COMMON_PRIVATE_FRAGMENT_ALLOWLIST:
            candidates.update((line, normalized_line))
    encoded: set[bytes] = set()
    for fragment in sorted(candidates, key=lambda value: (-len(value), value)):
        for normalized_fragment in {
            unicodedata.normalize("NFC", fragment),
            unicodedata.normalize("NFD", fragment),
        }:
            bounded_fragments: tuple[str, ...]
            if len(normalized_fragment) <= MAX_PRIVATE_FRAGMENT_CHARS:
                bounded_fragments = (normalized_fragment,)
            else:
                starts = range(
                    0,
                    len(normalized_fragment) - LONG_PRIVATE_WINDOW_CHARS + 1,
                    LONG_PRIVATE_WINDOW_STRIDE,
                )
                bounded_fragments = tuple(
                    normalized_fragment[start : start + LONG_PRIVATE_WINDOW_CHARS]
                    for start in starts
                )
                final_window = normalized_fragment[-LONG_PRIVATE_WINDOW_CHARS:]
                if not bounded_fragments or bounded_fragments[-1] != final_window:
                    bounded_fragments = (*bounded_fragments, final_window)
            for bounded in bounded_fragments:
                for encoding in (
                    "utf-8",
                    "utf-16-le",
                    "utf-16-be",
                    "utf-32-le",
                    "utf-32-be",
                ):
                    value = bounded.encode(encoding)
                    if len(value) >= 8:
                        encoded.add(value)
    return encoded


def compile_private_byte_pattern(
    fragments: set[bytes],
) -> tuple[re.Pattern[bytes] | None, int]:
    if not fragments:
        return None, 0
    total_pattern_bytes = sum(len(value) + 1 for value in fragments)
    if total_pattern_bytes > MAX_PRIVATE_PATTERN_BYTES:
        raise RuntimeError(
            "private binary fingerprints exceed the safe matcher budget; "
            "split or reduce private inputs before release"
        )
    ordered = sorted(fragments, key=lambda value: (-len(value), value))
    try:
        pattern = re.compile(b"|".join(re.escape(value) for value in ordered))
    except (MemoryError, re.error) as error:
        raise RuntimeError("private binary fingerprints could not be compiled safely") from error
    return pattern, max(len(value) for value in fragments)


def distinctive_fragments(text: str) -> set[str]:
    fragments: set[str] = set()
    for paragraph in re.split(r"(?:\r?\n){2,}", text):
        normalized = normalize_prose(paragraph)
        if len(normalized) >= 80:
            fragments.add(normalized)
        words = normalized.split()
        for start in range(0, max(0, len(words) - 15), 8):
            window = " ".join(words[start : start + 16])
            if len(window) >= 100:
                fragments.add(window)
    for raw_line in text.splitlines():
        line = normalize_prose(re.sub(r"^\s*(?:#{1,6}|[-*+] |\d+[.)] )", "", raw_line))
        sensitive = re.search(
            r"\b(?:codename|private|internal|unreleased|secret|credential|token)\b",
            line,
        )
        if (
            len(line) >= 64 or (sensitive and len(line) >= 24)
        ) and line not in COMMON_PRIVATE_FRAGMENT_ALLOWLIST:
            fragments.add(line)
        for sentence in re.split(r"(?<=[.!?])\s+", line):
            if len(sentence) >= 80 and sentence not in COMMON_PRIVATE_FRAGMENT_ALLOWLIST:
                fragments.add(sentence)
    fragments.update(strong_private_values(text))
    return fragments


def decode_candidate_text(data: bytes, name: str) -> tuple[str | None, str | None]:
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        try:
            return data.decode("utf-16"), None
        except UnicodeDecodeError:
            return None, f"invalid BOM-marked UTF-16 text: {name}"
    if data.startswith(codecs.BOM_UTF8):
        try:
            return data.decode("utf-8-sig"), None
        except UnicodeDecodeError:
            return None, f"invalid BOM-marked UTF-8 text: {name}"
    if b"\0" in data:
        return None, None
    try:
        return data.decode("utf-8"), None
    except UnicodeDecodeError:
        return None, None


def load_private_fingerprints(
    paths: list[Path],
) -> tuple[set[str], set[str], set[str], set[bytes]]:
    exact_hashes: set[str] = set()
    normalized_documents: set[str] = set()
    fragments: set[str] = set()
    byte_fragments: set[bytes] = set()
    for path in paths:
        resolved = path.resolve()
        if not resolved.is_file():
            raise RuntimeError("a private input is missing or is not a regular file")
        if resolved.stat().st_size > MAX_PRIVATE_INPUT_BYTES:
            raise RuntimeError("a private input exceeds the scan limit")
        data = resolved.read_bytes()
        text, _ = decode_candidate_text(data, resolved.name)
        if text is None:
            raise RuntimeError("a private input is not supported Unicode text")
        private_text = without_allowlisted_public_lines(text)
        normalized_document = normalize_prose(private_text)
        if normalized_document:
            exact_hashes.add(hashlib.sha256(data).hexdigest())
            normalized_documents.add(normalized_document)
        if len(normalized_document) >= 12:
            fragments.add(normalized_document)
        fragments.update(distinctive_fragments(private_text))
        byte_fragments.update(private_byte_fragments(private_text))
    return exact_hashes, normalized_documents, fragments, byte_fragments


def private_path_key(path: Path) -> str:
    return os.path.normcase(str(path.resolve(strict=False)))


def private_input_set_digest(paths: list[Path]) -> str:
    records: list[bytes] = []
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    seen_keys: set[str] = set()
    seen_files: list[Path] = []
    for path in sorted(paths, key=private_path_key):
        path_key = private_path_key(path)
        if path_key in seen_keys:
            raise RuntimeError("the private-input inventory contains a duplicate path")
        before_path = path.lstat()
        attributes = getattr(before_path, "st_file_attributes", 0)
        if (
            not stat.S_ISREG(before_path.st_mode)
            or stat.S_ISLNK(before_path.st_mode)
            or (reparse_flag and attributes & reparse_flag)
        ):
            raise RuntimeError("every private inventory item must be a plain regular file")
        if any(os.path.samefile(path, seen_path) for seen_path in seen_files):
            raise RuntimeError("the private-input inventory contains aliased files")
        seen_keys.add(path_key)
        seen_files.append(path)
        content_digest = hashlib.sha256()
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            if executable_identity(opened) != executable_identity(before_path):
                raise RuntimeError("a private inventory item changed before hashing")
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                content_digest.update(block)
            after_open = os.fstat(handle.fileno())
        after_path = path.lstat()
        if executable_identity(opened) != executable_identity(after_open) or executable_identity(
            opened
        ) != executable_identity(after_path):
            raise RuntimeError("a private inventory item changed while hashing")
        canonical_path = os.path.normcase(str(path.resolve(strict=True))).encode(
            "utf-8", errors="surrogatepass"
        )
        records.append(canonical_path + b"\0" + content_digest.hexdigest().encode("ascii"))
    inventory_digest = hashlib.sha256()
    for record in records:
        inventory_digest.update(len(record).to_bytes(8, "big"))
        inventory_digest.update(record)
    return inventory_digest.hexdigest()


def matches_private_content(data: bytes, budget: ArchiveBudget) -> bool:
    if hashlib.sha256(data).hexdigest() in budget.private_exact_hashes:
        return True
    if budget.private_byte_pattern is not None and budget.private_byte_pattern.search(data):
        return True
    text, _ = decode_candidate_text(data, "private-content candidate")
    if text is None:
        return False
    normalized = normalize_prose(text)
    return normalized in budget.private_normalized_documents or any(
        fragment in normalized for fragment in budget.private_fragments
    )


def expected_archive(path: Path) -> bool:
    return path.name.casefold().endswith(ARCHIVE_SUFFIXES)


def normalized_member_path(
    name: str,
    seen: dict[str, str],
    explicit_seen: set[str],
    display_name: str,
    is_directory: bool,
    file_paths: set[str],
    directory_paths: set[str],
) -> tuple[str, list[str]]:
    issues: list[str] = []
    normalized = name.replace("\\", "/")
    candidate = normalized[:-1] if normalized.endswith("/") else normalized
    parts = candidate.split("/") if candidate else []
    if (
        not candidate
        or "\0" in candidate
        or any(ord(character) < 32 or ord(character) == 127 for character in candidate)
        or candidate.startswith("/")
        or candidate.startswith("//")
        or re.match(r"^[A-Za-z]:", candidate)
        or any(part in {"", ".", ".."} for part in parts)
        or any(
            any(character in '<>:"|?*!' for character in part) or part.endswith((" ", "."))
            for part in parts
        )
        or any(part.split(".", 1)[0].casefold() in WINDOWS_RESERVED_NAMES for part in parts)
        or PurePosixPath(candidate).is_absolute()
    ):
        issues.append(f"unsafe archive member path: {display_name}")

    for index in range(1, len(parts) + 1):
        exact_prefix = "/".join(parts[:index])
        canonical_prefix = unicodedata.normalize("NFC", exact_prefix).casefold()
        previous = seen.get(canonical_prefix)
        if previous is not None and previous != exact_prefix:
            issues.append(f"case-colliding archive member path: {display_name}")
            break
        seen.setdefault(canonical_prefix, exact_prefix)

    canonical = unicodedata.normalize("NFC", candidate).casefold()
    if canonical in explicit_seen:
        issues.append(f"duplicate archive member path: {display_name}")
    elif candidate:
        explicit_seen.add(canonical)

    ancestor_paths = [
        unicodedata.normalize("NFC", "/".join(parts[:index])).casefold()
        for index in range(1, len(parts))
    ]
    if any(ancestor in file_paths for ancestor in ancestor_paths):
        issues.append(f"archive file is used as a parent directory: {display_name}")
    directory_paths.update(ancestor_paths)
    if is_directory:
        if canonical in file_paths:
            issues.append(f"archive path is both a file and directory: {display_name}")
        directory_paths.add(canonical)
    else:
        if canonical in directory_paths:
            issues.append(f"archive path is both a file and directory: {display_name}")
        file_paths.add(canonical)

    if parts and parts[-1].casefold() in PRIVATE_NAMES:
        issues.append(f"private planning file is present in artifact: {display_name}")
    return candidate, issues


def archive_contract_matches(name: str, pattern: str) -> bool:
    """Match a documented path glob without letting `*` cross path boundaries."""
    expression: list[str] = ["^"]
    index = 0
    while index < len(pattern):
        character = pattern[index]
        if pattern.startswith("**/", index):
            expression.append(r"(?:[^!/]+/)*")
            index += 3
        elif pattern.startswith("**", index):
            expression.append(r"[^!]*")
            index += 2
        elif character == "*":
            expression.append(r"[^/!]*")
            index += 1
        elif character == "?":
            expression.append(r"[^/!]")
            index += 1
        else:
            expression.append(re.escape(character))
            index += 1
    expression.append("$")
    return re.fullmatch("".join(expression), name) is not None


def text_like_archive_member(name: str) -> bool:
    return PurePosixPath(name).suffix.casefold() in TEXT_SUFFIXES


def decode_archive_text(data: bytes, name: str) -> tuple[str | None, str | None]:
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        try:
            return data.decode("utf-16"), None
        except UnicodeDecodeError:
            return None, f"invalid BOM-marked UTF-16 archive member: {name}"
    if data.startswith(codecs.BOM_UTF8):
        try:
            return data.decode("utf-8-sig"), None
        except UnicodeDecodeError:
            return None, f"invalid BOM-marked UTF-8 archive member: {name}"
    if b"\0" in data:
        if text_like_archive_member(name):
            return None, f"text archive member has an unsupported encoding: {name}"
        return None, None
    try:
        return data.decode("utf-8"), None
    except UnicodeDecodeError:
        if text_like_archive_member(name):
            return None, f"text archive member is not UTF-8 or BOM-marked UTF-16: {name}"
        return None, None


def archive_member_issues(
    display_name: str,
    member_name: str,
    data: bytes | None,
    budget: ArchiveBudget,
) -> list[str]:
    issues: list[str] = []
    if data is None:
        if text_like_archive_member(member_name):
            issues.append(f"text archive member exceeds scan limit: {display_name}")
        return issues
    if matches_private_content(data, budget):
        issues.append(f"private planning content is present in artifact: {display_name}")
    text, decode_issue = decode_archive_text(data, member_name)
    if decode_issue:
        issues.append(decode_issue)
    if display_name in budget.expected_license_members:
        if not apache_license_bytes_are_canonical(data):
            issues.append(f"artifact LICENSE is not canonical Apache License 2.0: {display_name}")
        else:
            budget.canonical_license_members.add(display_name)
    if display_name in budget.expected_notice_members:
        normalized_notice = normalize_legal_bytes(data)
        expected_notice = normalize_legal_bytes(budget.expected_notice_bytes)
        if normalized_notice is None or normalized_notice != expected_notice:
            issues.append(
                f"artifact NOTICE differs from the audited repository NOTICE: {display_name}"
            )
        else:
            budget.approved_notice_members.add(display_name)

    secret_scan_text = text if text is not None else data.decode("latin-1")
    for category, pattern in ARCHIVE_SECRET_PATTERNS.items():
        if pattern.search(secret_scan_text):
            issues.append(f"possible {category} in archive member: {display_name}")
    return issues


def stream_opaque_member_issues(
    handle: Any,
    display_name: str,
    member_name: str,
    budget: ArchiveBudget,
) -> list[str]:
    """Scan a large opaque member without loading it all into memory."""
    issues: list[str] = []
    if text_like_archive_member(member_name):
        issues.append(f"text archive member exceeds scan limit: {display_name}")
    overlap_size = max(budget.longest_private_byte_fragment - 1, 512)
    tail = b""
    digest = hashlib.sha256()
    private_found = False
    secret_categories: set[str] = set()
    for block in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(block)
        candidate = tail + block
        if (
            not private_found
            and budget.private_byte_pattern is not None
            and budget.private_byte_pattern.search(candidate)
        ):
            private_found = True
        latin_text = candidate.decode("latin-1")
        for category, pattern in ARCHIVE_SECRET_PATTERNS.items():
            if category not in secret_categories and pattern.search(latin_text):
                secret_categories.add(category)
        tail = candidate[-overlap_size:]
    if digest.hexdigest() in budget.private_exact_hashes:
        private_found = True
    if private_found:
        issues.append(f"private planning content is present in artifact: {display_name}")
    for category in sorted(secret_categories):
        issues.append(f"possible {category} in archive member: {display_name}")
    return issues


def charge_archive_budget(
    budget: ArchiveBudget, member_name: str, uncompressed_bytes: int
) -> list[str]:
    budget.entries += 1
    budget.uncompressed_bytes += max(0, uncompressed_bytes)
    issues: list[str] = []
    if budget.entries > MAX_ARCHIVE_ENTRIES:
        issues.append(f"archive contains more than {MAX_ARCHIVE_ENTRIES} entries")
    if budget.uncompressed_bytes > MAX_ARCHIVE_TOTAL_BYTES:
        issues.append(
            f"archive expands beyond the {MAX_ARCHIVE_TOTAL_BYTES}-byte cumulative scan budget: "
            f"{member_name}"
        )
    return issues


def compression_ratio_issue(
    uncompressed_bytes: int, compressed_bytes: int, label: str
) -> str | None:
    if uncompressed_bytes < MIN_RATIO_CHECK_BYTES:
        return None
    if compressed_bytes <= 0 or uncompressed_bytes / compressed_bytes > MAX_COMPRESSION_RATIO:
        return f"archive compression ratio exceeds {MAX_COMPRESSION_RATIO}:1: {label}"
    return None


def tar_header_is_plausible(data: bytes) -> bool:
    if len(data) < 512:
        return False
    header = data[:512]
    raw_checksum = header[148:156].strip(b" \0")
    try:
        expected = int(raw_checksum or b"0", 8)
    except ValueError:
        return False
    observed = sum(header[:148]) + (8 * 32) + sum(header[156:])
    return expected == observed and expected != 0


def looks_like_container_payload(data: bytes) -> bool:
    if data.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        return True
    if data.startswith((b"\x1f\x8b", b"BZh", b"\xfd7zXZ\x00")):
        return True
    if tar_header_is_plausible(data):
        return True
    if len(data) <= MAX_ARCHIVE_MEMBER_BYTES:
        stream = io.BytesIO(data)
        return zipfile.is_zipfile(stream)
    return False


def single_stream_compression(data: bytes) -> str | None:
    if data.startswith(b"\x1f\x8b"):
        return "gzip"
    if data.startswith(b"BZh"):
        return "bzip2"
    if data.startswith(b"\xfd7zXZ\x00"):
        return "xz"
    return None


def decompress_single_stream(data: bytes, label: str) -> tuple[bytes | None, str | None]:
    kind = single_stream_compression(data)
    if kind is None:
        return None, "not a supported compressed stream"
    limit = MAX_ARCHIVE_MEMBER_BYTES + 1
    try:
        if kind == "gzip":
            with gzip.GzipFile(fileobj=io.BytesIO(data), mode="rb") as handle:
                decompressed = handle.read(limit)
        elif kind == "bzip2":
            bzip2_decompressor = bz2.BZ2Decompressor()
            decompressed = bzip2_decompressor.decompress(data, max_length=limit)
            if len(decompressed) <= MAX_ARCHIVE_MEMBER_BYTES and not bzip2_decompressor.eof:
                return None, f"compressed stream is truncated or exceeds scan limit: {label}"
            if bzip2_decompressor.unused_data:
                return None, f"compressed stream has trailing bytes: {label}"
        else:
            xz_decompressor = lzma.LZMADecompressor()
            decompressed = xz_decompressor.decompress(data, max_length=limit)
            if len(decompressed) <= MAX_ARCHIVE_MEMBER_BYTES and not xz_decompressor.eof:
                return None, f"compressed stream is truncated or exceeds scan limit: {label}"
            if xz_decompressor.unused_data:
                return None, f"compressed stream has trailing bytes: {label}"
    except (EOFError, OSError, ValueError, lzma.LZMAError) as error:
        return None, f"compressed stream cannot be decoded: {label}: {type(error).__name__}"
    if len(decompressed) > MAX_ARCHIVE_MEMBER_BYTES:
        return None, f"compressed stream exceeds member scan limit: {label}"
    ratio_issue = compression_ratio_issue(len(decompressed), len(data), label)
    if ratio_issue:
        return None, ratio_issue
    return decompressed, None


def decompressed_member_name(member_name: str, kind: str) -> str:
    suffixes = {"gzip": ".gz", "bzip2": ".bz2", "xz": ".xz"}
    suffix = suffixes[kind]
    if member_name.casefold().endswith(suffix):
        candidate = member_name[: -len(suffix)]
        if candidate:
            return candidate
    return f"{member_name}.decompressed"


def inspect_nested_payload(
    data: bytes,
    display_name: str,
    member_name: str,
    depth: int,
    budget: ArchiveBudget,
) -> tuple[list[str], list[str]]:
    if depth >= MAX_NESTED_ARCHIVE_DEPTH:
        return [], [f"nested archive exceeds scan depth: {display_name}"]

    wrapper_issues = archive_member_issues(
        f"{display_name}!<raw-wrapper>",
        "raw-wrapper.bin",
        data,
        budget,
    )

    kind = single_stream_compression(data)
    if kind is not None:
        decompressed, issue = decompress_single_stream(data, display_name)
        if issue or decompressed is None:
            return [], [issue or f"compressed stream cannot be decoded: {display_name}"]
        synthetic_member = decompressed_member_name(member_name, kind)
        synthetic_display = f"{display_name}!{synthetic_member}"
        issues = [
            *wrapper_issues,
            *charge_archive_budget(budget, synthetic_display, len(decompressed)),
        ]
        names = [synthetic_display]
        if looks_like_container_payload(decompressed):
            nested = inspect_archive_stream(
                io.BytesIO(decompressed), synthetic_display, depth + 1, budget
            )
            if nested is None:
                issues.append(f"nested archive cannot be opened: {synthetic_display}")
            else:
                nested_names, nested_issues = nested
                names.extend(nested_names)
                issues.extend(nested_issues)
        else:
            issues.extend(
                archive_member_issues(synthetic_display, synthetic_member, decompressed, budget)
            )
        return names, issues

    nested = inspect_archive_stream(io.BytesIO(data), display_name, depth + 1, budget)
    if nested is None:
        return [], [*wrapper_issues, f"nested archive cannot be opened: {display_name}"]
    nested[1][0:0] = wrapper_issues
    return nested


def zip_envelope_issues(data: bytes, label: str) -> list[str]:
    issues: list[str] = []
    if not data.startswith((b"PK\x03\x04", b"PK\x05\x06")):
        issues.append(f"ZIP has a prepended or unsupported envelope: {label}")
    if len(data) < 22 or data[-22:-18] != b"PK\x05\x06":
        issues.append(f"ZIP has a comment or trailing envelope bytes: {label}")
    elif int.from_bytes(data[-2:], "little") != 0:
        issues.append(f"ZIP archive comment is not allowed: {label}")
    return issues


def zip_path_envelope_issues(path: Path) -> list[str]:
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            prefix = handle.read(4)
            if size >= 22:
                handle.seek(-22, io.SEEK_END)
                suffix = handle.read(22)
            else:
                suffix = b""
    except OSError as error:
        return [f"ZIP envelope cannot be read: {path.name}: {type(error).__name__}"]
    issues: list[str] = []
    if not prefix.startswith((b"PK\x03\x04", b"PK\x05\x06")):
        issues.append(f"ZIP has a prepended or unsupported envelope: {path.name}")
    if len(suffix) != 22 or suffix[:4] != b"PK\x05\x06":
        issues.append(f"ZIP has a comment or trailing envelope bytes: {path.name}")
    elif int.from_bytes(suffix[-2:], "little") != 0:
        issues.append(f"ZIP archive comment is not allowed: {path.name}")
    return issues


def read_exact_at(handle: Any, offset: int, length: int) -> bytes | None:
    if offset < 0 or length < 0:
        return None
    handle.seek(offset)
    data = handle.read(length)
    return data if len(data) == length else None


def zip_preflight_issues(handle: Any, size: int, label: str) -> list[str]:
    """Bound central-directory allocation before constructing ZipFile."""
    suffix = read_exact_at(handle, size - 22, 22) if size >= 22 else None
    if suffix is None or suffix[:4] != b"PK\x05\x06" or int.from_bytes(suffix[-2:], "little"):
        return [f"ZIP has a comment or trailing envelope bytes: {label}"]
    eocd = struct.unpack("<4s4H2LH", suffix)
    if eocd[1] or eocd[2] or eocd[3] != eocd[4]:
        return [f"multi-disk ZIP is not supported: {label}"]
    if eocd[4] == 0xFFFF or eocd[5] == 0xFFFFFFFF or eocd[6] == 0xFFFFFFFF:
        return [f"ZIP64 is outside the bounded release format: {label}"]
    issues: list[str] = []
    if eocd[4] > MAX_ARCHIVE_ENTRIES:
        issues.append(f"ZIP contains more than {MAX_ARCHIVE_ENTRIES} entries: {label}")
    if eocd[5] > MAX_ZIP_CENTRAL_DIRECTORY_BYTES:
        issues.append(f"ZIP central directory exceeds the allocation limit: {label}")
    if eocd[6] + eocd[5] != size - 22:
        issues.append(f"ZIP central-directory envelope is inconsistent: {label}")
    return issues


def zip_raw_structure_issues(
    handle: Any,
    size: int,
    archive: zipfile.ZipFile,
    label: str,
    budget: ArchiveBudget,
) -> list[str]:
    """Reject unparsed ZIP envelope bytes and divergent local metadata."""
    issues: list[str] = []
    prefix = read_exact_at(handle, 0, min(4, size)) or b""
    suffix = read_exact_at(handle, size - 22, 22) if size >= 22 else None
    if not prefix.startswith((b"PK\x03\x04", b"PK\x05\x06")):
        issues.append(f"ZIP has a prepended or unsupported envelope: {label}")
    if suffix is None or suffix[:4] != b"PK\x05\x06" or int.from_bytes(suffix[-2:], "little"):
        issues.append(f"ZIP has a comment or trailing envelope bytes: {label}")
        return issues

    eocd = struct.unpack("<4s4H2LH", suffix)
    if eocd[1] != 0 or eocd[2] != 0 or eocd[3] != eocd[4]:
        issues.append(f"multi-disk ZIP is not supported: {label}")
    if eocd[4] == 0xFFFF or eocd[5] == 0xFFFFFFFF or eocd[6] == 0xFFFFFFFF:
        issues.append(f"ZIP64 is outside the bounded release format: {label}")
        return issues
    infos = archive.infolist()
    if eocd[4] != len(infos):
        issues.append(f"ZIP entry count does not match its central directory: {label}")

    start_dir = int(getattr(archive, "start_dir", -1))
    if start_dir < 0 or start_dir > size - 22:
        issues.append(f"ZIP central-directory offset is invalid: {label}")
        return issues
    if eocd[6] != start_dir:
        issues.append(f"ZIP central-directory offset is inconsistent: {label}")

    central_records: dict[int, tuple[tuple[Any, ...], bytes]] = {}
    central_offset = start_dir
    for info in infos:
        central_header = read_exact_at(handle, central_offset, 46)
        if central_header is None or central_header[:4] != b"PK\x01\x02":
            issues.append(f"ZIP central record is invalid: {label}!{info.filename}")
            break
        fields = struct.unpack("<4s6H3L5H2L", central_header)
        filename_length = fields[10]
        extra_length = fields[11]
        comment_length = fields[12]
        record_length = 46 + filename_length + extra_length + comment_length
        record = read_exact_at(handle, central_offset, record_length)
        if record is None:
            issues.append(f"ZIP central record is truncated: {label}!{info.filename}")
            break
        raw_name = record[46 : 46 + filename_length]
        raw_extra = record[46 + filename_length : 46 + filename_length + extra_length]
        raw_comment = record[46 + filename_length + extra_length :]
        local_offset = fields[16]
        if local_offset in central_records:
            issues.append(f"ZIP central records reuse a local offset: {label}")
        central_records[local_offset] = (fields, raw_name)
        issues.extend(
            archive_member_issues(
                f"{label}!{info.filename}!<zip-central-name>",
                "zip-central-name.bin",
                raw_name,
                budget,
            )
        )
        if extra_length:
            issues.append(f"ZIP central extra fields are not allowed: {label}!{info.filename}")
            issues.extend(
                archive_member_issues(
                    f"{label}!{info.filename}!<zip-central-extra>",
                    "zip-central-extra.bin",
                    raw_extra,
                    budget,
                )
            )
        if comment_length:
            issues.append(f"ZIP central comments are not allowed: {label}!{info.filename}")
            issues.extend(
                archive_member_issues(
                    f"{label}!{info.filename}!<zip-central-comment>",
                    "zip-central-comment.bin",
                    raw_comment,
                    budget,
                )
            )
        central_offset += record_length

    expected_local_offset = 0
    for info in sorted(infos, key=lambda value: value.header_offset):
        if info.header_offset != expected_local_offset:
            issues.append(f"ZIP contains unexplained bytes between local records: {label}")
        local_header = read_exact_at(handle, info.header_offset, 30)
        if local_header is None or local_header[:4] != b"PK\x03\x04":
            issues.append(f"ZIP local header is invalid: {label}!{info.filename}")
            continue
        fields = struct.unpack("<4s5H3L2H", local_header)
        flags = fields[2]
        filename_length = fields[9]
        extra_length = fields[10]
        local_name = read_exact_at(handle, info.header_offset + 30, filename_length)
        local_extra = read_exact_at(handle, info.header_offset + 30 + filename_length, extra_length)
        if local_name is None or local_extra is None:
            issues.append(f"ZIP local metadata is truncated: {label}!{info.filename}")
            continue
        issues.extend(
            archive_member_issues(
                f"{label}!{info.filename}!<zip-local-name>",
                "zip-local-name.bin",
                local_name,
                budget,
            )
        )
        if flags & 0x08:
            issues.append(f"ZIP data descriptors are not allowed: {label}!{info.filename}")
        if extra_length:
            issues.append(f"ZIP local extra fields are not allowed: {label}!{info.filename}")
            issues.extend(
                archive_member_issues(
                    f"{label}!{info.filename}!<zip-local-extra>",
                    "zip-local-extra.bin",
                    local_extra,
                    budget,
                )
            )
        central_record = central_records.get(info.header_offset)
        if central_record is None:
            issues.append(f"ZIP local record has no matching central record: {label}")
        else:
            central_fields, central_name = central_record
            if local_name != central_name:
                issues.append(f"ZIP local and central filenames differ: {label}!{info.filename}")
            if tuple(fields[1:9]) != tuple(central_fields[2:10]):
                issues.append(f"ZIP local and central metadata differ: {label}!{info.filename}")
        expected_local_offset = (
            info.header_offset + 30 + filename_length + extra_length + info.compress_size
        )
    if expected_local_offset != start_dir:
        issues.append(f"ZIP local records do not end at the central directory: {label}")

    if central_offset - start_dir != eocd[5]:
        issues.append(f"ZIP central-directory size is inconsistent: {label}")

    eocd_offset = size - 22
    if central_offset != eocd_offset:
        issues.append(f"ZIP contains unexplained central-directory bytes: {label}")
    return issues


def inspect_zip(
    archive: zipfile.ZipFile,
    prefix: str,
    depth: int,
    budget: ArchiveBudget,
) -> tuple[list[str], list[str]]:
    names: list[str] = []
    issues: list[str] = []
    seen: dict[str, str] = {}
    explicit_seen: set[str] = set()
    file_paths: set[str] = set()
    directory_paths: set[str] = set()
    if archive.comment:
        issues.append("ZIP archive comment is not allowed")
        issues.extend(
            archive_member_issues(
                f"{prefix or '<archive>'}!<zip-comment>",
                "zip-comment.bin",
                archive.comment,
                budget,
            )
        )
    for info in archive.infolist():
        display_name = f"{prefix}!{info.filename}" if prefix else info.filename
        names.append(display_name)
        issues.extend(
            archive_member_issues(
                f"{display_name}!<zip-name>",
                "zip-name.txt",
                info.filename.encode("utf-8", errors="surrogatepass"),
                budget,
            )
        )
        member_name, path_issues = normalized_member_path(
            info.filename,
            seen,
            explicit_seen,
            display_name,
            info.is_dir(),
            file_paths,
            directory_paths,
        )
        issues.extend(path_issues)
        issues.extend(charge_archive_budget(budget, display_name, info.file_size))
        if (
            budget.entries > MAX_ARCHIVE_ENTRIES
            or budget.uncompressed_bytes > MAX_ARCHIVE_TOTAL_BYTES
        ):
            break

        ratio_issue = compression_ratio_issue(info.file_size, info.compress_size, display_name)
        if ratio_issue:
            issues.append(ratio_issue)
            continue

        unix_mode = (info.external_attr >> 16) & 0xFFFF
        file_type = stat.S_IFMT(unix_mode)
        if unix_mode & (stat.S_ISUID | stat.S_ISGID | stat.S_IWOTH):
            issues.append(f"dangerous archive permission bits: {display_name}")
        if info.comment:
            issues.append(f"ZIP member comment is not allowed: {display_name}")
            issues.extend(
                archive_member_issues(
                    f"{display_name}!<zip-comment>",
                    "zip-comment.bin",
                    info.comment,
                    budget,
                )
            )
        if info.extra:
            issues.append(f"ZIP member extra fields are not allowed: {display_name}")
            if len(info.extra) > MAX_ARCHIVE_MEMBER_BYTES:
                issues.append(f"ZIP member extra fields exceed scan limit: {display_name}")
            else:
                issues.extend(
                    archive_member_issues(
                        f"{display_name}!<zip-extra>",
                        "zip-extra.bin",
                        info.extra,
                        budget,
                    )
                )
        if info.flag_bits & 0x1:
            issues.append(f"encrypted archive member is not inspectable: {display_name}")
            continue
        if stat.S_ISLNK(unix_mode):
            issues.append(f"archive symlink is not allowed: {display_name}")
            continue
        if file_type and not (stat.S_ISREG(unix_mode) or stat.S_ISDIR(unix_mode)):
            issues.append(f"special archive member is not allowed: {display_name}")
            continue
        if info.is_dir():
            continue
        if path_issues:
            continue

        data: bytes | None = None
        prefix_bytes = b""
        if info.file_size <= MAX_ARCHIVE_MEMBER_BYTES:
            data = archive.read(info)
            prefix_bytes = data
        else:
            with archive.open(info) as handle:
                prefix_bytes = handle.read(512)
            with archive.open(info) as handle:
                issues.extend(
                    stream_opaque_member_issues(handle, display_name, member_name, budget)
                )
        if data is not None:
            issues.extend(archive_member_issues(display_name, member_name, data, budget))
        nested_candidate = expected_archive(Path(member_name)) or looks_like_container_payload(
            prefix_bytes
        )
        if nested_candidate:
            if data is None:
                issues.append(f"nested archive exceeds member scan limit: {display_name}")
            else:
                nested_names, nested_issues = inspect_nested_payload(
                    data, display_name, member_name, depth, budget
                )
                names.extend(nested_names)
                issues.extend(nested_issues)
    return names, issues


def tar_tail_issues(archive: tarfile.TarFile, logical_end: int, label: str) -> list[str]:
    """Require the complete TAR trailer to be bounded and entirely zero-filled."""
    try:
        archive.fileobj.seek(logical_end)
        trailer = archive.fileobj.read(MAX_TAR_PADDING_BYTES + 1)
    except (EOFError, OSError, tarfile.TarError, ValueError):
        return [f"TAR trailer cannot be inspected safely: {label}"]
    if len(trailer) > MAX_TAR_PADDING_BYTES:
        return [f"TAR zero padding exceeds the bounded release format: {label}"]
    if len(trailer) < 1024:
        return [f"TAR is missing its two zero trailer blocks: {label}"]
    if any(trailer):
        return [f"TAR has nonzero or trailing envelope bytes: {label}"]
    return []


def inspect_tar(
    archive: tarfile.TarFile,
    prefix: str,
    depth: int,
    budget: ArchiveBudget,
) -> tuple[list[str], list[str]]:
    names: list[str] = []
    issues: list[str] = []
    seen: dict[str, str] = {}
    explicit_seen: set[str] = set()
    file_paths: set[str] = set()
    directory_paths: set[str] = set()
    logical_end = 0
    complete_scan = True
    if archive.pax_headers:
        issues.append("TAR global pax headers are not allowed")
        encoded_headers = "\n".join(
            f"{key}={value}" for key, value in sorted(archive.pax_headers.items())
        ).encode("utf-8", errors="surrogatepass")
        issues.extend(
            archive_member_issues(
                f"{prefix or '<archive>'}!<pax-global>",
                "pax-global.txt",
                encoded_headers,
                budget,
            )
        )
    for member in archive:
        logical_end = max(
            logical_end,
            member.offset_data + ((max(0, member.size) + 511) // 512) * 512,
        )
        display_name = f"{prefix}!{member.name}" if prefix else member.name
        names.append(display_name)
        metadata_text = "\n".join(
            value for value in (member.name, member.uname, member.gname, member.linkname) if value
        )
        issues.extend(
            archive_member_issues(
                f"{display_name}!<tar-metadata>",
                "tar-metadata.txt",
                metadata_text.encode("utf-8", errors="surrogatepass"),
                budget,
            )
        )
        member_name, path_issues = normalized_member_path(
            member.name,
            seen,
            explicit_seen,
            display_name,
            member.isdir(),
            file_paths,
            directory_paths,
        )
        issues.extend(path_issues)
        issues.extend(charge_archive_budget(budget, display_name, member.size))
        if (
            budget.entries > MAX_ARCHIVE_ENTRIES
            or budget.uncompressed_bytes > MAX_ARCHIVE_TOTAL_BYTES
        ):
            complete_scan = False
            break

        if member.mode & (stat.S_ISUID | stat.S_ISGID | stat.S_IWOTH):
            issues.append(f"dangerous archive permission bits: {display_name}")
        if (
            member.uid != 0
            or member.gid != 0
            or member.uname not in {"", "root"}
            or member.gname not in {"", "root"}
        ):
            issues.append(f"non-normalized TAR owner metadata: {display_name}")
        if member.pax_headers:
            forbidden_pax = {
                key
                for key in member.pax_headers
                if key.casefold() in {"atime", "ctime"} or "sparse" in key.casefold()
            }
            if forbidden_pax:
                issues.append(f"unsafe or non-reproducible TAR pax metadata: {display_name}")
            encoded_headers = "\n".join(
                f"{key}={value}" for key, value in sorted(member.pax_headers.items())
            ).encode("utf-8", errors="surrogatepass")
            if len(encoded_headers) > MAX_ARCHIVE_MEMBER_BYTES:
                issues.append(f"TAR pax metadata exceeds scan limit: {display_name}")
            else:
                issues.extend(
                    archive_member_issues(
                        f"{display_name}!<pax>",
                        "pax.txt",
                        encoded_headers,
                        budget,
                    )
                )

        if member.isdir():
            continue
        if not member.isfile():
            issues.append(f"archive link or special member is not allowed: {display_name}")
            continue
        if path_issues:
            continue

        data: bytes | None = None
        prefix_bytes = b""
        extracted = archive.extractfile(member)
        if extracted is None:
            issues.append(f"archive member cannot be read: {display_name}")
        elif member.size <= MAX_ARCHIVE_MEMBER_BYTES:
            data = extracted.read(MAX_ARCHIVE_MEMBER_BYTES + 1)
            prefix_bytes = data
            if len(data) > MAX_ARCHIVE_MEMBER_BYTES:
                data = None
        else:
            prefix_bytes = extracted.read(512)
            stream = archive.extractfile(member)
            if stream is None:
                issues.append(f"archive member cannot be reopened: {display_name}")
            else:
                issues.extend(
                    stream_opaque_member_issues(stream, display_name, member_name, budget)
                )
        if data is not None:
            issues.extend(archive_member_issues(display_name, member_name, data, budget))
        nested_candidate = expected_archive(Path(member_name)) or looks_like_container_payload(
            prefix_bytes
        )
        if nested_candidate:
            if data is None:
                issues.append(f"nested archive exceeds member scan limit: {display_name}")
            else:
                nested_names, nested_issues = inspect_nested_payload(
                    data, display_name, member_name, depth, budget
                )
                names.extend(nested_names)
                issues.extend(nested_issues)
    if complete_scan:
        issues.extend(tar_tail_issues(archive, logical_end, prefix or "<archive>"))
    return names, issues


def inspect_archive_stream(
    stream: io.BytesIO,
    prefix: str,
    depth: int,
    budget: ArchiveBudget,
) -> tuple[list[str], list[str]] | None:
    try:
        report: tuple[list[str], list[str]]
        compressed_bytes = stream.getbuffer().nbytes
        start_bytes = budget.uncompressed_bytes
        stream.seek(0)
        raw_issues = stream_opaque_member_issues(
            stream,
            f"{prefix or '<archive>'}!<raw-envelope>",
            "raw-envelope.bin",
            budget,
        )
        stream.seek(0)
        if zipfile.is_zipfile(stream):
            stream.seek(0)
            preflight_issues = zip_preflight_issues(stream, compressed_bytes, prefix or "<archive>")
            if preflight_issues:
                report = ([], preflight_issues)
            else:
                with zipfile.ZipFile(stream) as archive:
                    report = inspect_zip(archive, prefix, depth, budget)
                    report[1].extend(
                        zip_raw_structure_issues(
                            stream,
                            compressed_bytes,
                            archive,
                            prefix or "<archive>",
                            budget,
                        )
                    )
        else:
            stream.seek(0)
            with tarfile.open(fileobj=stream, mode="r:*") as archive:
                report = inspect_tar(archive, prefix, depth, budget)
        ratio_issue = compression_ratio_issue(
            budget.uncompressed_bytes - start_bytes, compressed_bytes, prefix
        )
        if ratio_issue:
            report[1].append(ratio_issue)
        report[1][0:0] = raw_issues
        return report
    except (
        EOFError,
        OSError,
        RuntimeError,
        ValueError,
        tarfile.TarError,
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
    ):
        return None


def inspect_archive(
    path: Path,
    private_exact_hashes: set[str],
    private_normalized_documents: set[str],
    private_fragments: set[str],
    private_byte_fragment_values: set[bytes],
    expected_notice_bytes: bytes,
    expected_license_members: set[str],
    expected_notice_members: set[str],
) -> tuple[list[str], list[str]] | None:
    budget = ArchiveBudget(
        private_exact_hashes=private_exact_hashes,
        private_normalized_documents=private_normalized_documents,
        private_fragments=private_fragments,
        private_byte_fragments=private_byte_fragment_values,
        expected_notice_bytes=expected_notice_bytes,
        expected_license_members=expected_license_members,
        expected_notice_members=expected_notice_members,
    )
    try:
        report: tuple[list[str], list[str]]
        start_bytes = budget.uncompressed_bytes
        if zipfile.is_zipfile(path):
            with path.open("rb") as raw_archive:
                preflight_issues = zip_preflight_issues(raw_archive, path.stat().st_size, path.name)
                if preflight_issues:
                    report = ([], preflight_issues)
                else:
                    with zipfile.ZipFile(path) as archive:
                        report = inspect_zip(archive, "", 0, budget)
                        report[1].extend(
                            zip_raw_structure_issues(
                                raw_archive,
                                path.stat().st_size,
                                archive,
                                path.name,
                                budget,
                            )
                        )
        elif tarfile.is_tarfile(path):
            with tarfile.open(path, "r:*") as archive:
                report = inspect_tar(archive, "", 0, budget)
        else:
            return None
        ratio_issue = compression_ratio_issue(
            budget.uncompressed_bytes - start_bytes, path.stat().st_size, path.name
        )
        if ratio_issue:
            report[1].append(ratio_issue)
        for missing in sorted(
            budget.expected_license_members - budget.canonical_license_members,
            key=str.casefold,
        ):
            report[1].append(f"archive lacks its approved canonical LICENSE member: {missing}")
        for missing in sorted(
            budget.expected_notice_members - budget.approved_notice_members,
            key=str.casefold,
        ):
            report[1].append(f"archive lacks its approved NOTICE member: {missing}")
        return report
    except (
        EOFError,
        OSError,
        RuntimeError,
        ValueError,
        tarfile.TarError,
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
    ):
        return None


def metadata_text(data: bytes, name: str) -> str:
    text, issue = decode_candidate_text(data, name)
    if text is None:
        raise ValueError(issue or f"package metadata is not supported text: {name}")
    return text


def email_metadata_version(text: str, name: str) -> str:
    match = re.search(r"^Version:\s*([^\s]+)\s*$", text, re.MULTILINE | re.IGNORECASE)
    if not match:
        raise ValueError(f"package metadata has no Version field: {name}")
    return match.group(1)


def nuspec_version(text: str, name: str) -> str:
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as error:
        raise ValueError(f"NuGet metadata is invalid XML: {name}: {error}") from error
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1].casefold() == "version" and element.text:
            return element.text.strip()
    raise ValueError(f"NuGet metadata has no version: {name}")


def package_json_version(text: str, name: str) -> str:
    try:
        value = json.loads(text).get("version")
    except json.JSONDecodeError as error:
        raise ValueError(f"npm metadata is invalid JSON: {name}: {error}") from error
    if not isinstance(value, str):
        raise ValueError(f"npm metadata has no string version: {name}")
    return value


def selected_metadata_version(member_name: str, data: bytes) -> str:
    text = metadata_text(data, member_name)
    lowered = member_name.casefold()
    if lowered.endswith(("/metadata", "/pkg-info")) or lowered == "pkg-info":
        return email_metadata_version(text, member_name)
    if lowered.endswith("package.json"):
        return package_json_version(text, member_name)
    if lowered.endswith(".nuspec"):
        return nuspec_version(text, member_name)
    if lowered.endswith("pom.properties"):
        match = re.search(r"^version\s*=\s*(\S+)\s*$", text, re.MULTILINE)
        if not match:
            raise ValueError(f"Maven metadata has no version: {member_name}")
        return match.group(1)
    if lowered.endswith("cargo.toml"):
        return manifest_version("Cargo.toml", text)
    raise ValueError(
        f"No built-in parser for selected metadata member {member_name}; "
        "use digest-bound --adapter-inspected"
    )


def artifact_metadata_version(path: Path, selected_member: str) -> tuple[str, str]:
    matches: list[tuple[str, bytes]] = []
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                normalized = info.filename.replace("\\", "/")
                if info.is_dir() or normalized != selected_member:
                    continue
                if info.file_size > MAX_ARCHIVE_MEMBER_BYTES:
                    raise ValueError(f"package metadata exceeds scan limit: {normalized}")
                matches.append((normalized, archive.read(info)))
    elif tarfile.is_tarfile(path):
        with tarfile.open(path, "r:*") as archive:
            for member in archive:
                normalized = member.name.replace("\\", "/")
                if not member.isfile() or normalized != selected_member:
                    continue
                if member.size > MAX_ARCHIVE_MEMBER_BYTES:
                    raise ValueError(f"package metadata exceeds scan limit: {normalized}")
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise ValueError(f"package metadata cannot be read: {normalized}")
                matches.append((normalized, extracted.read(MAX_ARCHIVE_MEMBER_BYTES + 1)))
    if len(matches) != 1:
        raise ValueError(f"selected project metadata must exist exactly once: {selected_member}")
    name, data = matches[0]
    return name, selected_metadata_version(name, data)


def digest_stream_exact(handle: Any, expected_bytes: int) -> str:
    digest = hashlib.sha256()
    remaining = expected_bytes
    while remaining:
        block = handle.read(min(1024 * 1024, remaining))
        if not block:
            raise ValueError("bundled artifact member is shorter than the approved artifact")
        digest.update(block)
        remaining -= len(block)
    if handle.read(1):
        raise ValueError("bundled artifact member is longer than the approved artifact")
    return digest.hexdigest()


def bundled_artifact_digests(
    path: Path, artifact_basename: str, expected_bytes: int
) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if info.is_dir() or PurePosixPath(info.filename).name != artifact_basename:
                    continue
                if info.file_size != expected_bytes:
                    raise ValueError("bundled artifact member size does not match approved bytes")
                with archive.open(info) as handle:
                    found.append((info.filename, digest_stream_exact(handle, expected_bytes)))
    elif tarfile.is_tarfile(path):
        with tarfile.open(path, "r:*") as archive:
            for member in archive:
                if not member.isfile() or PurePosixPath(member.name).name != artifact_basename:
                    continue
                if member.size != expected_bytes:
                    raise ValueError("bundled artifact member size does not match approved bytes")
                extracted = archive.extractfile(member)
                if extracted is not None:
                    found.append((member.name, digest_stream_exact(extracted, expected_bytes)))
    return found


def filename_contains_version(name: str, version: str) -> bool:
    return re.search(rf"(?<![0-9A-Za-z])v?{re.escape(version)}(?![0-9A-Za-z])", name) is not None


def tree_file_bytes(repo: Path, ref: str, relative: str) -> bytes | None:
    result = run_git_bytes(repo, "show", f"{ref}:{relative}", check=False)
    if result.returncode == 0:
        return result.stdout
    return None


def tree_file_text(repo: Path, ref: str, relative: str) -> str | None:
    data = tree_file_bytes(repo, ref, relative)
    if data is None:
        return None
    try:
        if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
            return data.decode("utf-16")
        if data.startswith(codecs.BOM_UTF8):
            return data.decode("utf-8-sig")
        return data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(f"{relative} is not UTF-8 or BOM-marked UTF-16 text") from error


def tree_directory_exists(repo: Path, ref: str, relative: str) -> bool:
    result = run_git(repo, "ls-tree", "-d", "--name-only", ref, "--", relative, check=False)
    return result.returncode == 0 and relative in result.stdout.splitlines()


def manifest_version(path_name: str, text: str) -> str:
    path = Path(path_name)
    name = path.name.casefold()
    if name == "package.json":
        value = json.loads(text).get("version")
        if not isinstance(value, str):
            raise ValueError("package.json has no string version")
        return value
    if name in {"pyproject.toml", "cargo.toml"}:
        if toml_parser is None:
            raise ValueError("Python 3.11 or the tomli package is required to parse TOML")
        data = toml_parser.loads(text)
        if name == "pyproject.toml":
            value = data.get("project", {}).get("version")
            if value is None:
                value = data.get("tool", {}).get("poetry", {}).get("version")
        else:
            value = data.get("package", {}).get("version")
        if not isinstance(value, str):
            raise ValueError(f"{path.name} has no supported version field")
        return value
    if path.suffix.casefold() in {".csproj", ".props"}:
        try:
            root = ElementTree.fromstring(text)
        except ElementTree.ParseError as error:
            raise ValueError(f"{path.name} is not valid XML: {error}") from error
        for field in ("PackageVersion", "Version", "VersionPrefix"):
            for element in root.iter():
                local_name = element.tag.rsplit("}", 1)[-1]
                if local_name == field and element.text:
                    return element.text.strip()
        raise ValueError(f"{path.name} has no package version field")
    if path.suffix.casefold() == ".gemspec":
        match = re.search(r"\.version\s*=\s*['\"]([^'\"]+)['\"]", text)
        if match:
            return match.group(1)
        raise ValueError(f"{path.name} has no literal gem version")
    raise ValueError(f"No built-in version parser for {path.name}; use --version-pattern")


def default_version_source_names(repo: Path, ref: str) -> list[str]:
    return [
        name
        for name in ("pyproject.toml", "package.json", "Cargo.toml")
        if tree_file_bytes(repo, ref, name) is not None
    ]


def reachable_objects_by_type(repo: Path) -> dict[str, set[str]]:
    listing = run_git(repo, "rev-list", "--objects", "--all", "--no-object-names", check=False)
    if listing.returncode != 0:
        raise RuntimeError(listing.stderr.strip() or "Could not enumerate reachable Git objects")
    object_ids = sorted(set(value for value in listing.stdout.splitlines() if value))
    if not object_ids:
        return {}
    if GIT_PROGRAM is None:
        raise RuntimeError("A trusted absolute Git executable has not been configured")
    assert_trusted_program_unchanged(GIT_PROGRAM, "Git executable")
    batch = subprocess.run(
        [
            GIT_PROGRAM,
            "-C",
            str(repo),
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.hooksPath=",
            "cat-file",
            "--batch-check=%(objectname) %(objecttype)",
        ],
        input="\n".join(object_ids) + "\n",
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=git_environment(),
    )
    assert_trusted_program_unchanged(GIT_PROGRAM, "Git executable")
    if batch.returncode != 0:
        raise RuntimeError(batch.stderr.strip() or "Could not classify reachable Git objects")
    by_type: dict[str, set[str]] = {}
    classified: set[str] = set()
    for line in batch.stdout.splitlines():
        object_id, separator, object_type = line.partition(" ")
        if (
            not separator
            or object_type == "missing"
            or object_id not in object_ids
            or object_id in classified
        ):
            raise RuntimeError("Git did not classify every reachable object exactly once")
        classified.add(object_id)
        by_type.setdefault(object_type, set()).add(object_id)
    if classified != set(object_ids):
        raise RuntimeError("Git did not classify every reachable object exactly once")
    return by_type


def history_private_names(repo: Path, private_names: set[str]) -> set[str]:
    shallow = run_git(repo, "rev-parse", "--is-shallow-repository").stdout.strip()
    if shallow == "true":
        raise RuntimeError("Cannot prove private-file history in a shallow repository")

    trees = run_git(repo, "log", "--all", "--format=%T", check=False)
    if trees.returncode != 0:
        raise RuntimeError(trees.stderr.strip() or "Could not enumerate reachable commit trees")
    found: set[str] = set()
    reachable_trees = reachable_objects_by_type(repo).get("tree", set())
    for tree in sorted(set(trees.stdout.splitlines()).union(reachable_trees)):
        if not tree:
            continue
        listing = run_git(repo, "ls-tree", "-r", "-z", "--name-only", tree)
        for value in (path for path in listing.stdout.split("\0") if path):
            if Path(value.replace("\\", "/")).name.casefold() in private_names:
                found.add(value)
    return found


def reject_sparse_or_optimized_index(repo: Path) -> None:
    sparse = run_git(repo, "config", "--bool", "core.sparseCheckout", check=False)
    if sparse.returncode == 0 and sparse.stdout.strip().casefold() == "true":
        raise RuntimeError("Cannot prove a clean release from a sparse checkout")
    listing = run_git(repo, "ls-files", "-v", "-z")
    unsafe: list[str] = []
    for record in (value for value in listing.stdout.split("\0") if value):
        tag, separator, path = record.partition(" ")
        if not separator:
            raise RuntimeError("Could not parse Git index flags")
        if tag == "S" or tag.islower():
            unsafe.append(path)
    if unsafe:
        raise RuntimeError(
            "Cannot prove a clean release while skip-worktree or assume-unchanged "
            f"is set on {len(unsafe)} tracked path(s)"
        )


def parse_index_snapshot(data: bytes) -> dict[bytes, tuple[str, str]]:
    entries: dict[bytes, tuple[str, str]] = {}
    for record in (value for value in data.split(b"\0") if value):
        metadata, separator, path = record.partition(b"\t")
        fields = metadata.split()
        if not separator or len(fields) != 3 or not path:
            raise RuntimeError("Could not parse the Git index snapshot")
        mode_bytes, object_id_bytes, stage = fields
        if stage != b"0":
            raise RuntimeError("Cannot release with unmerged index entries")
        try:
            mode = mode_bytes.decode("ascii")
            object_id = object_id_bytes.decode("ascii")
        except UnicodeDecodeError as error:
            raise RuntimeError("Git index metadata is not ASCII") from error
        if path in entries:
            raise RuntimeError("Git index contains a duplicate path")
        entries[path] = (mode, object_id)
    return entries


def parse_tree_snapshot(data: bytes) -> dict[bytes, tuple[str, str]]:
    entries: dict[bytes, tuple[str, str]] = {}
    for record in (value for value in data.split(b"\0") if value):
        metadata, separator, path = record.partition(b"\t")
        fields = metadata.split()
        if not separator or len(fields) != 3 or not path:
            raise RuntimeError("Could not parse the HEAD tree snapshot")
        mode_bytes, object_type, object_id_bytes = fields
        try:
            mode = mode_bytes.decode("ascii")
            object_id = object_id_bytes.decode("ascii")
        except UnicodeDecodeError as error:
            raise RuntimeError("Git tree metadata is not ASCII") from error
        expected_type = b"commit" if mode == "160000" else b"blob"
        if object_type != expected_type or path in entries:
            raise RuntimeError("Git HEAD tree contains an unsupported or duplicate entry")
        entries[path] = (mode, object_id)
    return entries


def git_blob_digest_bytes(data: bytes, object_format: str) -> str:
    digest = hashlib.new(object_format)
    digest.update(b"blob " + str(len(data)).encode("ascii") + b"\0")
    digest.update(data)
    return digest.hexdigest()


def regular_worktree_blob_digest(path: Path, repo: Path, object_format: str) -> str:
    before_path = path.lstat()
    file_attributes = getattr(before_path, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if (
        not stat.S_ISREG(before_path.st_mode)
        or stat.S_ISLNK(before_path.st_mode)
        or (reparse_flag and file_attributes & reparse_flag)
    ):
        raise RuntimeError("Tracked worktree entry is not a plain regular file")
    try:
        path.parent.resolve(strict=True).relative_to(repo.resolve())
        path.resolve(strict=True).relative_to(repo.resolve())
    except (OSError, ValueError) as error:
        raise RuntimeError("Tracked worktree entry escapes the repository") from error

    with path.open("rb") as handle:
        opened = os.fstat(handle.fileno())
        if executable_identity(opened) != executable_identity(before_path):
            raise RuntimeError("Tracked worktree entry changed before it could be read")
        digest = hashlib.new(object_format)
        digest.update(b"blob " + str(opened.st_size).encode("ascii") + b"\0")
        observed_size = 0
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            observed_size += len(block)
            digest.update(block)
        after_open = os.fstat(handle.fileno())
    after_path = path.lstat()
    if (
        observed_size != opened.st_size
        or executable_identity(opened) != executable_identity(after_open)
        or executable_identity(opened) != executable_identity(after_path)
    ):
        raise RuntimeError("Tracked worktree entry changed while it was read")
    return digest.hexdigest()


def worktree_blob_digest(
    repo: Path, raw_path: bytes, mode: str, object_format: str
) -> tuple[str, os.stat_result]:
    relative = os.fsdecode(raw_path).replace("\\", "/")
    pure_path = PurePosixPath(relative)
    if (
        pure_path.is_absolute()
        or not pure_path.parts
        or any(part in {"", ".", ".."} for part in pure_path.parts)
    ):
        raise RuntimeError("Git returned an unsafe tracked worktree path")
    path = repo.joinpath(*pure_path.parts)
    metadata = path.lstat()
    if mode == "120000" and stat.S_ISLNK(metadata.st_mode):
        try:
            path.parent.resolve(strict=True).relative_to(repo.resolve())
        except (OSError, ValueError) as error:
            raise RuntimeError("Tracked symlink parent escapes the repository") from error
        target = os.fsencode(os.readlink(path))
        after = path.lstat()
        if executable_identity(metadata) != executable_identity(after):
            raise RuntimeError("Tracked symlink changed while it was read")
        return git_blob_digest_bytes(target, object_format), metadata
    return regular_worktree_blob_digest(path, repo, object_format), metadata


def filter_free_clean_checkout_issues(
    repo: Path, head_commit: str, allowed_untracked: set[bytes]
) -> list[str]:
    """Prove index and worktree bytes match HEAD without invoking Git filters."""
    object_format = run_git(repo, "rev-parse", "--show-object-format").stdout.strip()
    if object_format not in hashlib.algorithms_available or object_format not in {"sha1", "sha256"}:
        raise RuntimeError("Git repository uses an unsupported object format")
    index_entries = parse_index_snapshot(run_git_bytes(repo, "ls-files", "--stage", "-z").stdout)
    tree_entries = parse_tree_snapshot(
        run_git_bytes(repo, "ls-tree", "-r", "-z", "--full-tree", head_commit).stdout
    )
    issues: list[str] = []
    if index_entries != tree_entries:
        issues.append("Git index does not exactly match the audited HEAD tree")

    mismatches = 0
    unsupported = 0
    for raw_path, (mode, expected_object) in index_entries.items():
        if mode == "160000":
            unsupported += 1
            continue
        if mode not in {"100644", "100755", "120000"}:
            unsupported += 1
            continue
        try:
            observed_object, metadata = worktree_blob_digest(repo, raw_path, mode, object_format)
        except (FileNotFoundError, OSError, RuntimeError):
            mismatches += 1
            continue
        if mode == "120000" and not (
            stat.S_ISLNK(metadata.st_mode) or (os.name == "nt" and stat.S_ISREG(metadata.st_mode))
        ):
            mismatches += 1
        if os.name != "nt" and mode in {"100644", "100755"}:
            executable = bool(metadata.st_mode & 0o111)
            if executable != (mode == "100755"):
                mismatches += 1
        if observed_object != expected_object:
            mismatches += 1
    if unsupported:
        issues.append(f"worktree contains {unsupported} unsupported tracked entry type(s)")
    if mismatches:
        issues.append(f"worktree bytes or modes differ for {mismatches} tracked path(s)")

    untracked = [
        value
        for value in run_git_bytes(repo, "ls-files", "--others", "-z").stdout.split(b"\0")
        if value and value not in allowed_untracked
    ]
    if untracked:
        issues.append(
            f"worktree contains {len(untracked)} untracked path(s), including ignored paths"
        )
    return issues


def normalize_legal_bytes(data: bytes) -> bytes | None:
    if data.startswith((codecs.BOM_UTF8, codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return None
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    normalized = data.replace(b"\r\n", b"\n")
    if b"\r" in normalized:
        return None
    return normalized.rstrip(b"\n")


def apache_license_bytes_are_canonical(data: bytes) -> bool:
    normalized = normalize_legal_bytes(data)
    if normalized is None:
        return False
    digest = hashlib.sha256(normalized).hexdigest()
    return digest == APACHE_2_NORMALIZED_SHA256


def parse_allowed_signer(value: str) -> str:
    candidate = value.strip()
    if candidate.casefold().startswith("gpg:"):
        fingerprint = candidate[4:].replace(" ", "").upper()
        if not re.fullmatch(r"[0-9A-F]{40}|[0-9A-F]{64}", fingerprint):
            raise argparse.ArgumentTypeError(
                "GPG signers must use gpg:<40-or-64-digit-fingerprint>"
            )
        return f"gpg:{fingerprint}"
    if candidate.startswith("ssh-key:SHA256:") and len(candidate) > len("ssh-key:SHA256:"):
        return candidate
    if candidate.startswith("ssh-principal:") and candidate[len("ssh-principal:") :].strip():
        return candidate
    raise argparse.ArgumentTypeError(
        "Expected gpg:<fingerprint>, ssh-key:SHA256:<fingerprint>, or ssh-principal:<principal>"
    )


def parse_absolute_program(value: str) -> str:
    path = Path(value).expanduser()
    if not path.is_absolute() or not path.is_file():
        raise argparse.ArgumentTypeError("Expected an absolute path to an existing program")
    return str(path.resolve())


def parse_sha256(value: str) -> str:
    digest = value.strip().casefold()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise argparse.ArgumentTypeError("Expected a 64-digit SHA-256 digest")
    return digest


def parse_positive_integer(value: str) -> int:
    try:
        parsed = int(value, 10)
    except ValueError as error:
        raise argparse.ArgumentTypeError("Expected a positive integer") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError("Expected a positive integer")
    return parsed


def verified_signature_identities(output: str) -> set[str]:
    identities: set[str] = set()
    for line in output.splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[:2] == ["[GNUPG:]", "VALIDSIG"]:
            for candidate in (fields[2], fields[-1]):
                if re.fullmatch(r"[0-9A-Fa-f]{40}|[0-9A-Fa-f]{64}", candidate):
                    identities.add(f"gpg:{candidate.upper()}")

    ssh_pattern = re.compile(
        r'^Good ["\']git["\'] signature for (.+?) with \S+ key (SHA256:[A-Za-z0-9+/=]+)\s*$',
        re.MULTILINE,
    )
    for match in ssh_pattern.finditer(output):
        identities.add(f"ssh-principal:{match.group(1).strip()}")
        identities.add(f"ssh-key:{match.group(2)}")
    return identities


def verify_signature(
    repo: Path,
    object_kind: str,
    object_name: str,
    allowed_signers: list[str],
    gpg_program: str | None,
    ssh_keygen_program: str | None,
) -> tuple[bool, str]:
    object_data = run_git(repo, "cat-file", "-p", object_name).stdout
    if "-----BEGIN PGP SIGNATURE-----" in object_data:
        signature_kind = "gpg"
        if gpg_program is None:
            return False, f"GPG verifier program was not approved for {object_kind}: {object_name}"
        try:
            assert_trusted_program_unchanged(gpg_program, "GPG verifier")
        except RuntimeError:
            return False, f"GPG verifier identity changed for {object_kind}: {object_name}"
        verification_arguments = (
            "-c",
            "gpg.format=openpgp",
            "-c",
            f"gpg.program={gpg_program}",
        )
    elif "-----BEGIN SSH SIGNATURE-----" in object_data:
        signature_kind = "ssh"
        if ssh_keygen_program is None:
            return False, f"SSH verifier program was not approved for {object_kind}: {object_name}"
        try:
            assert_trusted_program_unchanged(ssh_keygen_program, "ssh-keygen verifier")
        except RuntimeError:
            return False, f"ssh-keygen verifier identity changed for {object_kind}: {object_name}"
        verification_arguments = (
            "-c",
            "gpg.format=ssh",
            "-c",
            f"gpg.ssh.program={ssh_keygen_program}",
        )
    else:
        return False, f"unsupported or missing {object_kind} signature: {object_name}"

    verification = run_git(
        repo,
        *verification_arguments,
        f"verify-{object_kind}",
        "--raw",
        object_name,
        check=False,
    )
    output = "\n".join((verification.stdout, verification.stderr))
    if verification.returncode != 0:
        return False, f"{object_kind} signature could not be verified: {object_name}"
    verified_identities = verified_signature_identities(output)
    if signature_kind == "gpg":
        matched = verified_identities.intersection(
            signer for signer in allowed_signers if signer.startswith("gpg:")
        )
    else:
        approved_keys = {signer for signer in allowed_signers if signer.startswith("ssh-key:")}
        approved_principals = {
            signer for signer in allowed_signers if signer.startswith("ssh-principal:")
        }
        matched_keys = verified_identities.intersection(approved_keys)
        matched_principals = verified_identities.intersection(approved_principals)
        if not matched_keys or (approved_principals and not matched_principals):
            return (
                False,
                f"{object_kind} SSH key or principal is not in the approved signer set: "
                f"{object_name}",
            )
        matched = matched_keys.union(matched_principals)
    if not matched:
        return False, f"{object_kind} signer is not in the approved signer set: {object_name}"
    identity = sorted(matched)[0]
    return True, f"verified {object_kind} signer {identity}: {object_name}"


def parse_version_pattern(value: str) -> tuple[str, re.Pattern[str]]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("Expected PATH=REGEX")
    path, pattern = value.split("=", 1)
    try:
        compiled = re.compile(pattern, re.MULTILINE)
    except re.error as error:
        raise argparse.ArgumentTypeError(f"Invalid regex: {error}") from error
    if compiled.groups < 1:
        raise argparse.ArgumentTypeError("REGEX must capture the version in group 1")
    return path, compiled


def parse_member_rule(value: str) -> tuple[str, str]:
    artifact_name, separator, pattern = value.partition("=")
    if not separator or not artifact_name.strip() or not pattern.strip():
        raise argparse.ArgumentTypeError("Expected ARTIFACT-BASENAME=MEMBER-GLOB")
    normalized = pattern.replace("\\", "/").strip()
    if (
        normalized in {"*", "**", "**/*"}
        or normalized.startswith("/")
        or ".." in PurePosixPath(normalized).parts
        or any(character in normalized for character in "[]")
        or "***" in normalized
        or any(ord(character) < 32 or ord(character) == 127 for character in normalized)
    ):
        raise argparse.ArgumentTypeError(
            "Member glob must be scoped and use only literals, *, **, and ?"
        )
    return artifact_name.strip(), normalized


def parse_exact_member_rule(value: str) -> tuple[str, str]:
    artifact_name, member = parse_member_rule(value)
    if any(character in member for character in "*?["):
        raise argparse.ArgumentTypeError("Legal member paths must be exact, not globs")
    return artifact_name, member


def parse_artifact_pair(value: str) -> tuple[str, str]:
    artifact_name, separator, bundle_name = value.partition("=")
    if (
        not separator
        or not artifact_name.strip()
        or not bundle_name.strip()
        or Path(artifact_name.strip()).name != artifact_name.strip()
        or Path(bundle_name.strip()).name != bundle_name.strip()
    ):
        raise argparse.ArgumentTypeError("Expected ARTIFACT-BASENAME=BUNDLE-BASENAME")
    return artifact_name.strip(), bundle_name.strip()


def parse_artifact_digest(value: str) -> tuple[str, str]:
    artifact_name, separator, digest = value.partition("=")
    artifact_name = artifact_name.strip()
    digest = digest.strip().casefold()
    if (
        not separator
        or Path(artifact_name).name != artifact_name
        or not re.fullmatch(r"[0-9a-f]{64}", digest)
    ):
        raise argparse.ArgumentTypeError("Expected ARTIFACT-BASENAME=SHA256")
    return artifact_name, digest


def parse_archive_format(value: str) -> tuple[str, str]:
    artifact_name, separator, archive_format = value.partition("=")
    artifact_name = artifact_name.strip()
    archive_format = archive_format.strip().casefold()
    if (
        not separator
        or Path(artifact_name).name != artifact_name
        or archive_format not in {"tar", "zip"}
    ):
        raise argparse.ArgumentTypeError("Expected ARTIFACT-BASENAME=tar|zip")
    return artifact_name, archive_format


def parse_repo_directory(value: str) -> str:
    normalized = value.replace("\\", "/").strip().rstrip("/")
    path = PurePosixPath(normalized)
    if (
        not normalized
        or path.is_absolute()
        or re.match(r"^[A-Za-z]:", normalized)
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise argparse.ArgumentTypeError("Expected a safe repository-relative directory")
    return normalized


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit release repository and artifact state.")
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
    parser.add_argument("--version", required=True)
    parser.add_argument("--version-source", action="append", default=[])
    parser.add_argument(
        "--version-pattern",
        action="append",
        default=[],
        type=parse_version_pattern,
        metavar="PATH=REGEX",
    )
    parser.add_argument("--artifact", action="append", default=[])
    parser.add_argument(
        "--staging-directory",
        type=Path,
        help="New empty absolute directory for content-addressed, read-only snapshots",
    )
    parser.add_argument(
        "--max-artifact-bytes",
        type=parse_positive_integer,
        help="Plan-approved maximum size of each supplied artifact",
    )
    parser.add_argument(
        "--archive-format",
        action="append",
        default=[],
        type=parse_archive_format,
        metavar="ARTIFACT=tar|zip",
        help="Bind each archive artifact to its approved outer container type",
    )
    parser.add_argument(
        "--require-member",
        action="append",
        default=[],
        type=parse_member_rule,
        metavar="ARTIFACT=GLOB",
        help="Required top-level archive member pattern; repeat as needed",
    )
    parser.add_argument(
        "--allow-member",
        action="append",
        default=[],
        type=parse_member_rule,
        metavar="ARTIFACT=GLOB",
        help="Allowed top-level archive member pattern; repeat to form an allowlist",
    )
    parser.add_argument(
        "--license-member",
        action="append",
        default=[],
        type=parse_exact_member_rule,
        metavar="ARTIFACT=PATH",
        help="Exact project LICENSE member to verify; one required per archive",
    )
    parser.add_argument(
        "--notice-member",
        action="append",
        default=[],
        type=parse_exact_member_rule,
        metavar="ARTIFACT=PATH",
        help="Exact project NOTICE member to verify; one required per archive",
    )
    parser.add_argument(
        "--adapter-inspected",
        action="append",
        default=[],
        type=parse_artifact_digest,
        metavar="ARTIFACT-BASENAME=SHA256",
        help="Bind completed adapter-specific inspection to exact artifact bytes",
    )
    parser.add_argument(
        "--metadata-member",
        action="append",
        default=[],
        type=parse_exact_member_rule,
        metavar="ARTIFACT=PATH",
        help="Exact project-owned archive metadata member used for version verification",
    )
    parser.add_argument(
        "--legal-bundle",
        action="append",
        default=[],
        type=parse_artifact_pair,
        metavar="ARTIFACT=BUNDLE",
        help="Inspected co-distributed archive containing a bare artifact plus legal files",
    )
    parser.add_argument(
        "--private-input",
        action="append",
        required=True,
        type=Path,
        help="Ordinary private input; include exactly one live plan.md and omit its approved snapshot",
    )
    parser.add_argument(
        "--approved-plan-snapshot",
        required=True,
        type=Path,
        help="Separate, byte-identical private snapshot of the approved live plan",
    )
    parser.add_argument(
        "--private-input-set-sha256",
        required=True,
        type=parse_sha256,
        help="Plan-recorded digest binding every canonical private path and current byte hash",
    )
    parser.add_argument(
        "--tag-only-distribution",
        action="store_true",
        help="Allow a source-only distribution whose immutable Git tag is the release artifact",
    )
    parser.add_argument("--tag")
    parser.add_argument("--default-branch", default="main")
    parser.add_argument("--require-signed-tag", action="store_true")
    parser.add_argument("--require-signed-commits", action="store_true")
    parser.add_argument(
        "--allowed-signer",
        action="append",
        default=[],
        type=parse_allowed_signer,
        help=(
            "Approved gpg:<fingerprint>, ssh-key:SHA256:<fingerprint>, or "
            "ssh-principal:<principal>; repeat for each signer"
        ),
    )
    parser.add_argument(
        "--gpg-program",
        type=parse_absolute_program,
        help="Approved absolute path to the GPG verifier",
    )
    parser.add_argument(
        "--gpg-program-sha256",
        type=parse_sha256,
        help="Approved SHA-256 of the GPG verifier",
    )
    parser.add_argument(
        "--ssh-keygen-program",
        type=parse_absolute_program,
        help="Approved absolute path to the ssh-keygen verifier",
    )
    parser.add_argument(
        "--ssh-keygen-program-sha256",
        type=parse_sha256,
        help="Approved SHA-256 of the ssh-keygen verifier",
    )
    parser.add_argument("--copyright-year", required=True)
    parser.add_argument("--copyright-holder", required=True)
    parser.add_argument("--expect-docs", action="store_true")
    parser.add_argument("--expect-website", action="store_true")
    parser.add_argument(
        "--docs-path",
        action="append",
        default=[],
        type=parse_repo_directory,
        help="Expected repository-relative documentation directory; repeat as needed",
    )
    parser.add_argument(
        "--website-path",
        action="append",
        default=[],
        type=parse_repo_directory,
        help="Expected repository-relative website directory; repeat as needed",
    )
    return parser.parse_args()


def main() -> int:
    global GIT_PROGRAM, GIT_PROGRAM_IDENTITY, LOG_PRIVATE_BYTE_PATTERN
    args = parse_args()
    failures: list[str] = []
    evidence: list[str] = []

    try:
        GIT_PROGRAM, GIT_PROGRAM_IDENTITY = verify_trusted_program(
            args.git_program, args.git_program_sha256, "Git executable"
        )
        repo_candidate = args.repo.resolve()
        preflight_program_location(GIT_PROGRAM, repo_candidate, "Git executable")
        preflight_local_git_config(repo_candidate)
        for verifier, digest, label in (
            (args.gpg_program, args.gpg_program_sha256, "GPG verifier"),
            (
                args.ssh_keygen_program,
                args.ssh_keygen_program_sha256,
                "ssh-keygen verifier",
            ),
        ):
            if verifier and digest:
                resolved_verifier, _ = verify_trusted_program(verifier, digest, label)
                preflight_program_location(resolved_verifier, repo_candidate, label)
        repo = repo_root(repo_candidate)
        ensure_program_outside_repo(GIT_PROGRAM, repo)
        for verifier in (args.gpg_program, args.ssh_keygen_program):
            if verifier:
                ensure_program_outside_repo(verifier, repo)
        reject_grafts(repo)
        reject_partial_clone(repo)
        reject_sparse_or_optimized_index(repo)
        ordinary_private_inputs = [
            path if path.is_absolute() else repo / path for path in args.private_input
        ]
        if not {"idea.md", "plan.md"}.issubset(
            {path.name.casefold() for path in ordinary_private_inputs}
        ):
            raise RuntimeError("--private-input must include both idea.md and plan.md")
        current_plans = [
            path for path in ordinary_private_inputs if path.name.casefold() == "plan.md"
        ]
        if len(current_plans) != 1:
            raise RuntimeError("--private-input must include exactly one live plan.md")
        approved_plan_snapshot = args.approved_plan_snapshot
        if not approved_plan_snapshot.is_absolute():
            approved_plan_snapshot = repo / approved_plan_snapshot
        if any(
            private_path_key(approved_plan_snapshot) == private_path_key(path)
            for path in ordinary_private_inputs
        ):
            raise RuntimeError(
                "the approved plan snapshot must be separate from every --private-input"
            )
        private_input_paths = [*ordinary_private_inputs, approved_plan_snapshot]
        private_set_digest_before = private_input_set_digest(private_input_paths)
        if private_set_digest_before != args.private_input_set_sha256:
            raise RuntimeError("the private-input set does not match its approved digest")
        if (
            hashlib.sha256(current_plans[0].read_bytes()).digest()
            != hashlib.sha256(approved_plan_snapshot.read_bytes()).digest()
        ):
            raise RuntimeError("the live plan does not match the approved plan snapshot")
        (
            private_exact_hashes,
            private_normalized_documents,
            private_fragments,
            private_binary_fragments,
        ) = load_private_fingerprints(private_input_paths)
        LOG_PRIVATE_BYTE_PATTERN, _ = compile_private_byte_pattern(private_binary_fragments)
        private_names = {path.name.casefold() for path in private_input_paths}
        PRIVATE_NAMES.update(private_names)
    except (OSError, RuntimeError) as error:
        print(f"ERROR: {terminal_safe(str(error))}", file=sys.stderr)
        return 2

    git_version = run_git(repo, "--version").stdout.strip()
    if (
        not git_version.startswith("git version ")
        or len(git_version) > 256
        or any(ord(character) < 32 or ord(character) == 127 for character in git_version)
    ):
        print("ERROR: approved Git executable returned an invalid version", file=sys.stderr)
        return 2
    evidence.append(
        f"Git executable: {GIT_PROGRAM} ({git_version}; sha256 {args.git_program_sha256})"
    )

    head_commit = run_git(repo, "rev-parse", "HEAD").stdout.strip()
    try:
        allowed_private_untracked: set[bytes] = set()
        for private_path in private_input_paths:
            try:
                relative_private = private_path.resolve().relative_to(repo).as_posix()
            except ValueError:
                continue
            allowed_private_untracked.add(os.fsencode(relative_private))
        failures.extend(
            filter_free_clean_checkout_issues(
                repo,
                head_commit,
                allowed_private_untracked,
            )
        )
    except RuntimeError as error:
        print(f"ERROR: {terminal_safe(str(error))}", file=sys.stderr)
        return 2
    if run_git(repo, "rev-parse", "HEAD").stdout.strip() != head_commit:
        print("ERROR: HEAD changed while the clean checkout was audited", file=sys.stderr)
        return 2
    default_branch_result = run_git(repo, "rev-parse", args.default_branch, check=False)
    default_branch_commit = default_branch_result.stdout.strip()
    if default_branch_result.returncode != 0:
        failures.append(f"default branch ref does not exist: {args.default_branch}")

    audit_ref = head_commit
    signing_required = args.require_signed_tag or args.require_signed_commits
    if signing_required and not args.allowed_signer:
        failures.append("signature verification requires at least one --allowed-signer")
    if any(signer.startswith("gpg:") for signer in args.allowed_signer) and not args.gpg_program:
        failures.append("approved GPG signers require --gpg-program")
    if args.gpg_program and not args.gpg_program_sha256:
        failures.append("--gpg-program requires --gpg-program-sha256")
    if any(signer.startswith("ssh-") for signer in args.allowed_signer):
        if not any(signer.startswith("ssh-key:") for signer in args.allowed_signer):
            failures.append("SSH signer approval must include an ssh-key:SHA256 fingerprint")
        if not args.ssh_keygen_program:
            failures.append("approved SSH signers require --ssh-keygen-program")
    if args.ssh_keygen_program and not args.ssh_keygen_program_sha256:
        failures.append("--ssh-keygen-program requires --ssh-keygen-program-sha256")
    if args.tag:
        tag_ref = f"refs/tags/{args.tag}"
        object_type = run_git(repo, "cat-file", "-t", tag_ref, check=False)
        if object_type.returncode != 0:
            failures.append(f"tag does not exist: {args.tag}")
        else:
            if object_type.stdout.strip() != "tag":
                failures.append(f"tag is not annotated: {args.tag}")
            else:
                tag_object = run_git(repo, "cat-file", "-p", tag_ref)
                embedded_tag_name: str | None = None
                embedded_object_type: str | None = None
                for line in tag_object.stdout.splitlines():
                    if not line:
                        break
                    if line.startswith("tag "):
                        embedded_tag_name = line[4:]
                    elif line.startswith("type "):
                        embedded_object_type = line[5:]
                if embedded_tag_name != args.tag:
                    failures.append(
                        f"annotated tag object name mismatch: expected {args.tag}, "
                        f"found {embedded_tag_name or '<missing>'}"
                    )
                if embedded_object_type != "commit":
                    failures.append(
                        "annotated release tag must point directly to a commit, "
                        f"not {embedded_object_type or '<missing>'}"
                    )
            expected_tag = f"v{args.version}"
            if args.tag != expected_tag:
                failures.append(f"tag mismatch: expected {expected_tag}, found {args.tag}")
            tag_commit = run_git(repo, "rev-parse", f"{tag_ref}^{{commit}}").stdout.strip()
            audit_ref = tag_commit
            evidence.append(f"tag commit: {tag_commit}")
            if tag_commit != head_commit:
                failures.append("tag commit is not the current HEAD")
            if default_branch_commit and tag_commit != default_branch_commit:
                failures.append(f"tag commit is not the tip of {args.default_branch}")
            if args.require_signed_tag:
                valid, message = verify_signature(
                    repo,
                    "tag",
                    args.tag,
                    args.allowed_signer,
                    args.gpg_program,
                    args.ssh_keygen_program,
                )
                (evidence if valid else failures).append(message)
    else:
        if args.require_signed_tag:
            failures.append("--require-signed-tag requires --tag")
        if default_branch_commit and head_commit != default_branch_commit:
            failures.append(f"HEAD is not the tip of {args.default_branch}")

    evidence.append(f"audited commit: {audit_ref}")

    if args.require_signed_commits:
        commits = run_git(repo, "rev-list", "--reverse", audit_ref, check=False)
        if commits.returncode != 0:
            failures.append("could not enumerate bootstrap commits for signature verification")
        else:
            verified_commit_count = 0
            for commit in (value for value in commits.stdout.splitlines() if value):
                valid, message = verify_signature(
                    repo,
                    "commit",
                    commit,
                    args.allowed_signer,
                    args.gpg_program,
                    args.ssh_keygen_program,
                )
                if valid:
                    verified_commit_count += 1
                else:
                    failures.append(message)
            evidence.append(f"verified signed commits: {verified_commit_count}")

    required_text: dict[str, str] = {}
    for relative in REQUIRED_FILES:
        try:
            text = tree_file_text(repo, audit_ref, relative)
        except ValueError as error:
            failures.append(str(error))
            continue
        if text is None:
            failures.append(f"missing required file at audited commit: {relative}")
        else:
            required_text[relative] = text

    expected_docs_paths = [*args.docs_path, *(("docs",) if args.expect_docs else ())]
    expected_website_paths = [
        *args.website_path,
        *(("website",) if args.expect_website else ()),
    ]
    for docs_path in dict.fromkeys(expected_docs_paths):
        if not tree_directory_exists(repo, audit_ref, docs_path):
            failures.append(
                f"expected documentation directory is missing at audited commit: {docs_path}"
            )
    for website_path in dict.fromkeys(expected_website_paths):
        if not tree_directory_exists(repo, audit_ref, website_path):
            failures.append(
                f"expected website directory is missing at audited commit: {website_path}"
            )

    license_bytes = tree_file_bytes(repo, audit_ref, "LICENSE")
    if license_bytes is not None and not apache_license_bytes_are_canonical(license_bytes):
        failures.append("LICENSE is not the unmodified canonical Apache License 2.0 text")

    if not re.fullmatch(r"[0-9]{4}(?:-[0-9]{4})?", args.copyright_year):
        failures.append("--copyright-year must be YYYY or YYYY-YYYY")
    if not args.copyright_holder.strip():
        failures.append("--copyright-holder must not be blank")
    notice_bytes = tree_file_bytes(repo, audit_ref, "NOTICE")
    normalized_notice_bytes = (
        normalize_legal_bytes(notice_bytes) if notice_bytes is not None else None
    )
    if notice_bytes is not None and normalized_notice_bytes is None:
        failures.append("NOTICE must be UTF-8 without a BOM and use LF or CRLF line endings")
    notice = (
        normalized_notice_bytes.decode("utf-8") if normalized_notice_bytes is not None else None
    )
    expected_notice = f"Copyright {args.copyright_year} {args.copyright_holder.strip()}"
    if notice is not None and expected_notice not in (line.strip() for line in notice.splitlines()):
        failures.append("NOTICE does not contain the approved copyright holder and year")

    readme = required_text.get("README.md")
    if readme is not None:
        if not re.search(r"<div\s+align=['\"]center['\"]", readme, re.IGNORECASE):
            failures.append("README is missing the centered masthead")
        if not re.search(r"<img\b[^>]*(?:banner|social)", readme, re.IGNORECASE):
            failures.append("README masthead does not reference a banner image")

    changelog = required_text.get("CHANGELOG.md")
    if changelog is not None and args.version not in changelog:
        failures.append(f"CHANGELOG.md does not mention version {args.version}")

    private_history = history_private_names(repo, private_names)
    if private_history:
        for history_path in sorted(private_history, key=str.casefold):
            failures.append(
                f"private planning filename exists in reachable history: {history_path}"
            )

    version_sources = list(args.version_source)
    if not version_sources and not args.version_pattern and not args.tag_only_distribution:
        version_sources = default_version_source_names(repo, audit_ref)
    if not version_sources and not args.version_pattern and not args.tag_only_distribution:
        failures.append("no supported version source was found or supplied")
    for version_source_name in version_sources:
        try:
            version_source_text = tree_file_text(repo, audit_ref, version_source_name)
            if version_source_text is None:
                raise ValueError("file is missing at the audited commit")
            observed = manifest_version(version_source_name, version_source_text)
        except (ValueError, json.JSONDecodeError) as error:
            failures.append(f"could not read version from {version_source_name}: {error}")
            continue
        if observed != args.version:
            failures.append(
                f"version mismatch in {version_source_name}: "
                f"expected {args.version}, found {observed}"
            )
        else:
            evidence.append(f"version {observed}: {version_source_name}")

    for relative, pattern in args.version_pattern:
        try:
            pattern_text = tree_file_text(repo, audit_ref, relative)
        except ValueError as error:
            failures.append(f"could not read version pattern source {relative}: {error}")
            continue
        if pattern_text is None:
            failures.append(f"version pattern source is missing at audited commit: {relative}")
            continue
        match = pattern.search(pattern_text)
        if not match:
            failures.append(f"version pattern did not match {relative}")
        elif match.group(1) != args.version:
            failures.append(
                f"version mismatch in {relative}: expected {args.version}, found {match.group(1)}"
            )
        else:
            evidence.append(f"version {match.group(1)}: {relative}")

    if args.tag_only_distribution and not args.tag:
        failures.append("--tag-only-distribution requires --tag")
    if not args.artifact and not args.tag_only_distribution:
        failures.append("no release artifact was supplied")

    required_member_rules: dict[str, list[str]] = {}
    allowed_member_rules: dict[str, list[str]] = {}
    license_member_rules: dict[str, list[str]] = {}
    notice_member_rules: dict[str, list[str]] = {}
    metadata_member_rules: dict[str, list[str]] = {}
    archive_formats: dict[str, str] = {}
    for artifact_name, archive_format in args.archive_format:
        if artifact_name in archive_formats:
            failures.append(f"artifact has more than one --archive-format: {artifact_name}")
        archive_formats[artifact_name] = archive_format
    for artifact_name, pattern in args.require_member:
        required_member_rules.setdefault(artifact_name, []).append(pattern)
    for artifact_name, pattern in args.allow_member:
        allowed_member_rules.setdefault(artifact_name, []).append(pattern)
    for artifact_name, member in args.license_member:
        license_member_rules.setdefault(artifact_name, []).append(member)
    for artifact_name, member in args.notice_member:
        notice_member_rules.setdefault(artifact_name, []).append(member)
    for artifact_name, member in args.metadata_member:
        metadata_member_rules.setdefault(artifact_name, []).append(member)

    adapter_digests: dict[str, str] = {}
    for artifact_name, digest in args.adapter_inspected:
        if artifact_name in adapter_digests:
            failures.append(
                f"artifact has more than one --adapter-inspected digest: {artifact_name}"
            )
        adapter_digests[artifact_name] = digest

    supplied_artifact_names = {Path(value).name for value in args.artifact}
    legal_bundles: dict[str, str] = {}
    for artifact_name, bundle_name in args.legal_bundle:
        if artifact_name in legal_bundles:
            failures.append(f"artifact has more than one --legal-bundle: {artifact_name}")
        legal_bundles[artifact_name] = bundle_name
        if artifact_name == bundle_name:
            failures.append(f"artifact cannot be its own legal bundle: {artifact_name}")
    for artifact_name, bundle_name in sorted(legal_bundles.items()):
        if artifact_name not in supplied_artifact_names:
            failures.append(f"legal-bundle rule names an unsupplied artifact: {artifact_name}")
        if bundle_name not in supplied_artifact_names:
            failures.append(f"legal-bundle rule names an unsupplied bundle: {bundle_name}")
    for rule_name in sorted(
        {
            *required_member_rules,
            *allowed_member_rules,
            *license_member_rules,
            *notice_member_rules,
            *metadata_member_rules,
            *archive_formats,
            *adapter_digests,
        }.difference(supplied_artifact_names)
    ):
        failures.append(f"artifact rule names an unsupplied artifact: {rule_name}")

    staging_directory: Path | None = None
    if args.artifact:
        if args.max_artifact_bytes is None:
            failures.append("release artifacts require --max-artifact-bytes")
        if args.staging_directory is None:
            failures.append("release artifacts require --staging-directory")
        elif not args.staging_directory.is_absolute():
            failures.append("--staging-directory must be an absolute path")
        else:
            staging_directory = args.staging_directory.resolve()
            if path_is_within(staging_directory, repo):
                failures.append("artifact staging directory must be outside the audited worktree")
                staging_directory = None
            elif staging_directory.exists():
                try:
                    metadata = staging_directory.lstat()
                    attributes = getattr(metadata, "st_file_attributes", 0)
                    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
                    if (
                        not stat.S_ISDIR(metadata.st_mode)
                        or stat.S_ISLNK(metadata.st_mode)
                        or (reparse_flag and attributes & reparse_flag)
                        or any(staging_directory.iterdir())
                    ):
                        failures.append(
                            "artifact staging directory must be a new or empty plain directory"
                        )
                        staging_directory = None
                except OSError:
                    failures.append("artifact staging directory cannot be inspected safely")
                    staging_directory = None

    artifact_paths_by_name: dict[str, Path] = {}
    artifact_digests_by_name: dict[str, str] = {}
    seen_artifact_names: set[str] = set()
    unsafe_artifact_names: set[str] = set()
    for value in args.artifact:
        source_path = Path(value)
        if not source_path.is_absolute():
            source_path = repo / source_path
        artifact_name = source_path.name
        if artifact_name in seen_artifact_names:
            failures.append(f"artifact basenames must be unique: {artifact_name}")
            continue
        seen_artifact_names.add(artifact_name)
        if source_path.is_symlink():
            failures.append(f"artifact path is a symlink: {source_path}")
            continue
        if not source_path.is_file():
            failures.append(f"artifact does not exist: {source_path}")
            continue
        if source_path.stat().st_size == 0:
            failures.append(f"artifact is empty: {source_path}")
            continue
        if staging_directory is None or args.max_artifact_bytes is None:
            continue
        try:
            artifact_path, artifact_digest = snapshot_artifact(
                source_path, staging_directory, args.max_artifact_bytes
            )
        except (OSError, RuntimeError) as error:
            failures.append(f"could not snapshot artifact {artifact_name}: {error}")
            continue
        artifact_paths_by_name[artifact_name] = artifact_path
        artifact_digests_by_name[artifact_name] = artifact_digest
        evidence.append(f"content-addressed read-only snapshot {artifact_path}: {artifact_name}")

        raw_scan_budget = ArchiveBudget(
            private_exact_hashes=private_exact_hashes,
            private_normalized_documents=private_normalized_documents,
            private_fragments=private_fragments,
            private_byte_fragments=private_binary_fragments,
        )
        with artifact_path.open("rb") as handle:
            raw_artifact_issues = stream_opaque_member_issues(
                handle,
                f"{artifact_name}!<raw-artifact>",
                "raw-artifact.bin",
                raw_scan_budget,
            )
        if raw_artifact_issues:
            unsafe_artifact_names.add(artifact_name)
        for issue in raw_artifact_issues:
            failures.append(f"artifact {artifact_name}: {issue}")
        evidence.append(f"raw artifact envelope scanned: {artifact_name}")

        expected_adapter_digest = adapter_digests.get(artifact_name)
        if expected_adapter_digest and expected_adapter_digest != artifact_digest:
            failures.append(
                f"adapter inspection digest mismatch for {artifact_name}: "
                f"expected {expected_adapter_digest}, found {artifact_digest}"
            )
        if not filename_contains_version(artifact_name, args.version):
            failures.append(
                f"artifact filename does not contain version {args.version}: {artifact_name}"
            )

        archive_report = inspect_archive(
            artifact_path,
            private_exact_hashes,
            private_normalized_documents,
            private_fragments,
            private_binary_fragments,
            notice_bytes or b"",
            set(license_member_rules.get(artifact_name, [])),
            set(notice_member_rules.get(artifact_name, [])),
        )
        if archive_report is None and expected_archive(artifact_path):
            unsafe_artifact_names.add(artifact_name)
            failures.append(
                f"artifact has an archive extension but cannot be opened: {artifact_name}"
            )
        elif archive_report is not None:
            detected_archive_format = "zip" if zipfile.is_zipfile(artifact_path) else "tar"
            approved_archive_format = archive_formats.get(artifact_name)
            if approved_archive_format is None:
                failures.append(f"archive has no --archive-format contract: {artifact_name}")
            elif approved_archive_format != detected_archive_format:
                failures.append(
                    f"archive format mismatch for {artifact_name}: expected "
                    f"{approved_archive_format}, found {detected_archive_format}"
                )
            names, archive_issues = archive_report
            if archive_issues:
                unsafe_artifact_names.add(artifact_name)
            failures.extend(
                f"artifact {artifact_name}: {archive_issue}" for archive_issue in archive_issues
            )
            evidence.append(f"archive entries {len(names)}: {artifact_name}")
            required_patterns = required_member_rules.get(artifact_name, [])
            allowed_patterns = allowed_member_rules.get(artifact_name, [])
            if not required_patterns:
                failures.append(f"archive has no --require-member contract: {artifact_name}")
            if not allowed_patterns:
                failures.append(f"archive has no --allow-member contract: {artifact_name}")
            if len(license_member_rules.get(artifact_name, [])) != 1:
                failures.append(
                    f"archive requires exactly one --license-member path: {artifact_name}"
                )
            if len(notice_member_rules.get(artifact_name, [])) != 1:
                failures.append(
                    f"archive requires exactly one --notice-member path: {artifact_name}"
                )
            for pattern in required_patterns:
                if not any(archive_contract_matches(name, pattern) for name in names):
                    failures.append(
                        f"archive is missing required member {pattern}: {artifact_name}"
                    )
            for name in names:
                if allowed_patterns and not any(
                    archive_contract_matches(name, pattern) for pattern in allowed_patterns
                ):
                    failures.append(
                        f"archive member is outside the approved allowlist: {artifact_name}!{name}"
                    )

            selected_metadata = metadata_member_rules.get(artifact_name, [])
            if archive_issues:
                failures.append(
                    f"artifact metadata verification skipped after structural failure: "
                    f"{artifact_name}"
                )
            elif len(selected_metadata) > 1:
                failures.append(f"archive has more than one --metadata-member: {artifact_name}")
            elif len(selected_metadata) == 1:
                try:
                    metadata_name, metadata_version = artifact_metadata_version(
                        artifact_path, selected_metadata[0]
                    )
                except (
                    OSError,
                    ValueError,
                    tarfile.TarError,
                    zipfile.BadZipFile,
                ) as error:
                    failures.append(
                        f"artifact metadata cannot be verified: {artifact_name}: {error}"
                    )
                else:
                    if metadata_version != args.version:
                        failures.append(
                            f"artifact metadata version mismatch in {metadata_name}: "
                            f"expected {args.version}, found {metadata_version}"
                        )
                    else:
                        evidence.append(
                            f"artifact version {metadata_version}: {artifact_name}!{metadata_name}"
                        )
            elif artifact_name not in adapter_digests:
                failures.append(
                    f"archive needs one --metadata-member or a digest-bound "
                    f"--adapter-inspected proof: {artifact_name}"
                )
        else:
            if artifact_name in archive_formats:
                failures.append(
                    f"--archive-format names an artifact that is not a supported archive: "
                    f"{artifact_name}"
                )
            if artifact_name not in adapter_digests:
                failures.append(
                    f"non-archive artifact lacks digest-bound --adapter-inspected proof: "
                    f"{artifact_name}"
                )
            if artifact_name not in legal_bundles:
                failures.append(
                    f"non-archive artifact lacks a co-distributed --legal-bundle: {artifact_name}"
                )
            artifact_size = artifact_path.stat().st_size
            if artifact_size > MAX_NONARCHIVE_SCAN_BYTES:
                evidence.append(f"streamed opaque artifact scan: {artifact_name}")
            else:
                data = artifact_path.read_bytes()
                scan_budget = ArchiveBudget(
                    private_exact_hashes=private_exact_hashes,
                    private_normalized_documents=private_normalized_documents,
                    private_fragments=private_fragments,
                    private_byte_fragments=private_binary_fragments,
                )
                for issue in archive_member_issues(artifact_name, artifact_name, data, scan_budget):
                    failures.append(f"artifact {artifact_name}: {issue}")
                evidence.append(f"bounded non-archive scan: {artifact_name}")
        evidence.append(f"sha256 {artifact_digest}: {artifact_name}")

    for artifact_name, bundle_name in sorted(legal_bundles.items()):
        public_artifact_path = artifact_paths_by_name.get(artifact_name)
        legal_bundle_path = artifact_paths_by_name.get(bundle_name)
        if (
            public_artifact_path is None
            or legal_bundle_path is None
            or not public_artifact_path.is_file()
            or not legal_bundle_path.is_file()
        ):
            continue
        if artifact_name in unsafe_artifact_names or bundle_name in unsafe_artifact_names:
            failures.append(
                f"legal-bundle digest comparison skipped after an unsafe artifact audit: "
                f"{bundle_name}"
            )
            continue
        try:
            bundled_digests = bundled_artifact_digests(
                legal_bundle_path,
                artifact_name,
                public_artifact_path.stat().st_size,
            )
        except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile) as error:
            failures.append(f"could not verify legal bundle {bundle_name}: {error}")
            continue
        if len(bundled_digests) != 1:
            failures.append(
                f"legal bundle must contain exactly one member named {artifact_name}: {bundle_name}"
            )
            continue
        member_name, bundled_digest = bundled_digests[0]
        public_digest = artifact_digests_by_name.get(artifact_name)
        if public_digest is None:
            failures.append(f"artifact snapshot digest is missing: {artifact_name}")
            continue
        if bundled_digest != public_digest:
            failures.append(
                f"legal bundle member bytes differ from {artifact_name}: "
                f"{bundle_name}!{member_name}"
            )
        else:
            evidence.append(
                f"co-distributed legal bundle matches {artifact_name}: {bundle_name}!{member_name}"
            )

    for artifact_name, artifact_path in sorted(artifact_paths_by_name.items()):
        expected_digest = artifact_digests_by_name[artifact_name]
        if sha256(artifact_path) != expected_digest:
            failures.append(
                f"content-addressed artifact snapshot changed during audit: {artifact_name}"
            )

    try:
        if private_input_set_digest(private_input_paths) != private_set_digest_before:
            failures.append("the private-input set changed during the release audit")
    except (OSError, RuntimeError):
        failures.append("the private-input set could not be reverified after the release audit")
    evidence.append(f"private input revisions verified: {len(set(private_input_paths))}")

    if failures:
        print(f"Release-state audit failed with {len(failures)} issue(s):")
        for failure in failures:
            print(f"  ERROR: {terminal_safe(failure)}")
        if evidence:
            print("Evidence collected before failure:")
            for item in evidence:
                print(f"  {terminal_safe(item)}")
        return 1

    print("Release-state audit passed")
    for item in evidence:
        print(f"  {terminal_safe(item)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
