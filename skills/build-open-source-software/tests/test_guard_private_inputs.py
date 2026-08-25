from __future__ import annotations

import base64
import bz2
import gzip
import hashlib
import json
import lzma
import os
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import unittest
from pathlib import Path

from tests.support import (
    GUARD_SCRIPT,
    combined_output,
    commit_all,
    create_basic_repo,
    git,
    init_repo,
    private_input_set_digest,
    run_script,
    write_text,
)

GIT_PROGRAM_TEXT = shutil.which("git")
if GIT_PROGRAM_TEXT is None:
    raise RuntimeError("The guard tests require Git")
GIT_PROGRAM = Path(GIT_PROGRAM_TEXT).resolve()
GIT_PROGRAM_SHA256 = hashlib.sha256(GIT_PROGRAM.read_bytes()).hexdigest()


class GuardPrivateInputsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="build-oss-guard-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def private_input(self, name: str = "plan.md", content: str = "private source\n") -> Path:
        path = self.root / "private-inputs" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def assert_failed_with(self, result: subprocess.CompletedProcess[str], phrase: str) -> None:
        self.assertNotEqual(result.returncode, 0, combined_output(result))
        self.assertIn(phrase, combined_output(result))

    def run_guard(
        self, mode: str, repo: Path, *private_paths: Path
    ) -> subprocess.CompletedProcess[str]:
        supplied = list(private_paths)
        supplied_names = {path.name.casefold() for path in supplied}
        for required_name in ("idea.md", "plan.md"):
            if required_name not in supplied_names:
                supplied.append(
                    self.private_input(
                        required_name,
                        f"Private supplemental {required_name} content.\n",
                    )
                )
        ordinary_plan = next(path for path in supplied if path.name.casefold() == "plan.md")
        approved_plan = self.root / "approved-plans" / f"{repo.name}-snapshot.md"
        approved_plan.parent.mkdir(parents=True, exist_ok=True)
        approved_plan.write_bytes(ordinary_plan.read_bytes())
        return run_script(
            GUARD_SCRIPT,
            "--git-program",
            GIT_PROGRAM,
            "--git-program-sha256",
            GIT_PROGRAM_SHA256,
            "--approved-plan-snapshot",
            approved_plan,
            "--private-input-set-sha256",
            private_input_set_digest([*supplied, approved_plan]),
            mode,
            repo,
            *supplied,
        )

    def run_bound_guard(
        self,
        repo: Path,
        ordinary_inputs: list[Path],
        approved_plan: Path,
        digest: str,
    ) -> subprocess.CompletedProcess[str]:
        return run_script(
            GUARD_SCRIPT,
            "--git-program",
            GIT_PROGRAM,
            "--git-program-sha256",
            GIT_PROGRAM_SHA256,
            "--approved-plan-snapshot",
            approved_plan,
            "--private-input-set-sha256",
            digest,
            "check",
            repo,
            *ordinary_inputs,
        )

    def test_protect_then_check_passes_for_untracked_planning_files(self) -> None:
        repo = create_basic_repo(self.root / "repo")
        write_text(repo, "idea.md", "private concept\n")
        write_text(repo, "plan.md", "private plan\n")

        protected = self.run_guard("protect", repo)
        checked = self.run_guard("check", repo)

        self.assertEqual(protected.returncode, 0, combined_output(protected))
        self.assertEqual(checked.returncode, 0, combined_output(checked))
        record_line = next(
            line.removeprefix("Trusted Git: ")
            for line in checked.stdout.splitlines()
            if line.startswith("Trusted Git: ")
        )
        record = json.loads(json.loads(f'"{record_line}"'))
        self.assertEqual(record["git_program"], str(GIT_PROGRAM))
        self.assertEqual(record["git_program_sha256"], GIT_PROGRAM_SHA256)
        self.assertTrue(record["git_version"].startswith("git version "))
        exclude = (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")
        self.assertIn("/idea.md", exclude)
        self.assertIn("/plan.md", exclude)

    def test_protect_with_snapshot_prints_digest_without_expected_digest(self) -> None:
        repo = create_basic_repo(self.root / "repo")
        idea = self.private_input("idea.md", "A private source idea.\n")
        plan = self.private_input("plan.md", "A private approved plan.\n")
        approved = self.root / "approved-plans" / "protect-snapshot.md"
        approved.parent.mkdir(parents=True, exist_ok=True)
        approved.write_bytes(plan.read_bytes())
        expected_digest = private_input_set_digest([idea, plan, approved])

        result = run_script(
            GUARD_SCRIPT,
            "--git-program",
            GIT_PROGRAM,
            "--git-program-sha256",
            GIT_PROGRAM_SHA256,
            "--approved-plan-snapshot",
            approved,
            "protect",
            repo,
            idea,
            plan,
        )

        self.assertEqual(result.returncode, 0, combined_output(result))
        self.assertIn(f"Private input set SHA-256: {expected_digest}", result.stdout)

    def test_rejects_staged_private_file_even_when_force_added(self) -> None:
        repo = create_basic_repo(self.root / "repo")
        plan = write_text(repo, "plan.md", "private plan\n")
        self.run_guard("protect", repo, plan)
        git(repo, "add", "--force", "plan.md")

        result = self.run_guard("check", repo, plan)

        self.assert_failed_with(result, "tracked or staged")
        self.assertNotIn("plan.md", combined_output(result))

    def test_rejects_private_filename_removed_from_current_tree(self) -> None:
        repo = create_basic_repo(self.root / "repo")
        private_input = self.private_input("idea.md", "different private concept\n")
        write_text(repo, "idea.md", "private concept\n")
        commit_all(repo, "test: accidentally add idea")
        (repo / "idea.md").unlink()
        commit_all(repo, "test: remove idea")
        self.run_guard("protect", repo, private_input)

        result = self.run_guard("check", repo, private_input)

        self.assert_failed_with(result, "reachable history")
        self.assertNotIn("idea.md", combined_output(result))

    def test_replace_ref_cannot_hide_private_history(self) -> None:
        repo = create_basic_repo(self.root / "repo")
        clean_commit = git(repo, "rev-parse", "HEAD").stdout.strip()
        private_input = self.private_input("idea.md", "different private concept\n")
        write_text(repo, "idea.md", "private concept\n")
        private_commit = commit_all(repo, "test: accidentally add idea")
        (repo / "idea.md").unlink()
        commit_all(repo, "test: remove idea")
        git(repo, "replace", private_commit, clean_commit)
        self.run_guard("protect", repo, private_input)

        result = self.run_guard("check", repo, private_input)

        self.assert_failed_with(result, "reachable history")
        self.assertNotIn("idea.md", combined_output(result))

    def test_rejects_historical_private_path_when_blob_is_duplicated(self) -> None:
        repo = create_basic_repo(self.root / "repo")
        private_input = self.private_input("plan.md", "different private plan\n")
        write_text(repo, "public-notes.md", "identical bytes\n")
        write_text(repo, "nested/plan.md", "identical bytes\n")
        commit_all(repo, "test: duplicate private blob")
        (repo / "nested" / "plan.md").unlink()
        commit_all(repo, "test: remove private path")
        self.run_guard("protect", repo, private_input)

        result = self.run_guard("check", repo, private_input)

        self.assert_failed_with(result, "reachable history")
        self.assertNotIn("nested/plan.md", combined_output(result))

    def test_rejects_private_content_under_a_renamed_tracked_file(self) -> None:
        repo = create_basic_repo(self.root / "repo")
        private_input = self.private_input(
            "idea.md",
            "This exact private design is deliberately long enough to be meaningful, but the "
            "exact-byte fingerprint is what this regression case exercises.\n",
        )
        write_text(repo, "public-design.md", private_input.read_text(encoding="utf-8"))
        commit_all(repo, "test: publish renamed private content")
        self.run_guard("protect", repo, private_input)

        result = self.run_guard("check", repo, private_input)

        self.assert_failed_with(result, "private planning content appears")
        self.assertNotIn("public-design.md", combined_output(result))

    def test_rejects_private_file_present_only_in_a_merge_tree(self) -> None:
        repo = create_basic_repo(self.root / "repo")
        private_input = self.private_input("plan.md", "different merge plan\n")
        root_commit = git(repo, "rev-parse", "HEAD").stdout.strip()
        git(repo, "switch", "--create", "side")
        write_text(repo, "side.txt", "side\n")
        commit_all(repo, "test: side")
        git(repo, "switch", "main")
        write_text(repo, "main.txt", "main\n")
        commit_all(repo, "test: main")
        self.assertEqual(root_commit, git(repo, "merge-base", "main", "side").stdout.strip())
        git(repo, "merge", "--no-commit", "--no-ff", "side")
        write_text(repo, "plan.md", "merge-only private plan\n")
        git(repo, "add", "plan.md")
        git(repo, "commit", "--no-gpg-sign", "-m", "test: merge with private plan")
        (repo / "plan.md").unlink()
        commit_all(repo, "test: remove merge-only plan")
        self.run_guard("protect", repo, private_input)

        result = self.run_guard("check", repo, private_input)

        self.assert_failed_with(result, "reachable history")
        self.assertNotIn("plan.md", combined_output(result))

    def test_rejects_nonempty_git_grafts(self) -> None:
        repo = create_basic_repo(self.root / "repo")
        self.run_guard("protect", repo)
        grafts = Path(
            git(
                repo,
                "rev-parse",
                "--path-format=absolute",
                "--git-path",
                "info/grafts",
            ).stdout.strip()
        )
        grafts.parent.mkdir(parents=True, exist_ok=True)
        grafts.write_text("not-empty\n", encoding="utf-8")

        result = self.run_guard("check", repo)

        self.assertEqual(result.returncode, 2, combined_output(result))
        self.assertIn("grafts", combined_output(result).casefold())

    def test_checks_private_path_in_containing_parent_repository(self) -> None:
        parent = init_repo(self.root / "parent")
        write_text(parent, "README.md", "# Parent\n")
        commit_all(parent, "test: initialize parent")
        child = create_basic_repo(parent / "child")
        idea = write_text(parent, "idea.md", "parent-private concept\n")
        git(parent, "add", "--force", "idea.md")
        self.run_guard("protect", child)

        result = self.run_guard("check", child, idea)

        self.assert_failed_with(result, "tracked or staged")
        self.assertNotIn(str(parent.resolve()), combined_output(result))

    def test_rejects_private_content_in_nested_reachable_annotated_tag(self) -> None:
        repo = create_basic_repo(self.root / "repo")
        secret = (
            "Confidential launch sequence midnight-orchid must never appear in public metadata."
        )
        idea = self.private_input("idea.md", f"{secret}\n")
        plan = self.private_input("plan.md", "A separate private release plan.\n")
        protected = self.run_guard("protect", repo, idea, plan)
        self.assertEqual(protected.returncode, 0, combined_output(protected))
        git(repo, "tag", "--annotate", "inner", "--message", secret)
        git(repo, "tag", "--annotate", "outer", "inner", "--message", "Public wrapper")
        git(repo, "tag", "--delete", "inner")

        result = self.run_guard("check", repo, idea, plan)

        self.assert_failed_with(result, "private planning content appears")
        self.assertNotIn("<annotated tag object>", combined_output(result))
        self.assertNotIn(secret, combined_output(result))

    def test_normalizes_unicode_nfc_before_comparing_prose(self) -> None:
        repo = create_basic_repo(self.root / "repo")
        composed = "Confidential caf\u00e9 launch details with a distinctive private sequence."
        idea = self.private_input("idea.md", f"{composed}\n")
        plan = self.private_input("plan.md", "A separate private release plan.\n")
        protected = self.run_guard("protect", repo, idea, plan)
        self.assertEqual(protected.returncode, 0, combined_output(protected))
        decomposed = unicodedata.normalize("NFD", composed)
        write_text(repo, "public-notes.md", f"Prefix {decomposed} suffix.\n")
        commit_all(repo, "test: publish canonically equivalent private prose")

        result = self.run_guard("check", repo, idea, plan)

        self.assert_failed_with(result, "private planning content")
        self.assertNotIn("public-notes.md", combined_output(result))

    def test_rejects_utf16_private_fragment_inside_binary_blob(self) -> None:
        repo = create_basic_repo(self.root / "repo")
        secret = "Distinctive confidential binary payload phrase for internal planning only."
        idea = self.private_input("idea.md", f"{secret}\n")
        plan = self.private_input("plan.md", "A separate private release plan.\n")
        protected = self.run_guard("protect", repo, idea, plan)
        self.assertEqual(protected.returncode, 0, combined_output(protected))
        payload = b"\x00opaque-prefix\x00" + secret.encode("utf-16-le") + b"\x00suffix"
        target = repo / "payload.bin"
        target.write_bytes(payload)
        commit_all(repo, "test: publish binary payload")

        result = self.run_guard("check", repo, idea, plan)

        self.assert_failed_with(result, "private planning content")
        self.assertNotIn("payload.bin", combined_output(result))
        self.assertNotIn(secret, combined_output(result))

    def test_rejects_utf8_private_fragment_inside_binary_blob(self) -> None:
        repo = create_basic_repo(self.root / "repo")
        secret = "Distinctive confidential UTF-8 payload phrase for internal planning only."
        idea = self.private_input("idea.md", f"{secret}\n")
        plan = self.private_input("plan.md", "A separate private release plan.\n")
        protected = self.run_guard("protect", repo, idea, plan)
        self.assertEqual(protected.returncode, 0, combined_output(protected))
        (repo / "payload.bin").write_bytes(
            b"\x00opaque-prefix\xff" + secret.encode("utf-8") + b"\x00suffix"
        )
        commit_all(repo, "test: publish binary payload")

        result = self.run_guard("check", repo, idea, plan)

        self.assert_failed_with(result, "private planning content")
        self.assertNotIn("payload.bin", combined_output(result))
        self.assertNotIn(secret, combined_output(result))

    def test_rejects_late_private_canary_inside_binary_blob(self) -> None:
        repo = create_basic_repo(self.root / "repo")
        secret = "Late confidential canary cobalt-firefly belongs only in the private plan."
        filler = "".join(
            f"Internal planning filler row {number:05d} with nonpublic context.\n"
            for number in range(800)
        )
        idea = self.private_input("idea.md", f"{filler}{secret}\n")
        self.assertGreater(idea.stat().st_size, 40_000)
        plan = self.private_input("plan.md", "A separate private release plan.\n")
        protected = self.run_guard("protect", repo, idea, plan)
        self.assertEqual(protected.returncode, 0, combined_output(protected))
        (repo / "late-payload.bin").write_bytes(
            b"\x00opaque-prefix\xff" + secret.encode("utf-8") + b"\x00suffix"
        )
        commit_all(repo, "test: publish late binary canary")

        result = self.run_guard("check", repo, idea, plan)

        self.assert_failed_with(result, "private planning content")
        self.assertNotIn("late-payload.bin", combined_output(result))
        self.assertNotIn(secret, combined_output(result))

    def test_allows_the_approved_public_project_name(self) -> None:
        repo = create_basic_repo(self.root / "repo")
        idea = self.private_input(
            "idea.md",
            "Project name: ExampleOpenSource\n"
            "Private rollout details: use the confidential cobalt-firefly sequence.\n",
        )
        plan = self.private_input(
            "plan.md", "Internal release steps stay in this private planning file.\n"
        )
        protected = self.run_guard("protect", repo, idea, plan)
        self.assertEqual(protected.returncode, 0, combined_output(protected))
        write_text(
            repo,
            "README.md",
            "# ExampleOpenSource\n\nA useful public package.\n",
        )
        commit_all(repo, "docs: publish approved project name")

        result = self.run_guard("check", repo, idea, plan)

        self.assertEqual(result.returncode, 0, combined_output(result))

    def test_rejects_short_secret_codename_inside_binary_blobs(self) -> None:
        repo = create_basic_repo(self.root / "repo")
        secret = "Secret codename: Obsidian-7"
        idea = self.private_input("idea.md", f"{secret}\n")
        plan = self.private_input("plan.md", "A separate private release plan.\n")
        protected = self.run_guard("protect", repo, idea, plan)
        self.assertEqual(protected.returncode, 0, combined_output(protected))
        (repo / "codename-utf8.bin").write_bytes(
            b"\x00opaque\xff" + secret.encode("utf-8") + b"\x00"
        )
        (repo / "codename-utf16.bin").write_bytes(
            b"\x00opaque\xff" + secret.encode("utf-16-le") + b"\x00"
        )
        commit_all(repo, "test: publish short private codename")

        result = self.run_guard("check", repo, idea, plan)

        self.assert_failed_with(result, "private planning content")
        self.assertNotIn("codename-utf8.bin", combined_output(result))
        self.assertNotIn("codename-utf16.bin", combined_output(result))
        self.assertNotIn(secret, combined_output(result))

    def test_rejects_late_canary_after_five_thousand_private_lines(self) -> None:
        repo = create_basic_repo(self.root / "repo")
        ordinary_lines = [
            f"Internal planning marker number {number:04d} remains confidential."
            for number in range(5_000)
        ]
        late_canary = "Late canary midnight-violet-5001 must remain confidential."
        idea = self.private_input(
            "idea.md",
            "\n".join((*ordinary_lines, late_canary, "")),
        )
        plan = self.private_input("plan.md", "A separate private release plan.\n")
        protected = self.run_guard("protect", repo, idea, plan)
        self.assertEqual(protected.returncode, 0, combined_output(protected))
        (repo / "payload.bin").write_bytes(
            b"\x00opaque-prefix\xff" + late_canary.encode() + b"\x00suffix"
        )
        commit_all(repo, "test: publish late private canary")

        result = self.run_guard("check", repo, idea, plan)

        self.assert_failed_with(result, "private planning content")
        self.assertNotIn("payload.bin", combined_output(result))
        self.assertNotIn(late_canary, combined_output(result))

    def test_rejects_private_value_inside_gzip_blob(self) -> None:
        repo = create_basic_repo(self.root / "repo")
        secret = "midnight-orchid-gzip"
        idea = self.private_input("idea.md", f"codename: {secret}\n")
        plan = self.private_input("plan.md", "A separate private release plan.\n")
        self.assertEqual(
            self.run_guard("protect", repo, idea, plan).returncode,
            0,
        )
        (repo / "payload.gz").write_bytes(gzip.compress(f"embedded {secret}\n".encode()))
        commit_all(repo, "test: publish compressed payload")

        result = self.run_guard("check", repo, idea, plan)

        self.assert_failed_with(result, "private planning content")
        self.assertNotIn(secret, combined_output(result))

    def test_rejects_private_value_inside_base64_blob(self) -> None:
        repo = create_basic_repo(self.root / "repo")
        secret = "midnight-orchid-base64"
        idea = self.private_input("idea.md", f"codename: {secret}\n")
        plan = self.private_input("plan.md", "A separate private release plan.\n")
        self.assertEqual(
            self.run_guard("protect", repo, idea, plan).returncode,
            0,
        )
        (repo / "payload.b64").write_bytes(base64.b64encode(f"embedded {secret}\n".encode()))
        commit_all(repo, "test: publish encoded payload")

        result = self.run_guard("check", repo, idea, plan)

        self.assert_failed_with(result, "private planning content")
        self.assertNotIn(secret, combined_output(result))

    def test_rejects_private_rhs_value_inside_utf32_blob(self) -> None:
        repo = create_basic_repo(self.root / "repo")
        secret = "violet-owl-32"
        idea = self.private_input("idea.md", f"codename: {secret}\n")
        plan = self.private_input("plan.md", "A separate private release plan.\n")
        self.assertEqual(
            self.run_guard("protect", repo, idea, plan).returncode,
            0,
        )
        (repo / "payload.bin").write_bytes(secret.encode("utf-32-le"))
        commit_all(repo, "test: publish UTF-32 payload")

        result = self.run_guard("check", repo, idea, plan)

        self.assert_failed_with(result, "private planning content")
        self.assertNotIn(secret, combined_output(result))

    def test_rejects_concatenated_bzip2_streams(self) -> None:
        repo = create_basic_repo(self.root / "repo")
        idea = self.private_input("idea.md", "A private source idea.\n")
        plan = self.private_input("plan.md", "A separate private release plan.\n")
        self.assertEqual(
            self.run_guard("protect", repo, idea, plan).returncode,
            0,
        )
        (repo / "payload.bz2").write_bytes(
            bz2.compress(b"first stream\n") + bz2.compress(b"second stream\n")
        )
        commit_all(repo, "test: publish concatenated bzip2")

        result = self.run_guard("check", repo, idea, plan)

        self.assertEqual(result.returncode, 2, combined_output(result))
        self.assertIn("bzip2 blob has concatenated or trailing data", combined_output(result))

    def test_rejects_concatenated_xz_streams(self) -> None:
        repo = create_basic_repo(self.root / "repo")
        idea = self.private_input("idea.md", "A private source idea.\n")
        plan = self.private_input("plan.md", "A separate private release plan.\n")
        self.assertEqual(
            self.run_guard("protect", repo, idea, plan).returncode,
            0,
        )
        (repo / "payload.xz").write_bytes(
            lzma.compress(b"first stream\n") + lzma.compress(b"second stream\n")
        )
        commit_all(repo, "test: publish concatenated xz")

        result = self.run_guard("check", repo, idea, plan)

        self.assertEqual(result.returncode, 2, combined_output(result))
        self.assertIn("xz blob has concatenated or trailing data", combined_output(result))

    def test_allows_documented_public_values_from_private_inputs(self) -> None:
        repo = create_basic_repo(self.root / "repo")
        public_values = (
            "License: Apache-2.0\n\n"
            "Commit-signing policy: required by default\n\n"
            "Release-tag signing policy: required by default\n\n"
            "None found with evidence\n\n"
        )
        idea = self.private_input(
            "idea.md",
            public_values + "Private rollout details: midnight-orchid remains confidential.\n",
        )
        plan = self.private_input("plan.md", "A separate private release plan.\n")
        self.assertEqual(
            self.run_guard("protect", repo, idea, plan).returncode,
            0,
        )
        write_text(repo, "PUBLIC-POLICY.md", public_values)
        commit_all(repo, "docs: publish approved policy values")

        result = self.run_guard("check", repo, idea, plan)

        self.assertEqual(result.returncode, 0, combined_output(result))

    def test_redacts_private_values_and_locations_from_diagnostics(self) -> None:
        repo = create_basic_repo(self.root / "repo")
        secret = "midnight-orchid-redaction"
        idea = self.private_input("idea.md", f"codename: {secret}\n")
        plan = self.private_input("plan.md", "A separate private release plan.\n")
        self.assertEqual(
            self.run_guard("protect", repo, idea, plan).returncode,
            0,
        )
        write_text(repo, "internal-launch-notes.md", f"codename: {secret}\n")
        commit_all(repo, f"test: accidentally publish {secret}")

        result = self.run_guard("check", repo, idea, plan)

        self.assert_failed_with(result, "private planning content")
        output = combined_output(result)
        self.assertNotIn(secret, output)
        self.assertNotIn("internal-launch-notes.md", output)
        self.assertNotIn(str(idea.resolve()), output)

    def test_requires_an_absolute_git_program(self) -> None:
        repo = create_basic_repo(self.root / "repo")

        result = run_script(
            GUARD_SCRIPT,
            "--git-program",
            "git",
            "--git-program-sha256",
            "0" * 64,
            "check",
            repo,
        )

        self.assertEqual(result.returncode, 2, combined_output(result))
        self.assertIn("must be an absolute path", combined_output(result))

    def test_rejects_live_plan_reused_as_approved_snapshot(self) -> None:
        repo = create_basic_repo(self.root / "repo")
        idea = self.private_input("idea.md", "A private source idea.\n")
        plan = self.private_input("plan.md", "A private approved plan.\n")

        result = self.run_bound_guard(
            repo,
            [idea, plan],
            plan,
            private_input_set_digest([idea, plan]),
        )

        self.assertEqual(result.returncode, 2, combined_output(result))
        self.assertIn("approved plan snapshot must be separate", combined_output(result))

    def test_rejects_hardlink_alias_for_approved_plan_snapshot(self) -> None:
        repo = create_basic_repo(self.root / "repo")
        idea = self.private_input("idea.md", "A private source idea.\n")
        plan = self.private_input("plan.md", "A private approved plan.\n")
        approved = self.root / "approved-plans" / "hardlink-snapshot.md"
        approved.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(plan, approved)
        except OSError as error:
            self.skipTest(f"hardlinks are unavailable: {error}")

        result = self.run_bound_guard(
            repo,
            [idea, plan],
            approved,
            "0" * 64,
        )

        self.assertEqual(result.returncode, 2, combined_output(result))
        self.assertIn("inventory contains aliased files", combined_output(result))

    def test_rejects_approved_snapshot_with_different_plan_bytes(self) -> None:
        repo = create_basic_repo(self.root / "repo")
        idea = self.private_input("idea.md", "A private source idea.\n")
        plan = self.private_input("plan.md", "A private approved plan.\n")
        approved = self.root / "approved-plans" / "different-snapshot.md"
        approved.parent.mkdir(parents=True, exist_ok=True)
        approved.write_text("A different private plan revision.\n", encoding="utf-8")

        result = self.run_bound_guard(
            repo,
            [idea, plan],
            approved,
            private_input_set_digest([idea, plan, approved]),
        )

        self.assertEqual(result.returncode, 2, combined_output(result))
        self.assertIn(
            "live plan does not match the approved plan snapshot",
            combined_output(result),
        )

    def test_rejects_unapproved_git_program_digest(self) -> None:
        repo = create_basic_repo(self.root / "repo")
        incorrect_digest = "0" * 64
        if incorrect_digest == GIT_PROGRAM_SHA256:
            incorrect_digest = "1" * 64

        result = run_script(
            GUARD_SCRIPT,
            "--git-program",
            GIT_PROGRAM,
            "--git-program-sha256",
            incorrect_digest,
            "check",
            repo,
        )

        self.assertEqual(result.returncode, 2, combined_output(result))
        self.assertIn("does not match", combined_output(result))
        self.assertNotIn("Trusted Git:", combined_output(result))

    def test_ignores_ambient_global_and_system_git_config(self) -> None:
        repo = create_basic_repo(self.root / "repo")
        hostile_global = self.root / "hostile-global.gitconfig"
        hostile_system = self.root / "hostile-system.gitconfig"
        hostile_global.write_text("[invalid\n", encoding="utf-8")
        hostile_system.write_text("[invalid\n", encoding="utf-8")
        environment = os.environ.copy()
        environment["GIT_CONFIG_GLOBAL"] = str(hostile_global)
        environment["GIT_CONFIG_SYSTEM"] = str(hostile_system)
        environment["GIT_CONFIG_NOSYSTEM"] = "0"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"

        result = subprocess.run(
            [
                sys.executable,
                str(GUARD_SCRIPT),
                "--git-program",
                str(GIT_PROGRAM),
                "--git-program-sha256",
                GIT_PROGRAM_SHA256,
                "protect",
                str(repo),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
        )

        self.assertEqual(result.returncode, 0, combined_output(result))

    def test_rejects_git_program_inside_the_audited_worktree(self) -> None:
        repo = create_basic_repo(self.root / "repo")
        local_program = repo / ("git-program.exe" if os.name == "nt" else "git-program")
        shutil.copy2(sys.executable, local_program)
        local_program.chmod(local_program.stat().st_mode | 0o111)
        local_program_sha256 = hashlib.sha256(local_program.read_bytes()).hexdigest()

        result = run_script(
            GUARD_SCRIPT,
            "--git-program",
            local_program,
            "--git-program-sha256",
            local_program_sha256,
            "check",
            repo,
        )

        self.assertEqual(result.returncode, 2, combined_output(result))
        self.assertIn("outside every audited Git worktree", combined_output(result))

    def test_rejects_symlinked_git_info_directory(self) -> None:
        repo = create_basic_repo(self.root / "repo")
        info = repo / ".git" / "info"
        real_info = repo / ".git" / "info-real"
        info.rename(real_info)
        try:
            os.symlink(real_info, info, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"directory symlinks are unavailable: {error}")

        result = self.run_guard("protect", repo)

        self.assertEqual(result.returncode, 2, combined_output(result))
        self.assertIn("symlink or reparse point", combined_output(result))

    def test_fails_closed_when_a_ref_points_to_a_missing_object(self) -> None:
        repo = create_basic_repo(self.root / "repo")
        protected = self.run_guard("protect", repo)
        self.assertEqual(protected.returncode, 0, combined_output(protected))
        broken_ref = repo / ".git" / "refs" / "heads" / "broken"
        broken_ref.parent.mkdir(parents=True, exist_ok=True)
        broken_ref.write_text(f"{'f' * 40}\n", encoding="ascii")

        result = self.run_guard("check", repo)

        self.assertEqual(result.returncode, 2, combined_output(result))
        self.assertRegex(combined_output(result).casefold(), r"bad object|enumerate")


if __name__ == "__main__":
    unittest.main()
