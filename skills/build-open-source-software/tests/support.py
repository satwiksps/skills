"""Shared, dependency-free test helpers for the skill scripts."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
GUARD_SCRIPT = SCRIPTS / "guard_private_inputs.py"
TEXT_SCRIPT = SCRIPTS / "audit_authored_text.py"
RELEASE_SCRIPT = SCRIPTS / "audit_release_state.py"

VERSION = "0.1.0"
COPYRIGHT_YEAR = "2026"
COPYRIGHT_HOLDER = "Example Project contributors"
DEFAULT_MAX_ARTIFACT_BYTES = 100_000_000

GIT_PROGRAM_TEXT = shutil.which("git")
if GIT_PROGRAM_TEXT is None:
    raise RuntimeError("The skill-script tests require Git")
GIT_PROGRAM = Path(GIT_PROGRAM_TEXT).resolve()
GIT_PROGRAM_SHA256 = hashlib.sha256(GIT_PROGRAM.read_bytes()).hexdigest()


def isolated_env() -> dict[str, str]:
    """Return an environment insulated from user-level Git configuration."""
    environment = os.environ.copy()
    for key in tuple(environment):
        if key in {
            "GIT_ALTERNATE_OBJECT_DIRECTORIES",
            "GIT_COMMON_DIR",
            "GIT_DIR",
            "GIT_INDEX_FILE",
            "GIT_OBJECT_DIRECTORY",
            "GIT_REPLACE_REF_BASE",
            "GIT_WORK_TREE",
        } or key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")):
            environment.pop(key, None)
    environment.pop("GIT_CONFIG_COUNT", None)
    environment["GIT_CONFIG_NOSYSTEM"] = "1"
    environment["GIT_CONFIG_GLOBAL"] = os.devnull
    environment["GIT_TERMINAL_PROMPT"] = "0"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def run(
    command: list[str],
    *,
    cwd: Path | None = None,
    input_text: str | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        input=input_text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=isolated_env(),
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"Command failed ({result.returncode}): {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def git(
    repo: Path,
    *arguments: str,
    input_text: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return run(
        ["git", "-C", str(repo), *arguments],
        input_text=input_text,
        check=check,
    )


def init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    initialized = run(
        ["git", "init", "--initial-branch=main", str(path)],
        check=False,
    )
    if initialized.returncode != 0:
        run(["git", "init", str(path)], check=True)
        git(path, "branch", "-M", "main")
    git(path, "config", "user.name", "Skill Test")
    git(path, "config", "user.email", "skill-test@example.com")
    git(path, "config", "commit.gpgsign", "false")
    git(path, "config", "tag.gpgsign", "false")
    git(path, "config", "core.autocrlf", "false")
    return path


def write_text(repo: Path, relative: str, text: str) -> Path:
    target = repo / Path(relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(text.encode("utf-8"))
    return target


def write_bytes(repo: Path, relative: str, data: bytes) -> Path:
    target = repo / Path(relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def commit_all(repo: Path, message: str = "test: snapshot") -> str:
    git(repo, "add", "--all")
    git(repo, "commit", "--no-gpg-sign", "-m", message)
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def run_script(script: Path, *arguments: str | Path) -> subprocess.CompletedProcess[str]:
    return run([sys.executable, str(script), *(str(value) for value in arguments)])


def combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return f"{result.stdout}\n{result.stderr}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def private_input_set_digest(paths: list[Path]) -> str:
    records: list[bytes] = []
    for path in sorted(set(paths), key=lambda value: os.path.normcase(str(value))):
        resolved = path.resolve(strict=True)
        canonical_path = os.path.normcase(str(resolved)).encode("utf-8", errors="surrogatepass")
        content_digest = hashlib.sha256(resolved.read_bytes()).hexdigest().encode("ascii")
        records.append(canonical_path + b"\0" + content_digest)
    digest = hashlib.sha256()
    for record in records:
        digest.update(len(record).to_bytes(8, "big"))
        digest.update(record)
    return digest.hexdigest()


def create_basic_repo(path: Path) -> Path:
    repo = init_repo(path)
    write_text(repo, "README.md", "# Safe project\n")
    commit_all(repo, "test: initialize")
    return repo


def create_release_repo(path: Path, *, include_manifest: bool = True) -> Path:
    repo = init_repo(path)
    private_directory = path.parent / f"{path.name}-private-inputs"
    private_directory.mkdir(parents=True, exist_ok=True)
    (private_directory / "idea.md").write_text(
        "A private test idea that must not enter Git or release artifacts.\n",
        encoding="utf-8",
    )
    plan_text = "A private test plan that must remain outside public project state.\n"
    (private_directory / "plan.md").write_text(plan_text, encoding="utf-8")
    (private_directory / "approved-plan-snapshot.md").write_text(
        plan_text,
        encoding="utf-8",
    )
    license_text = (FIXTURES / "APACHE-2.0.txt").read_text(encoding="utf-8")
    files = {
        "README.md": (
            '<div align="center">\n'
            '  <img src="assets/banner.svg" alt="Example Project banner">\n'
            "</div>\n\n"
            "# Example Project\n"
        ),
        "LICENSE": license_text,
        "NOTICE": (f"Example Project\nCopyright {COPYRIGHT_YEAR} {COPYRIGHT_HOLDER}\n"),
        "CHANGELOG.md": f"# Changelog\n\n## {VERSION}\n\nInitial release.\n",
        "CONTRIBUTING.md": "# Contributing\n\nRun the tests before proposing a change.\n",
        "CODE_OF_CONDUCT.md": "# Code of Conduct\n\nBe respectful.\n",
        "SECURITY.md": "# Security\n\nReport vulnerabilities privately.\n",
        "assets/banner.svg": (
            '<svg xmlns="http://www.w3.org/2000/svg" width="1440" height="360">'
            "<title>Example Project</title></svg>\n"
        ),
    }
    if include_manifest:
        files["package.json"] = '{"name":"example-project","version":"0.1.0","private":false}\n'
    for relative, content in files.items():
        write_text(repo, relative, content)
    commit_all(repo, "chore: prepare release")
    return repo


def tag_release(repo: Path) -> None:
    git(repo, "tag", "--annotate", f"v{VERSION}", "--message", f"Release {VERSION}")


def private_inputs(repo: Path) -> tuple[Path, Path]:
    directory = repo.parent / f"{repo.name}-private-inputs"
    return directory / "idea.md", directory / "plan.md"


def approved_plan_snapshot(repo: Path) -> Path:
    directory = repo.parent / f"{repo.name}-private-inputs"
    return directory / "approved-plan-snapshot.md"


def release_staging_directory(repo: Path) -> Path:
    return (repo.parent / f"{repo.name}-release-staging").resolve()


def archive_container_format(path: Path) -> str:
    name = path.name.casefold()
    if name.endswith((".crate", ".tar", ".tar.bz2", ".tar.gz", ".tar.xz", ".tgz")):
        return "tar"
    return "zip"


def release_arguments(
    repo: Path,
    *,
    artifact: Path | None = None,
    tag: bool = False,
    tag_only: bool = False,
    holder: str = COPYRIGHT_HOLDER,
    year: str = COPYRIGHT_YEAR,
    archive_contract: bool = True,
    adapter_inspected: bool | str = False,
    metadata_member: str = "example-project/package.json",
    staging_directory: Path | None = None,
    max_artifact_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES,
) -> list[str | Path]:
    approved_inputs = list(private_inputs(repo))
    approved_plan = approved_plan_snapshot(repo)
    arguments: list[str | Path] = [
        repo,
        "--git-program",
        GIT_PROGRAM,
        "--git-program-sha256",
        GIT_PROGRAM_SHA256,
        "--version",
        VERSION,
        "--default-branch",
        "main",
        "--copyright-year",
        year,
        "--copyright-holder",
        holder,
        "--approved-plan-snapshot",
        approved_plan,
        "--private-input-set-sha256",
        private_input_set_digest([*approved_inputs, approved_plan]),
    ]
    for private_input in approved_inputs:
        arguments.extend(("--private-input", private_input))
    if artifact is not None:
        staging = staging_directory or release_staging_directory(repo)
        arguments.extend(
            (
                "--artifact",
                artifact,
                "--staging-directory",
                staging,
                "--max-artifact-bytes",
                str(max_artifact_bytes),
            )
        )
        if archive_contract:
            arguments.extend(
                (
                    "--archive-format",
                    f"{artifact.name}={archive_container_format(artifact)}",
                    "--require-member",
                    f"{artifact.name}=example-project/*",
                    "--allow-member",
                    f"{artifact.name}=example-project/*",
                    "--license-member",
                    f"{artifact.name}=example-project/LICENSE",
                    "--notice-member",
                    f"{artifact.name}=example-project/NOTICE",
                    "--metadata-member",
                    f"{artifact.name}={metadata_member}",
                )
            )
        if adapter_inspected:
            adapter_digest = (
                sha256_file(artifact) if adapter_inspected is True else str(adapter_inspected)
            )
            arguments.extend(("--adapter-inspected", f"{artifact.name}={adapter_digest}"))
    if tag:
        arguments.extend(("--tag", f"v{VERSION}"))
    if tag_only:
        arguments.append("--tag-only-distribution")
    return arguments
