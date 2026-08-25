from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.support import (
    GIT_PROGRAM,
    GIT_PROGRAM_SHA256,
    TEXT_SCRIPT,
    combined_output,
    commit_all,
    create_basic_repo,
    git,
    run_script,
    write_bytes,
    write_text,
)


class AuditAuthoredTextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="build-oss-text-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def assert_failed_with(self, result: subprocess.CompletedProcess[str], phrase: str) -> None:
        self.assertEqual(result.returncode, 1, combined_output(result))
        self.assertIn(phrase, combined_output(result))

    def run_text(self, repo: Path, *arguments: str | Path) -> subprocess.CompletedProcess[str]:
        return run_script(
            TEXT_SCRIPT,
            "--git-program",
            GIT_PROGRAM,
            "--git-program-sha256",
            GIT_PROGRAM_SHA256,
            repo,
            *arguments,
        )

    def test_clean_project_passes(self) -> None:
        repo = create_basic_repo(self.root / "repo")

        result = self.run_text(repo, "--expected-brand", "Safe project")

        self.assertEqual(result.returncode, 0, combined_output(result))

    def test_scans_staged_snapshot_when_worktree_has_been_replaced(self) -> None:
        repo = create_basic_repo(self.root / "repo")
        write_text(repo, "config.txt", "safe=true\n")
        commit_all(repo, "test: add config")
        secret = "ghp_" + "12345678901234567890"
        write_text(repo, "config.txt", f"token={secret}\n")
        git(repo, "add", "config.txt")
        write_text(repo, "config.txt", "safe=true\n")

        result = self.run_text(repo)

        self.assert_failed_with(result, "possible GitHub token")
        self.assertIn("[index]", result.stdout)
        self.assertNotIn(secret, combined_output(result))

    def test_scans_worktree_snapshot_when_index_is_safe(self) -> None:
        repo = create_basic_repo(self.root / "repo")
        write_text(repo, "notes.md", "safe text\n")
        commit_all(repo, "test: add notes")
        write_text(repo, "notes.md", "unsafe em dash \u2014 here\n")

        result = self.run_text(repo)

        self.assert_failed_with(result, "Unicode em dash")
        self.assertIn("[worktree]", result.stdout)

    def test_detects_em_dash_in_bom_marked_utf16_index_blob(self) -> None:
        repo = create_basic_repo(self.root / "repo")
        write_bytes(
            repo,
            "utf16.md",
            "line one\nline two \u2014 unsafe\n".encode("utf-16"),
        )
        git(repo, "add", "utf16.md")

        result = self.run_text(repo)

        self.assert_failed_with(result, "Unicode em dash")
        self.assertIn("utf16.md:2 [index]", result.stdout)

    def test_does_not_follow_untracked_worktree_symlink(self) -> None:
        repo = create_basic_repo(self.root / "repo")
        target = self.root / "outside-secret.md"
        secret = "ghp_" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ123456"
        target.write_text(secret, encoding="utf-8")
        link = repo / "linked.md"
        try:
            os.symlink(target, link)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"symbolic links are unavailable: {error}")

        result = self.run_text(repo)

        self.assert_failed_with(result, "worktree symlink was not followed")
        self.assertNotIn(secret, combined_output(result))

    def test_missing_expected_brand_is_a_failure(self) -> None:
        repo = create_basic_repo(self.root / "repo")

        result = self.run_text(repo, "--expected-brand", "Different Brand")

        self.assert_failed_with(result, "expected brand is missing")

    def test_invocation_from_subdirectory_audits_repository_root(self) -> None:
        repo = create_basic_repo(self.root / "repo")
        subdirectory = repo / "nested" / "working-directory"
        subdirectory.mkdir(parents=True)

        result = self.run_text(
            subdirectory,
            "--expected-brand",
            "Safe project",
        )

        self.assertEqual(result.returncode, 0, combined_output(result))
        self.assertIn("Git verifier:", result.stdout)

    def test_brand_must_exist_in_index_even_when_worktree_has_it(self) -> None:
        repo = create_basic_repo(self.root / "repo")
        write_text(repo, "README.md", "# New Brand\n")

        result = self.run_text(repo, "--expected-brand", "New Brand")

        self.assert_failed_with(result, "expected brand is missing")
        brand_findings = [
            line for line in result.stdout.splitlines() if "expected brand is missing" in line
        ]
        self.assertTrue(any("[index]" in line for line in brand_findings))
        self.assertFalse(any("[worktree]" in line for line in brand_findings))

    def test_brand_must_exist_in_worktree_even_when_index_has_it(self) -> None:
        repo = create_basic_repo(self.root / "repo")
        write_text(repo, "README.md", "# New Brand\n")
        git(repo, "add", "README.md")
        write_text(repo, "README.md", "# Safe project\n")

        result = self.run_text(repo, "--expected-brand", "New Brand")

        self.assert_failed_with(result, "expected brand is missing")
        brand_findings = [
            line for line in result.stdout.splitlines() if "expected brand is missing" in line
        ]
        self.assertTrue(any("[worktree]" in line for line in brand_findings))
        self.assertFalse(any("[index]" in line for line in brand_findings))


if __name__ == "__main__":
    unittest.main()
