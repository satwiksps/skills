#!/usr/bin/env python3
"""Protect private planning files from Git tracking and reachable history."""

from __future__ import annotations

import argparse
import base64
import binascii
import bz2
import codecs
import gzip
import hashlib
import io
import json
import lzma
import os
import re
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
import unicodedata
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

MARKER = "# Private planning files managed by build-open-source-software"
DEFAULT_NAMES = ("idea.md", "plan.md")
MAX_CONTENT_SCAN_BYTES = 100_000_000
MIN_PRIVATE_FRAGMENT_CHARS = 40
MIN_PRIVATE_DOCUMENT_CHARS = 12
MIN_RAW_FRAGMENT_CHARS = 40
MAX_RAW_FRAGMENT_CHARS = 2_048
LONG_RAW_WINDOW_CHARS = 48
LONG_RAW_WINDOW_STRIDE = 16
MAX_RAW_FRAGMENT_PATTERNS = 100_000
MAX_RAW_FRAGMENT_PATTERN_BYTES = 32_000_000
RAW_SCAN_CHUNK_BYTES = 1_048_576
MAX_TRANSFORM_DEPTH = 2
MAX_CONTAINER_ENTRIES = 100_000
MAX_ZIP_CENTRAL_DIRECTORY_BYTES = 64_000_000
MAX_LOCAL_GIT_CONTROL_BYTES = 1_000_000
LOG_RAW_PATTERN: re.Pattern[bytes] | None = None
LOG_SECRET_PATTERNS = (
    re.compile(r"\bgh[opsu]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bpypi-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bnpm_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----"),
)
GIT_COMMAND_PREFIX = ("-c", "core.fsmonitor=false", "-c", "core.hooksPath=")
STRONG_PRIVATE_MARKER = re.compile(
    r"\b(?:codename|confidential|internal|private|secret|unreleased)\b",
    re.IGNORECASE,
)
PRIVATE_VALUE_FIELD = re.compile(
    r"\b(?:(?:secret|private|internal)\s+)?(?:codename|credential|"
    r"(?:(?:api|access|auth)\s*)?token|password|(?:api|ssh|signing)\s+key|"
    r"secret\s+(?:value|key|identifier))\b\s*[:=]\s*(.+)$",
    re.IGNORECASE,
)
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
    "GIT_NAMESPACE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_REPLACE_REF_BASE",
    "GIT_SHALLOW_FILE",
    "GIT_WORK_TREE",
}


class GuardError(RuntimeError):
    pass


@dataclass
class TransformBudget:
    decoded_bytes: int = 0
    entries: int = 0


def terminal_safe(value: str) -> str:
    redacted = value
    for pattern in LOG_SECRET_PATTERNS:
        redacted = pattern.sub("<redacted secret>", redacted)
    if LOG_RAW_PATTERN is not None and LOG_RAW_PATTERN.search(
        unicodedata.normalize("NFC", redacted).encode("utf-8", errors="surrogatepass")
    ):
        redacted = "<redacted private diagnostic>"
    return json.dumps(redacted, ensure_ascii=True)[1:-1]


@dataclass(frozen=True)
class TrustedGit:
    path: Path
    sha256: str
    identity: tuple[int, int, int, int, int]


def is_reparse_point(metadata: os.stat_result) -> bool:
    file_attributes = getattr(metadata, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(reparse_flag and file_attributes & reparse_flag)


def path_is_within(path: Path, directory: Path) -> bool:
    try:
        common = os.path.commonpath((str(path), str(directory)))
    except ValueError:
        return False
    return os.path.normcase(common) == os.path.normcase(str(directory))


def executable_identity(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def resolve_git_program(value: Path, approved_sha256: str) -> TrustedGit:
    if not value.is_absolute():
        raise GuardError("--git-program must be an absolute path")
    if re.fullmatch(r"[0-9a-fA-F]{64}", approved_sha256) is None:
        raise GuardError("--git-program-sha256 must be exactly 64 hexadecimal characters")
    try:
        program = value.resolve(strict=True)
        metadata = program.lstat()
    except (OSError, RuntimeError) as error:
        raise GuardError("--git-program could not be resolved to a regular executable") from error
    if not stat.S_ISREG(metadata.st_mode) or not os.access(program, os.X_OK):
        raise GuardError("--git-program must resolve to a regular executable file")
    if any(ord(character) < 32 or ord(character) == 127 for character in str(program)):
        raise GuardError("--git-program path contains a control character")

    digest = hashlib.sha256()
    try:
        before = executable_identity(program.lstat())
        with program.open("rb") as handle:
            opened = executable_identity(os.fstat(handle.fileno()))
            while chunk := handle.read(1_048_576):
                digest.update(chunk)
            after_open = executable_identity(os.fstat(handle.fileno()))
        after_path = executable_identity(program.lstat())
    except OSError as error:
        raise GuardError("Could not hash --git-program safely") from error
    if before != opened or opened != after_open or after_open != after_path:
        raise GuardError("--git-program changed while its SHA-256 was being verified")
    actual_sha256 = digest.hexdigest()
    if actual_sha256 != approved_sha256.casefold():
        raise GuardError("--git-program does not match --git-program-sha256")
    return TrustedGit(program, actual_sha256, after_path)


def git_command(git_program: TrustedGit, *arguments: str) -> list[str]:
    try:
        current_identity = executable_identity(git_program.path.lstat())
    except OSError as error:
        raise GuardError("The approved Git executable is no longer available") from error
    if current_identity != git_program.identity:
        raise GuardError("The approved Git executable changed after verification")
    return [str(git_program.path), *GIT_COMMAND_PREFIX, *arguments]


def git_version(git_program: TrustedGit) -> str:
    result = subprocess.run(
        git_command(git_program, "--version"),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=git_environment(),
    )
    git_command(git_program)
    version = result.stdout.strip()
    if (
        result.returncode != 0
        or not version.startswith("git version ")
        or len(version) > 256
        or any(ord(character) < 32 or ord(character) == 127 for character in version)
    ):
        raise GuardError("The approved executable did not return a valid Git version")
    return version


def git_identity_record(git_program: TrustedGit, version: str) -> str:
    return json.dumps(
        {
            "git_program": str(git_program.path),
            "git_program_sha256": git_program.sha256,
            "git_version": version,
        },
        ensure_ascii=True,
        sort_keys=True,
    )


def detectable_worktree_root(candidate: Path) -> Path | None:
    """Find a conventional worktree marker without executing repository code."""
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
            raise GuardError("Could not inspect the candidate worktree boundary") from error
        else:
            return current.resolve()
        if current == current.parent:
            return None
        current = current.parent


def read_plain_git_control_file(path: Path, maximum_bytes: int) -> bytes:
    before = path.lstat()
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or is_reparse_point(before)
        or before.st_size > maximum_bytes
    ):
        raise GuardError("Git control file is not a bounded plain regular file")
    with path.open("rb") as handle:
        opened = os.fstat(handle.fileno())
        if executable_identity(opened) != executable_identity(before):
            raise GuardError("Git control file changed before inspection")
        data = handle.read(maximum_bytes + 1)
        after_open = os.fstat(handle.fileno())
    after_path = path.lstat()
    if (
        len(data) > maximum_bytes
        or executable_identity(opened) != executable_identity(after_open)
        or executable_identity(opened) != executable_identity(after_path)
    ):
        raise GuardError("Git control file changed during inspection")
    return data


def preflight_local_git_config(candidate: Path) -> None:
    root = detectable_worktree_root(candidate)
    if root is None:
        return
    marker = root / ".git"
    marker_metadata = marker.lstat()
    if stat.S_ISDIR(marker_metadata.st_mode):
        if stat.S_ISLNK(marker_metadata.st_mode) or is_reparse_point(marker_metadata):
            raise GuardError("Git directory cannot be a symlink or reparse point")
        git_directory = marker.resolve(strict=True)
    elif stat.S_ISREG(marker_metadata.st_mode):
        raw_marker = read_plain_git_control_file(marker, 4096)
        try:
            marker_text = raw_marker.decode("utf-8").strip()
        except UnicodeDecodeError as error:
            raise GuardError("Git worktree marker is not UTF-8") from error
        match = re.fullmatch(r"gitdir:\s*(.+)", marker_text, re.IGNORECASE)
        if match is None or any(ord(character) < 32 for character in match.group(1)):
            raise GuardError("Git worktree marker is malformed")
        reported = Path(match.group(1))
        git_directory = (reported if reported.is_absolute() else root / reported).resolve(
            strict=True
        )
    else:
        raise GuardError("Git worktree marker is not a plain file or directory")

    common_directory = git_directory
    commondir_path = git_directory / "commondir"
    if commondir_path.exists():
        raw_common = read_plain_git_control_file(commondir_path, 4096)
        try:
            common_text = raw_common.decode("utf-8").strip()
        except UnicodeDecodeError as error:
            raise GuardError("Git common-directory marker is not UTF-8") from error
        if not common_text or any(ord(character) < 32 for character in common_text):
            raise GuardError("Git common-directory marker is malformed")
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
            raise GuardError(
                "repository-local Git config contains includes or execution-capable settings"
            )


def require_git_outside_worktree(git_program: TrustedGit, worktree: Path) -> None:
    canonical_worktree = worktree.resolve()
    if path_is_within(git_program.path, canonical_worktree):
        raise GuardError("--git-program must be outside every audited Git worktree")


def preflight_git_location(git_program: TrustedGit, candidate: Path) -> None:
    detectable_root = detectable_worktree_root(candidate)
    if detectable_root is not None:
        require_git_outside_worktree(git_program, detectable_root)


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


def run_git(
    git_program: TrustedGit, repo: Path, *args: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        git_command(git_program, "-C", str(repo), *args),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=git_environment(),
    )
    git_command(git_program)
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "Git command failed"
        raise GuardError(detail)
    return result


def repository_root(git_program: TrustedGit, candidate: Path) -> Path:
    preflight_git_location(git_program, candidate)
    result = run_git(git_program, candidate, "rev-parse", "--show-toplevel")
    root = Path(result.stdout.strip()).resolve()
    require_git_outside_worktree(git_program, root)
    return root


def containing_repository(git_program: TrustedGit, candidate: Path) -> Path | None:
    current = candidate
    while not current.exists() and current != current.parent:
        current = current.parent
    detectable_root = detectable_worktree_root(current)
    if detectable_root is not None:
        require_git_outside_worktree(git_program, detectable_root)
        preflight_local_git_config(current)
    result = run_git(git_program, current, "rev-parse", "--show-toplevel", check=False)
    if result.returncode != 0:
        if detectable_root is not None:
            raise GuardError("Could not inspect a containing Git worktree")
        return None
    root = Path(result.stdout.strip()).resolve()
    require_git_outside_worktree(git_program, root)
    return root


def reject_grafts(git_program: TrustedGit, repo: Path) -> None:
    result = run_git(
        git_program,
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
            raise GuardError("Cannot prove private-file history while .git/info/grafts is nonempty")
    except OSError as error:
        raise GuardError(f"Could not inspect Git grafts file: {error}") from error


def reject_partial_clone(git_program: TrustedGit, repo: Path) -> None:
    partial = run_git(
        git_program,
        repo,
        "config",
        "--local",
        "--get",
        "extensions.partialClone",
        check=False,
    )
    promisors = run_git(
        git_program,
        repo,
        "config",
        "--local",
        "--get-regexp",
        r"^remote\..*\.promisor$",
        check=False,
    )
    if partial.returncode == 0 and partial.stdout.strip():
        raise GuardError("Cannot prove private-file history from a partial clone")
    if promisors.returncode == 0 and promisors.stdout.strip():
        raise GuardError("Cannot prove private-file history with a promisor remote")


def normalize_private_paths(repo: Path, values: list[str]) -> tuple[list[Path], set[str], set[str]]:
    if values and (
        len(values) < 2
        or not {"idea.md", "plan.md"}.issubset({Path(value).name.casefold() for value in values})
    ):
        raise GuardError("Explicit inputs must include both idea.md and plan.md paths")
    raw_values = values or [str(repo / name) for name in DEFAULT_NAMES]
    resolved: list[Path] = []
    names = {name.casefold() for name in DEFAULT_NAMES}
    relative_paths: set[str] = set()

    for value in raw_values:
        path = Path(value)
        if not path.is_absolute():
            path = repo / path
        path = Path(os.path.abspath(path))
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            metadata = None
        if metadata is not None and (stat.S_ISLNK(metadata.st_mode) or is_reparse_point(metadata)):
            raise GuardError("A private input must not be a symlink or reparse point")
        resolved.append(path)
        names.add(path.name.casefold())
        try:
            relative_paths.add(path.relative_to(repo).as_posix().casefold())
        except ValueError:
            pass

    return resolved, names, relative_paths


def private_path_key(path: Path) -> str:
    return os.path.normcase(str(path.resolve(strict=False)))


def private_input_set_digest(paths: list[Path]) -> str:
    records: list[bytes] = []
    seen_keys: set[str] = set()
    seen_files: list[Path] = []
    for path in sorted(paths, key=private_path_key):
        path_key = private_path_key(path)
        if path_key in seen_keys:
            raise GuardError("The private-input inventory contains a duplicate path")
        before_path = path.lstat()
        if (
            not stat.S_ISREG(before_path.st_mode)
            or stat.S_ISLNK(before_path.st_mode)
            or is_reparse_point(before_path)
        ):
            raise GuardError("Every private inventory item must be a plain regular file")
        if any(os.path.samefile(path, seen_path) for seen_path in seen_files):
            raise GuardError("The private-input inventory contains aliased files")
        seen_keys.add(path_key)
        seen_files.append(path)
        content_digest = hashlib.sha256()
        with path.open("rb") as handle:
            opened = os.fstat(handle.fileno())
            if executable_identity(opened) != executable_identity(before_path):
                raise GuardError("A private inventory item changed before hashing")
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                content_digest.update(block)
            after_open = os.fstat(handle.fileno())
        after_path = path.lstat()
        if executable_identity(opened) != executable_identity(after_open) or executable_identity(
            opened
        ) != executable_identity(after_path):
            raise GuardError("A private inventory item changed while hashing")
        canonical_path = os.path.normcase(str(path.resolve(strict=True))).encode(
            "utf-8", errors="surrogatepass"
        )
        records.append(canonical_path + b"\0" + content_digest.hexdigest().encode("ascii"))
    inventory_digest = hashlib.sha256()
    for record in records:
        inventory_digest.update(len(record).to_bytes(8, "big"))
        inventory_digest.update(record)
    return inventory_digest.hexdigest()


def split_nul(value: str) -> list[str]:
    return [item for item in value.split("\0") if item]


def decode_private_text(data: bytes) -> str | None:
    try:
        if data.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
            return data.decode("utf-32")
        if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
            return data.decode("utf-16")
        if data.startswith(codecs.BOM_UTF8):
            return data.decode("utf-8-sig")
        if b"\0" in data:
            return None
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def normalize_prose(text: str) -> str:
    normalized = unicodedata.normalize("NFC", text)
    return re.sub(r"\s+", " ", normalized).strip().casefold()


def without_allowlisted_public_lines(text: str) -> str:
    kept: list[str] = []
    for raw_line in text.splitlines():
        candidate = re.sub(r"^\s*(?:#{1,6}|[-*+] |\d+[.)] )", "", raw_line)
        if normalize_prose(candidate) in COMMON_PRIVATE_FRAGMENT_ALLOWLIST:
            continue
        kept.append(raw_line)
    return "\n".join(kept)


def strong_private_values(text: str) -> Iterator[str]:
    for raw_line in text.splitlines():
        assignment = PRIVATE_VALUE_FIELD.search(raw_line)
        if assignment is None:
            continue
        value = assignment.group(1).strip().rstrip(".,;").strip().strip("`'\"").strip()
        normalized = normalize_prose(value)
        if len(normalized) >= 8 and normalized not in COMMON_PRIVATE_FRAGMENT_ALLOWLIST:
            yield value
            if normalized != value:
                yield normalized


def distinctive_fragments(text: str) -> set[str]:
    fragments: set[str] = set()
    for paragraph in re.split(r"(?:\r?\n){2,}", text):
        normalized = normalize_prose(paragraph)
        if len(normalized) >= MIN_PRIVATE_FRAGMENT_CHARS:
            fragments.add(normalized)
        words = normalized.split()
        for start in range(0, max(0, len(words) - 11), 6):
            window = " ".join(words[start : start + 12])
            if len(window) >= 60:
                fragments.add(window)

    for raw_line in text.splitlines():
        line = normalize_prose(re.sub(r"^\s*(?:#{1,6}|[-*+] |\d+[.)] )", "", raw_line))
        sensitive = re.search(
            r"\b(?:codename|private|internal|unreleased|secret|domain|handle|package name|project name)\b",
            line,
        )
        if (
            len(line) >= 20 or (sensitive and len(line) >= 8)
        ) and line not in COMMON_PRIVATE_FRAGMENT_ALLOWLIST:
            fragments.add(line)
        for sentence in re.split(r"(?<=[.!?])\s+", line):
            if len(sentence) >= 30 and sentence not in COMMON_PRIVATE_FRAGMENT_ALLOWLIST:
                fragments.add(sentence)
    fragments.update(strong_private_values(text))
    return fragments


def raw_text_fragments(text: str) -> Iterator[str]:
    def emit(raw_candidate: str, allow_windows: bool) -> Iterator[str]:
        candidate = re.sub(r"^\s*(?:#{1,6}|[-*+] |\d+[.)] )", "", raw_candidate).strip()
        normalized = normalize_prose(candidate)
        is_strongly_private = (
            len(normalized) >= 8 and STRONG_PRIVATE_MARKER.search(normalized) is not None
        )
        if (
            len(normalized) < MIN_RAW_FRAGMENT_CHARS and not is_strongly_private
        ) or normalized in COMMON_PRIVATE_FRAGMENT_ALLOWLIST:
            return
        if len(candidate) <= MAX_RAW_FRAGMENT_CHARS:
            yield candidate
            if normalized != candidate:
                yield normalized
            return
        if not allow_windows:
            return
        for start in range(0, len(candidate), LONG_RAW_WINDOW_STRIDE):
            window = candidate[start : start + LONG_RAW_WINDOW_CHARS]
            if len(window) == LONG_RAW_WINDOW_CHARS:
                yield window
                normalized_window = normalize_prose(window)
                if normalized_window != window:
                    yield normalized_window

    for paragraph in re.split(r"(?:\r?\n){2,}", text):
        yield from emit(paragraph, False)
    for line in text.splitlines():
        yield from emit(line, True)
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        yield from emit(sentence, False)
    yield from strong_private_values(text)


def raw_fragment_fingerprints(text: str) -> set[bytes]:
    fingerprints: set[bytes] = set()
    total_bytes = 0
    for fragment in raw_text_fragments(text):
        for form in ("NFC", "NFD"):
            normalized = unicodedata.normalize(form, fragment)
            for encoding in ("utf-8", "utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be"):
                encoded = normalized.encode(encoding)
                if encoded in fingerprints:
                    continue
                fingerprints.add(encoded)
                total_bytes += len(encoded)
                if (
                    len(fingerprints) > MAX_RAW_FRAGMENT_PATTERNS
                    or total_bytes > MAX_RAW_FRAGMENT_PATTERN_BYTES
                ):
                    raise GuardError(
                        "Private inputs exceed the safe raw-fragment fingerprint budget"
                    )
    return fingerprints


def compile_raw_fragment_pattern(
    fingerprints: set[bytes],
) -> tuple[re.Pattern[bytes] | None, int]:
    if not fingerprints:
        return None, 0
    ordered = sorted(fingerprints, key=lambda value: (-len(value), value))
    expression = b"(?:" + b"|".join(re.escape(value) for value in ordered) + b")"
    return re.compile(expression), max(len(value) for value in ordered)


def contains_raw_fragment(data: bytes, pattern: re.Pattern[bytes] | None, longest: int) -> bool:
    if pattern is None:
        return False
    overlap = b""
    for offset in range(0, len(data), RAW_SCAN_CHUNK_BYTES):
        window = overlap + data[offset : offset + RAW_SCAN_CHUNK_BYTES]
        if pattern.search(window) is not None:
            return True
        overlap = window[-(longest - 1) :] if longest > 1 else b""
    return False


def private_fingerprints(
    private_paths: list[Path], require_all: bool
) -> tuple[set[str], set[str], set[str], set[bytes]]:
    exact_hashes: set[str] = set()
    normalized_documents: set[str] = set()
    fragments: set[str] = set()
    raw_fragments: set[bytes] = set()
    for path in private_paths:
        if not path.exists():
            if require_all:
                raise GuardError("A supplied private input does not exist")
            continue
        if not path.is_file():
            raise GuardError("A private input is not a regular file")
        if path.stat().st_size > MAX_CONTENT_SCAN_BYTES:
            raise GuardError("A private input exceeds the content scan limit")
        data = path.read_bytes()
        text = decode_private_text(data)
        if text is None:
            raise GuardError("A private input is not supported Unicode text")
        private_text = without_allowlisted_public_lines(text)
        normalized_document = normalize_prose(private_text)
        if normalized_document:
            exact_hashes.add(hashlib.sha256(data).hexdigest())
            normalized_documents.add(normalized_document)
        if len(normalized_document) >= MIN_PRIVATE_DOCUMENT_CHARS:
            fragments.add(normalized_document)
        fragments.update(distinctive_fragments(private_text))
        raw_fragments.update(raw_fragment_fingerprints(private_text))
        if (
            len(raw_fragments) > MAX_RAW_FRAGMENT_PATTERNS
            or sum(len(fragment) for fragment in raw_fragments) > MAX_RAW_FRAGMENT_PATTERN_BYTES
        ):
            raise GuardError("Private inputs exceed the safe raw-fragment fingerprint budget")
    return exact_hashes, normalized_documents, fragments, raw_fragments


def bytes_match_private(
    data: bytes,
    exact_hashes: set[str],
    normalized_documents: set[str],
    fragments: set[str],
    raw_pattern: re.Pattern[bytes] | None,
    longest_raw_fragment: int,
    depth: int = 0,
    transform_budget: TransformBudget | None = None,
) -> bool:
    if transform_budget is None:
        transform_budget = TransformBudget()

    def queue_payload(payload: bytes) -> None:
        transform_budget.decoded_bytes += len(payload)
        if transform_budget.decoded_bytes > MAX_CONTENT_SCAN_BYTES:
            raise GuardError("Reachable transformed blobs exceed the cumulative decoded limit")
        decoded_payloads.append(payload)

    if hashlib.sha256(data).hexdigest() in exact_hashes:
        return True
    if contains_raw_fragment(data, raw_pattern, longest_raw_fragment):
        return True
    text = decode_private_text(data)
    if text is not None:
        normalized = normalize_prose(text)
        if normalized in normalized_documents or any(
            fragment in normalized for fragment in fragments
        ):
            return True

    recognized_transform = False
    decoded_payloads: list[bytes] = []
    try:
        if data.startswith(b"\x1f\x8b"):
            recognized_transform = True
            with gzip.GzipFile(fileobj=io.BytesIO(data), mode="rb") as gzip_handle:
                queue_payload(gzip_handle.read(MAX_CONTENT_SCAN_BYTES + 1))
        elif data.startswith(b"BZh"):
            recognized_transform = True
            bzip2_decompressor = bz2.BZ2Decompressor()
            queue_payload(
                bzip2_decompressor.decompress(data, max_length=MAX_CONTENT_SCAN_BYTES + 1)
            )
            if not bzip2_decompressor.eof:
                raise GuardError("A reachable bzip2 blob exceeds the decoded scan limit")
            if bzip2_decompressor.unused_data:
                raise GuardError("A reachable bzip2 blob has concatenated or trailing data")
        elif data.startswith(b"\xfd7zXZ\x00"):
            recognized_transform = True
            xz_decompressor = lzma.LZMADecompressor()
            queue_payload(xz_decompressor.decompress(data, max_length=MAX_CONTENT_SCAN_BYTES + 1))
            if not xz_decompressor.eof:
                raise GuardError("A reachable xz blob exceeds the decoded scan limit")
            if xz_decompressor.unused_data:
                raise GuardError("A reachable xz blob has concatenated or trailing data")
    except (EOFError, OSError, ValueError, lzma.LZMAError) as error:
        raise GuardError("A reachable compressed blob cannot be decoded safely") from error

    stripped = re.sub(rb"\s+", b"", data)
    if (
        len(stripped) >= 16
        and len(stripped) % 4 == 0
        and re.fullmatch(rb"[A-Za-z0-9+/]*={0,2}", stripped)
    ):
        recognized_transform = True
        try:
            queue_payload(base64.b64decode(stripped, validate=True))
        except binascii.Error as error:
            raise GuardError("A reachable base64 blob cannot be decoded safely") from error
    if len(stripped) >= 32 and len(stripped) % 2 == 0 and re.fullmatch(rb"[0-9A-Fa-f]+", stripped):
        recognized_transform = True
        queue_payload(bytes.fromhex(stripped.decode("ascii")))

    stream = io.BytesIO(data)
    if zipfile.is_zipfile(stream):
        recognized_transform = True
        total_bytes = 0
        if len(data) < 22 or data[-22:-18] != b"PK\x05\x06":
            raise GuardError("A reachable ZIP blob has an unsupported envelope")
        eocd = struct.unpack("<4s4H2LH", data[-22:])
        if (
            eocd[1]
            or eocd[2]
            or eocd[3] != eocd[4]
            or eocd[4] == 0xFFFF
            or eocd[5] == 0xFFFFFFFF
            or eocd[6] == 0xFFFFFFFF
            or eocd[4] > MAX_CONTAINER_ENTRIES
            or eocd[5] > MAX_ZIP_CENTRAL_DIRECTORY_BYTES
            or eocd[6] + eocd[5] != len(data) - 22
        ):
            raise GuardError("A reachable ZIP blob exceeds the bounded container format")
        try:
            with zipfile.ZipFile(stream) as zip_archive:
                infos = zip_archive.infolist()
                if len(infos) > MAX_CONTAINER_ENTRIES:
                    raise GuardError("A reachable ZIP blob exceeds the entry scan limit")
                for info in infos:
                    transform_budget.entries += 1
                    if transform_budget.entries > MAX_CONTAINER_ENTRIES:
                        raise GuardError("Reachable containers exceed the cumulative entry limit")
                    if contains_raw_fragment(
                        info.filename.encode("utf-8", errors="surrogatepass"),
                        raw_pattern,
                        longest_raw_fragment,
                    ):
                        return True
                    if info.is_dir():
                        continue
                    total_bytes += info.file_size
                    if total_bytes > MAX_CONTENT_SCAN_BYTES:
                        raise GuardError("A reachable ZIP blob exceeds the decoded scan limit")
                    if info.flag_bits & 0x1:
                        raise GuardError("An encrypted reachable ZIP member cannot be audited")
                    with zip_archive.open(info) as zip_member_handle:
                        payload = zip_member_handle.read(info.file_size + 1)
                    if len(payload) != info.file_size:
                        raise GuardError("A reachable ZIP member has inconsistent size metadata")
                    queue_payload(payload)
        except (OSError, RuntimeError, zipfile.BadZipFile, zipfile.LargeZipFile) as error:
            if isinstance(error, GuardError):
                raise
            raise GuardError("A reachable ZIP blob cannot be decoded safely") from error
    elif len(data) >= 512 and data[257:262] in {b"ustar", b"ustar\x00"}:
        recognized_transform = True
        total_bytes = 0
        try:
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tar_archive:
                for entry_count, member in enumerate(tar_archive, start=1):
                    if entry_count > MAX_CONTAINER_ENTRIES:
                        raise GuardError("A reachable TAR blob exceeds the entry scan limit")
                    transform_budget.entries += 1
                    if transform_budget.entries > MAX_CONTAINER_ENTRIES:
                        raise GuardError("Reachable containers exceed the cumulative entry limit")
                    if contains_raw_fragment(
                        member.name.encode("utf-8", errors="surrogatepass"),
                        raw_pattern,
                        longest_raw_fragment,
                    ):
                        return True
                    if not member.isfile():
                        continue
                    total_bytes += member.size
                    if total_bytes > MAX_CONTENT_SCAN_BYTES:
                        raise GuardError("A reachable TAR blob exceeds the decoded scan limit")
                    extracted = tar_archive.extractfile(member)
                    if extracted is None:
                        raise GuardError("A reachable TAR member cannot be inspected")
                    payload = extracted.read(member.size + 1)
                    if len(payload) != member.size:
                        raise GuardError("A reachable TAR member has inconsistent size metadata")
                    queue_payload(payload)
        except (OSError, tarfile.TarError) as error:
            raise GuardError("A reachable TAR blob cannot be decoded safely") from error

    for payload in decoded_payloads:
        if len(payload) > MAX_CONTENT_SCAN_BYTES:
            raise GuardError("A reachable transformed blob exceeds the decoded scan limit")
        if depth >= MAX_TRANSFORM_DEPTH:
            raise GuardError("A reachable blob exceeds the nested transform scan depth")
        if bytes_match_private(
            payload,
            exact_hashes,
            normalized_documents,
            fragments,
            raw_pattern,
            longest_raw_fragment,
            depth + 1,
            transform_budget,
        ):
            return True
    if recognized_transform and depth >= MAX_TRANSFORM_DEPTH:
        raise GuardError("A reachable blob exceeds the nested transform scan depth")
    return False


def reachable_objects_by_type(git_program: TrustedGit, repo: Path) -> dict[str, set[str]]:
    listing = run_git(
        git_program,
        repo,
        "rev-list",
        "--objects",
        "--all",
        "--no-object-names",
        check=False,
    )
    if listing.returncode != 0:
        raise GuardError(listing.stderr.strip() or "Could not enumerate reachable Git objects")
    object_ids = sorted({value for value in listing.stdout.splitlines() if value})
    if any(re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value) is None for value in object_ids):
        raise GuardError("Git returned an invalid reachable object identifier")
    if not object_ids:
        return {}
    batch = subprocess.run(
        git_command(
            git_program,
            "-C",
            str(repo),
            "cat-file",
            "--batch-check=%(objectname) %(objecttype)",
        ),
        input="\n".join(object_ids) + "\n",
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=git_environment(),
    )
    git_command(git_program)
    if batch.returncode != 0:
        raise GuardError(batch.stderr.strip() or "Could not classify reachable Git objects")
    lines = batch.stdout.splitlines()
    if len(lines) != len(object_ids):
        raise GuardError("Git returned an incomplete reachable object classification")
    by_type: dict[str, set[str]] = {}
    for expected_id, line in zip(object_ids, lines, strict=True):
        fields = line.split()
        if (
            len(fields) != 2
            or fields[0] != expected_id
            or fields[1] not in {"blob", "commit", "tag", "tree"}
        ):
            raise GuardError("Git returned an invalid or missing object classification")
        by_type.setdefault(fields[1], set()).add(fields[0])
    return by_type


def blob_ids_with_labels(git_program: TrustedGit, repo: Path) -> dict[str, set[str]]:
    blobs: dict[str, set[str]] = {}
    index = run_git(git_program, repo, "ls-files", "-s", "-z")
    for item in split_nul(index.stdout):
        metadata, separator, path = item.partition("\t")
        fields = metadata.split()
        if separator and len(fields) >= 2:
            blobs.setdefault(fields[1], set()).add(path)

    trees = run_git(git_program, repo, "log", "--all", "--format=%T", check=False)
    if trees.returncode != 0:
        raise GuardError(trees.stderr.strip() or "Could not enumerate reachable commit trees")
    for tree in sorted(set(trees.stdout.splitlines())):
        if not tree:
            continue
        listing = run_git(git_program, repo, "ls-tree", "-r", "-z", tree)
        for item in split_nul(listing.stdout):
            metadata, separator, path = item.partition("\t")
            fields = metadata.split()
            if separator and len(fields) >= 3 and fields[1] == "blob":
                blobs.setdefault(fields[2], set()).add(path)
    for object_id in reachable_objects_by_type(git_program, repo).get("blob", set()):
        blobs.setdefault(object_id, set()).add(f"<reachable blob {object_id[:12]}>")
    return blobs


def read_git_object(
    git_program: TrustedGit, repo: Path, object_id: str, expected_type: str
) -> bytes:
    size_result = run_git(git_program, repo, "cat-file", "-s", object_id)
    try:
        size = int(size_result.stdout.strip())
    except ValueError as error:
        raise GuardError(f"Invalid Git {expected_type} object size") from error
    if size > MAX_CONTENT_SCAN_BYTES:
        raise GuardError(
            f"Cannot prove private-input separation because a Git {expected_type} object "
            "exceeds the content scan limit"
        )
    result = subprocess.run(
        git_command(
            git_program,
            "-C",
            str(repo),
            "cat-file",
            expected_type,
            object_id,
        ),
        check=False,
        capture_output=True,
        env=git_environment(),
    )
    git_command(git_program)
    if result.returncode != 0:
        raise GuardError(f"Could not read a reachable Git {expected_type} object")
    return result.stdout


def private_content_violations(
    git_program: TrustedGit,
    repo: Path,
    private_paths: list[Path],
    require_all: bool,
) -> list[str]:
    global LOG_RAW_PATTERN
    exact_hashes, normalized_documents, fragments, raw_fragments = private_fingerprints(
        private_paths, require_all
    )
    if not exact_hashes and not normalized_documents and not fragments and not raw_fragments:
        return []
    raw_pattern, longest_raw_fragment = compile_raw_fragment_pattern(raw_fragments)
    LOG_RAW_PATTERN = raw_pattern
    violations: set[str] = set()
    reachable_objects = reachable_objects_by_type(git_program, repo)
    for object_id, labels in blob_ids_with_labels(git_program, repo).items():
        if bytes_match_private(
            read_git_object(git_program, repo, object_id, "blob"),
            exact_hashes,
            normalized_documents,
            fragments,
            raw_pattern,
            longest_raw_fragment,
        ):
            violations.update(labels)

    messages = run_git(git_program, repo, "log", "--all", "--format=%B%x00", check=False)
    if messages.returncode != 0:
        raise GuardError(messages.stderr.strip() or "Could not inspect commit messages")
    if any(
        bytes_match_private(
            message.encode("utf-8"),
            exact_hashes,
            normalized_documents,
            fragments,
            raw_pattern,
            longest_raw_fragment,
        )
        for message in split_nul(messages.stdout)
    ):
        violations.add("<commit message>")

    for object_id in reachable_objects.get("tag", set()):
        if bytes_match_private(
            read_git_object(git_program, repo, object_id, "tag"),
            exact_hashes,
            normalized_documents,
            fragments,
            raw_pattern,
            longest_raw_fragment,
        ):
            violations.add("<annotated tag object>")
    return sorted(violations, key=str.casefold)


def protected_path(path: str, forbidden_names: set[str], forbidden_paths: set[str]) -> bool:
    normalized = path.replace("\\", "/")
    return (
        normalized.casefold() in forbidden_paths
        or Path(normalized).name.casefold() in forbidden_names
    )


def current_violations(
    git_program: TrustedGit,
    repo: Path,
    forbidden_names: set[str],
    forbidden_paths: set[str],
) -> list[str]:
    tracked = split_nul(run_git(git_program, repo, "ls-files", "-z").stdout)
    staged = split_nul(
        run_git(
            git_program,
            repo,
            "diff",
            "--cached",
            "--name-only",
            "--diff-filter=ACMR",
            "-z",
        ).stdout
    )
    return sorted(
        {
            path
            for path in [*tracked, *staged]
            if protected_path(path, forbidden_names, forbidden_paths)
        },
        key=str.casefold,
    )


def history_violations(
    git_program: TrustedGit,
    repo: Path,
    forbidden_names: set[str],
    forbidden_paths: set[str],
) -> list[str]:
    violations: set[str] = set()
    shallow = run_git(git_program, repo, "rev-parse", "--is-shallow-repository").stdout.strip()
    if shallow == "true":
        raise GuardError("Cannot prove private-file history in a shallow repository")

    trees = run_git(git_program, repo, "log", "--all", "--format=%T", check=False)
    if trees.returncode != 0:
        raise GuardError(trees.stderr.strip() or "Could not enumerate reachable commit trees")
    reachable_trees = reachable_objects_by_type(git_program, repo).get("tree", set())
    for tree in sorted(set(trees.stdout.splitlines()).union(reachable_trees)):
        if not tree:
            continue
        listing = run_git(git_program, repo, "ls-tree", "-r", "-z", "--name-only", tree)
        for path in split_nul(listing.stdout):
            if protected_path(path, forbidden_names, forbidden_paths):
                violations.add(path)
    return sorted(violations, key=str.casefold)


def git_exclude_path(git_program: TrustedGit, repo: Path) -> Path:
    common_result = run_git(git_program, repo, "rev-parse", "--git-common-dir")
    common_dir = Path(common_result.stdout.strip())
    if not common_dir.is_absolute():
        common_dir = repo / common_dir
    try:
        common_dir = common_dir.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise GuardError("Could not resolve the Git common directory") from error

    result = run_git(git_program, repo, "rev-parse", "--git-path", "info/exclude")
    reported_path = Path(result.stdout.strip())
    if not reported_path.is_absolute():
        reported_path = repo / reported_path
    reported_path = Path(os.path.abspath(reported_path))
    expected_path = common_dir / "info" / "exclude"
    if os.path.normcase(str(reported_path)) != os.path.normcase(str(expected_path)):
        raise GuardError(
            "Git exclude path is not the exact canonical common-directory info/exclude path"
        )

    components = (
        (common_dir, "directory", False),
        (common_dir / "info", "directory", False),
        (expected_path, "file", True),
    )
    for component, expected_kind, may_be_missing in components:
        try:
            metadata = component.lstat()
        except FileNotFoundError:
            if may_be_missing:
                continue
            raise GuardError("Git common-directory metadata path is unexpectedly missing") from None
        except OSError as error:
            raise GuardError("Could not inspect the Git exclude path safely") from error
        if stat.S_ISLNK(metadata.st_mode) or is_reparse_point(metadata):
            raise GuardError("Refusing a symlink or reparse point in the Git info/exclude path")
        if expected_kind == "directory" and not stat.S_ISDIR(metadata.st_mode):
            raise GuardError("A Git info/exclude parent is not a directory")
        if expected_kind == "file" and not stat.S_ISREG(metadata.st_mode):
            raise GuardError("Git exclude path is not a regular file")

    return expected_path


def file_identity(path: Path) -> tuple[int, int, int, int] | None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise GuardError(f"Could not inspect Git exclude path: {error}") from error
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
    )


def exclusion_patterns(repo: Path, private_paths: list[Path]) -> list[str]:
    patterns: list[str] = []
    for path in private_paths:
        try:
            relative = path.relative_to(repo).as_posix()
        except ValueError:
            continue
        patterns.append(f"/{relative}")
    for name in DEFAULT_NAMES:
        root_pattern = f"/{name}"
        if root_pattern not in patterns:
            patterns.append(root_pattern)
    return patterns


def write_exclusions(git_program: TrustedGit, repo: Path, private_paths: list[Path]) -> None:
    exclude_path = git_exclude_path(git_program, repo)
    initial_identity = file_identity(exclude_path)
    original_mode: int | None = None
    if initial_identity is not None:
        original_mode = stat.S_IMODE(exclude_path.lstat().st_mode)
    original = exclude_path.read_text(encoding="utf-8") if initial_identity is not None else ""
    existing = {line.strip() for line in original.splitlines()}
    additions = [
        pattern for pattern in exclusion_patterns(repo, private_paths) if pattern not in existing
    ]
    if not additions:
        return

    prefix = original
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    if MARKER not in existing:
        prefix += f"{MARKER}\n"
    updated = prefix + "".join(f"{pattern}\n" for pattern in additions)

    fd, temporary_name = tempfile.mkstemp(prefix="exclude-", dir=str(exclude_path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(updated)
        if original_mode is not None:
            os.chmod(temporary_name, original_mode)
        if git_exclude_path(git_program, repo) != exclude_path:
            raise GuardError("Git exclude path changed while it was being updated")
        if file_identity(exclude_path) != initial_identity:
            raise GuardError("Git exclude file changed while it was being updated")
        os.replace(temporary_name, exclude_path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def verify_ignored(git_program: TrustedGit, repo: Path, private_paths: list[Path]) -> list[str]:
    failures: list[str] = []
    for path in private_paths:
        try:
            relative = path.relative_to(repo).as_posix()
        except ValueError:
            continue
        result = run_git(
            git_program,
            repo,
            "check-ignore",
            "--no-index",
            "--quiet",
            "--",
            relative,
            check=False,
        )
        if result.returncode == 1:
            failures.append(relative)
        elif result.returncode != 0:
            raise GuardError("Git could not verify a private-input ignore rule")
    return failures


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Keep idea.md, plan.md, and specified private planning files out of Git."
    )
    parser.add_argument("mode", choices=("protect", "check"))
    parser.add_argument("repo", type=Path, help="Path inside the Git worktree")
    parser.add_argument(
        "--git-program",
        required=True,
        type=Path,
        metavar="PATH",
        help="Trusted absolute Git executable located outside every audited worktree",
    )
    parser.add_argument(
        "--git-program-sha256",
        required=True,
        metavar="HEX",
        help="Approved SHA-256 digest of --git-program",
    )
    parser.add_argument(
        "private_paths",
        nargs="*",
        help="Ordinary private paths including exactly one live plan.md; omit the approved snapshot",
    )
    parser.add_argument(
        "--approved-plan-snapshot",
        type=Path,
        help="Separate, byte-identical private snapshot of the approved live plan",
    )
    parser.add_argument(
        "--private-input-set-sha256",
        metavar="HEX",
        help="Plan-recorded digest binding every canonical private path and current byte hash",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        git_program = resolve_git_program(args.git_program, args.git_program_sha256)
        repo_candidate = args.repo.resolve()
        preflight_git_location(git_program, repo_candidate)
        preflight_local_git_config(repo_candidate)
        if args.mode == "check" and (
            args.approved_plan_snapshot is None
            or args.private_input_set_sha256 is None
            or re.fullmatch(r"[0-9a-fA-F]{64}", args.private_input_set_sha256) is None
        ):
            raise GuardError(
                "check mode requires --approved-plan-snapshot and --private-input-set-sha256"
            )
        supplied_private_paths = list(args.private_paths)
        if args.approved_plan_snapshot is not None:
            supplied_private_paths.append(str(args.approved_plan_snapshot))
        for raw_private_path in supplied_private_paths:
            candidate = Path(raw_private_path)
            if not candidate.is_absolute():
                candidate = repo_candidate / candidate
            preflight_git_location(git_program, candidate.parent)

        repo = repository_root(git_program, repo_candidate)
        version = git_version(git_program)
        print(f"Trusted Git: {terminal_safe(git_identity_record(git_program, version))}")
        ordinary_private_paths, _, _ = normalize_private_paths(repo, list(args.private_paths))
        current_plans = [
            path for path in ordinary_private_paths if path.name.casefold() == "plan.md"
        ]
        if args.approved_plan_snapshot is not None and len(current_plans) != 1:
            raise GuardError(
                "an approved plan snapshot requires exactly one live plan.md private input"
            )
        approved_plan_snapshot: Path | None = None
        if args.approved_plan_snapshot is not None:
            approved_plan_snapshot = args.approved_plan_snapshot
            if not approved_plan_snapshot.is_absolute():
                approved_plan_snapshot = repo / approved_plan_snapshot
            approved_plan_snapshot = Path(os.path.abspath(approved_plan_snapshot))
            if any(
                private_path_key(approved_plan_snapshot) == private_path_key(path)
                for path in ordinary_private_paths
            ):
                raise GuardError(
                    "The approved plan snapshot must be separate from every ordinary private input"
                )
        combined_private_values = [str(path) for path in ordinary_private_paths]
        if approved_plan_snapshot is not None:
            combined_private_values.append(str(approved_plan_snapshot))
        private_paths, forbidden_names, _forbidden_paths = normalize_private_paths(
            repo, combined_private_values
        )
        approved_set_digest: str | None = None
        if (
            args.mode == "check"
            or args.private_input_set_sha256 is not None
            or approved_plan_snapshot is not None
        ):
            approved_set_digest = private_input_set_digest(private_paths)
            if (
                args.private_input_set_sha256 is not None
                and approved_set_digest != args.private_input_set_sha256.casefold()
            ):
                raise GuardError("The private-input set does not match its approved digest")
        if approved_plan_snapshot is not None:
            if (
                hashlib.sha256(current_plans[0].read_bytes()).digest()
                != hashlib.sha256(approved_plan_snapshot.read_bytes()).digest()
            ):
                raise GuardError("The live plan does not match the approved plan snapshot")

        repositories = {repo}
        outside_git = 0
        for private_path in private_paths:
            containing = containing_repository(git_program, private_path.parent)
            if containing is None:
                outside_git += 1
            else:
                repositories.add(containing)

        all_current: list[tuple[Path, str]] = []
        all_history: list[tuple[Path, str]] = []
        all_content: list[tuple[Path, str]] = []
        all_not_ignored: list[tuple[Path, str]] = []
        for guarded_repo in sorted(repositories, key=lambda item: str(item).casefold()):
            require_git_outside_worktree(git_program, guarded_repo)
            reject_grafts(git_program, guarded_repo)
            reject_partial_clone(git_program, guarded_repo)
            _, _, guarded_relative_paths = normalize_private_paths(
                guarded_repo, [str(path) for path in private_paths]
            )
            current = current_violations(
                git_program, guarded_repo, forbidden_names, guarded_relative_paths
            )
            history = history_violations(
                git_program, guarded_repo, forbidden_names, guarded_relative_paths
            )
            content = private_content_violations(
                git_program,
                guarded_repo,
                private_paths,
                require_all=args.mode == "check",
            )
            all_current.extend((guarded_repo, path) for path in current)
            all_history.extend((guarded_repo, path) for path in history)
            all_content.extend((guarded_repo, path) for path in content)

            if args.mode == "protect":
                write_exclusions(git_program, guarded_repo, private_paths)
            not_ignored = verify_ignored(git_program, guarded_repo, private_paths)
            all_not_ignored.extend((guarded_repo, path) for path in not_ignored)

        if all_current or all_history or all_content:
            if all_current:
                print(
                    f"ERROR: {len(all_current)} private planning file(s) are tracked or staged",
                    file=sys.stderr,
                )
            if all_history:
                print(
                    f"ERROR: {len(all_history)} private planning filename(s) exist in reachable history",
                    file=sys.stderr,
                )
            if all_content:
                print(
                    f"ERROR: private planning content appears in {len(all_content)} reachable "
                    "location(s) under another name or in Git metadata",
                    file=sys.stderr,
                )
            print(
                "Stop. Do not commit, push, package, or rewrite history without an approved incident plan.",
                file=sys.stderr,
            )
            return 1

        if (
            approved_set_digest is not None
            and private_input_set_digest(private_paths) != approved_set_digest
        ):
            raise GuardError("The private-input set changed during the guard run")

        if all_not_ignored:
            print(
                f"ERROR: {len(all_not_ignored)} private planning path(s) are not locally excluded",
                file=sys.stderr,
            )
            print("Run this script in protect mode before continuing.", file=sys.stderr)
            return 1

        print(
            f"Private planning guard passed for {len(repositories)} Git worktree(s); "
            f"{outside_git} supplied path(s) are outside Git"
        )
        if approved_set_digest is not None:
            print(f"Private input set SHA-256: {approved_set_digest}")
        return 0
    except (GuardError, OSError) as error:
        print(f"ERROR: {terminal_safe(str(error))}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
