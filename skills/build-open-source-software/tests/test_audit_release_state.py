from __future__ import annotations

import gzip
import io
import os
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

from tests.support import (
    COPYRIGHT_HOLDER,
    COPYRIGHT_YEAR,
    FIXTURES,
    RELEASE_SCRIPT,
    VERSION,
    approved_plan_snapshot,
    combined_output,
    commit_all,
    create_release_repo,
    git,
    private_input_set_digest,
    private_inputs,
    release_arguments,
    release_staging_directory,
    run_script,
    sha256_file,
    tag_release,
    write_text,
)


class AuditReleaseStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="build-oss-release-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.artifacts = self.root / "artifacts"
        self.artifacts.mkdir()
        self.canonical_license = (FIXTURES / "APACHE-2.0.txt").read_bytes()
        self.approved_notice = (
            f"Example Project\nCopyright {COPYRIGHT_YEAR} {COPYRIGHT_HOLDER}\n".encode()
        )
        self.project_metadata = f'{{"name":"example-project","version":"{VERSION}"}}\n'.encode()

    def new_repo(self, name: str = "repo", *, include_manifest: bool = True) -> Path:
        return create_release_repo(
            self.root / name,
            include_manifest=include_manifest,
        )

    def artifact_path(self, suffix: str = ".zip", stem: str = "example-project") -> Path:
        return self.artifacts / f"{stem}-{VERSION}{suffix}"

    def safe_zip(self, path: Path | None = None) -> Path:
        target = path or self.artifact_path()
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            self.add_zip_governance(archive)
            archive.writestr("example-project/README.txt", "release payload\n")
        return target

    def add_zip_governance(self, archive: zipfile.ZipFile) -> None:
        archive.writestr("example-project/LICENSE", self.canonical_license)
        archive.writestr("example-project/NOTICE", self.approved_notice)
        archive.writestr("example-project/package.json", self.project_metadata)

    def add_tar_bytes(self, archive: tarfile.TarFile, name: str, data: bytes) -> None:
        member = tarfile.TarInfo(name)
        member.size = len(data)
        archive.addfile(member, io.BytesIO(data))

    def add_tar_governance(self, archive: tarfile.TarFile) -> None:
        self.add_tar_bytes(archive, "example-project/LICENSE", self.canonical_license)
        self.add_tar_bytes(archive, "example-project/NOTICE", self.approved_notice)
        self.add_tar_bytes(
            archive,
            "example-project/package.json",
            self.project_metadata,
        )

    def add_local_only_zip_extra(self, path: Path) -> None:
        """Insert an extra field into only the final ZIP local header."""
        payload = bytearray(path.read_bytes())
        end_offset = payload.rfind(b"PK\x05\x06")
        self.assertGreaterEqual(end_offset, 0)
        central_offset = struct.unpack_from("<I", payload, end_offset + 16)[0]

        central_cursor = central_offset
        local_offsets: list[int] = []
        while payload[central_cursor : central_cursor + 4] == b"PK\x01\x02":
            filename_length, extra_length, comment_length = struct.unpack_from(
                "<HHH", payload, central_cursor + 28
            )
            local_offsets.append(struct.unpack_from("<I", payload, central_cursor + 42)[0])
            central_cursor += 46 + filename_length + extra_length + comment_length
        self.assertTrue(local_offsets)

        local_offset = max(local_offsets)
        self.assertEqual(payload[local_offset : local_offset + 4], b"PK\x03\x04")
        filename_length, existing_extra_length = struct.unpack_from(
            "<HH", payload, local_offset + 26
        )
        local_extra = b"\xfe\xca\x04\x00hide"
        insert_offset = local_offset + 30 + filename_length + existing_extra_length
        payload[insert_offset:insert_offset] = local_extra
        struct.pack_into(
            "<H",
            payload,
            local_offset + 28,
            existing_extra_length + len(local_extra),
        )

        shifted_end_offset = end_offset + len(local_extra)
        struct.pack_into(
            "<I",
            payload,
            shifted_end_offset + 16,
            central_offset + len(local_extra),
        )
        path.write_bytes(payload)

    def replace_local_zip_name(self, path: Path, old: bytes, new: bytes) -> None:
        self.assertEqual(len(old), len(new))
        with zipfile.ZipFile(path) as archive:
            info = archive.getinfo(old.decode("ascii"))
        payload = bytearray(path.read_bytes())
        filename_length = struct.unpack_from("<H", payload, info.header_offset + 26)[0]
        name_offset = info.header_offset + 30
        self.assertEqual(payload[name_offset : name_offset + filename_length], old)
        payload[name_offset : name_offset + filename_length] = new
        path.write_bytes(payload)

    def inflate_zip_central_directory_size(self, path: Path) -> None:
        payload = bytearray(path.read_bytes())
        end_offset = payload.rfind(b"PK\x05\x06")
        self.assertGreaterEqual(end_offset, 0)
        struct.pack_into("<I", payload, end_offset + 12, 64_000_001)
        path.write_bytes(payload)

    def run_release(
        self,
        repo: Path,
        *,
        artifact: Path | None = None,
        tag: bool = False,
        tag_only: bool = False,
        holder: str = COPYRIGHT_HOLDER,
        archive_contract: bool = True,
        adapter_inspected: bool | str = False,
        staging_directory: Path | None = None,
        max_artifact_bytes: int = 100_000_000,
        extra_arguments: tuple[str | Path, ...] = (),
    ) -> subprocess.CompletedProcess[str]:
        arguments = release_arguments(
            repo,
            artifact=artifact,
            tag=tag,
            tag_only=tag_only,
            holder=holder,
            archive_contract=archive_contract,
            adapter_inspected=adapter_inspected,
            staging_directory=staging_directory,
            max_artifact_bytes=max_artifact_bytes,
        )
        arguments.extend(extra_arguments)
        return run_script(RELEASE_SCRIPT, *arguments)

    def run_nonarchive_release(
        self,
        repo: Path,
        artifact: Path,
        *,
        adapter_inspected: bool | str,
        bundled_payload: bytes | None = None,
    ) -> subprocess.CompletedProcess[str]:
        bundle = self.artifact_path(stem="example-project-legal")
        with zipfile.ZipFile(bundle, "w") as archive:
            self.add_zip_governance(archive)
            archive.writestr(
                f"example-project/{artifact.name}",
                artifact.read_bytes() if bundled_payload is None else bundled_payload,
            )
        arguments = release_arguments(
            repo,
            artifact=artifact,
            archive_contract=False,
            adapter_inspected=adapter_inspected,
        )
        arguments.extend(
            (
                "--artifact",
                bundle,
                "--archive-format",
                f"{bundle.name}=zip",
                "--require-member",
                f"{bundle.name}=example-project/*",
                "--allow-member",
                f"{bundle.name}=example-project/*",
                "--license-member",
                f"{bundle.name}=example-project/LICENSE",
                "--notice-member",
                f"{bundle.name}=example-project/NOTICE",
                "--metadata-member",
                f"{bundle.name}=example-project/package.json",
                "--legal-bundle",
                f"{artifact.name}={bundle.name}",
            )
        )
        return run_script(RELEASE_SCRIPT, *arguments)

    def assert_failed_with(self, result: subprocess.CompletedProcess[str], phrase: str) -> None:
        self.assertEqual(result.returncode, 1, combined_output(result))
        self.assertIn(phrase, combined_output(result))

    def test_canonical_apache_license_notice_and_safe_archive_pass(self) -> None:
        repo = self.new_repo()
        artifact = self.safe_zip()

        result = self.run_release(repo, artifact=artifact)

        self.assertEqual(result.returncode, 0, combined_output(result))
        self.assertIn("Release-state audit passed", result.stdout)
        self.assertIn("sha256", result.stdout)
        digest = sha256_file(artifact)
        snapshot = release_staging_directory(repo) / digest / artifact.name
        self.assertTrue(snapshot.is_file())
        self.assertEqual(snapshot.read_bytes(), artifact.read_bytes())
        self.assertIn("content-addressed read-only snapshot", result.stdout)

    def test_dynamic_version_pattern_does_not_trigger_default_manifest(self) -> None:
        repo = self.new_repo()
        write_text(
            repo,
            "package.json",
            '{"name":"example-project","version":"9.9.9","private":false}\n',
        )
        write_text(repo, "VERSION.txt", f"VERSION={VERSION}\n")
        commit_all(repo, "test: use a dynamic version source")
        artifact = self.safe_zip()

        result = self.run_release(
            repo,
            artifact=artifact,
            extra_arguments=(
                "--version-pattern",
                r"VERSION.txt=VERSION=([0-9.]+)",
            ),
        )

        self.assertEqual(result.returncode, 0, combined_output(result))
        self.assertIn(f"version {VERSION}: VERSION.txt", result.stdout)
        self.assertNotIn("version mismatch in package.json", result.stdout)

    def test_exact_metadata_member_ignores_dependency_manifest(self) -> None:
        repo = self.new_repo()
        artifact = self.artifact_path()
        with zipfile.ZipFile(artifact, "w") as archive:
            self.add_zip_governance(archive)
            archive.writestr(
                "example-project/vendor/dependency/package.json",
                '{"name":"dependency","version":"9.9.9"}\n',
            )

        result = self.run_release(
            repo,
            artifact=artifact,
            extra_arguments=(
                "--allow-member",
                f"{artifact.name}=example-project/vendor/**",
            ),
        )

        self.assertEqual(result.returncode, 0, combined_output(result))
        self.assertIn(
            f"artifact version {VERSION}: {artifact.name}!example-project/package.json",
            result.stdout,
        )

    def test_rejects_modified_apache_license(self) -> None:
        repo = self.new_repo()
        license_path = repo / "LICENSE"
        text = license_path.read_text(encoding="utf-8")
        write_text(repo, "LICENSE", text.replace("Apache License", "Altered License", 1))
        commit_all(repo, "test: alter license")

        result = self.run_release(repo, artifact=self.safe_zip())

        self.assert_failed_with(result, "canonical Apache License 2.0")

    def test_rejects_notice_with_wrong_holder(self) -> None:
        repo = self.new_repo()
        write_text(repo, "NOTICE", "Example Project\nCopyright 2026 Someone Else\n")
        commit_all(repo, "test: alter notice")

        result = self.run_release(repo, artifact=self.safe_zip())

        self.assert_failed_with(result, "NOTICE does not contain")

    def test_rejects_modified_license_inside_archive(self) -> None:
        repo = self.new_repo()
        artifact = self.artifact_path()
        altered = self.canonical_license.replace(b"Apache License", b"Altered License", 1)
        with zipfile.ZipFile(artifact, "w") as archive:
            archive.writestr("example-project/LICENSE", altered)
            archive.writestr("example-project/NOTICE", self.approved_notice)
            archive.writestr("example-project/package.json", self.project_metadata)
            archive.writestr("example-project/README.txt", "release payload\n")

        result = self.run_release(repo, artifact=artifact)

        self.assert_failed_with(result, "artifact LICENSE is not canonical")

    def test_rejects_wrong_notice_inside_archive(self) -> None:
        repo = self.new_repo()
        artifact = self.artifact_path()
        with zipfile.ZipFile(artifact, "w") as archive:
            archive.writestr("example-project/LICENSE", self.canonical_license)
            archive.writestr(
                "example-project/NOTICE",
                "Example Project\nCopyright 2026 Someone Else\n",
            )
            archive.writestr("example-project/package.json", self.project_metadata)
            archive.writestr("example-project/README.txt", "release payload\n")

        result = self.run_release(repo, artifact=artifact)

        self.assert_failed_with(
            result, "artifact NOTICE differs from the audited repository NOTICE"
        )

    def test_rejects_old_tag_that_is_not_current_default_branch_tip(self) -> None:
        repo = self.new_repo()
        tag_release(repo)
        write_text(repo, "post-release.txt", "new tip\n")
        commit_all(repo, "test: move branch beyond tag")

        result = self.run_release(repo, tag=True, tag_only=True)

        self.assert_failed_with(result, "tag commit is not the current HEAD")
        self.assertIn("tag commit is not the tip of main", combined_output(result))

    def test_tag_only_distribution_passes_without_manifest_or_file_artifact(
        self,
    ) -> None:
        repo = self.new_repo(include_manifest=False)
        tag_release(repo)

        result = self.run_release(repo, tag=True, tag_only=True)

        self.assertEqual(result.returncode, 0, combined_output(result))
        self.assertIn("tag commit", result.stdout)

    def test_tag_only_distribution_requires_a_tag(self) -> None:
        repo = self.new_repo(include_manifest=False)

        result = self.run_release(repo, tag_only=True)

        self.assert_failed_with(result, "--tag-only-distribution requires --tag")

    def test_filename_rejects_prerelease_suffix_after_exact_version(self) -> None:
        repo = self.new_repo()
        artifact = self.artifacts / f"example-project-{VERSION}rc1.zip"
        self.safe_zip(artifact)

        result = self.run_release(repo, artifact=artifact)

        self.assert_failed_with(result, "artifact filename does not contain version")

    def test_rejects_malformed_file_with_archive_extension(self) -> None:
        repo = self.new_repo()
        artifact = self.artifact_path()
        artifact.write_bytes(b"not a zip archive")

        result = self.run_release(repo, artifact=artifact)

        self.assert_failed_with(result, "archive extension but cannot be opened")

    def test_rejects_zip_with_prepended_envelope(self) -> None:
        repo = self.new_repo()
        artifact = self.safe_zip()
        artifact.write_bytes(b"prepended-envelope" + artifact.read_bytes())

        result = self.run_release(repo, artifact=artifact)

        self.assert_failed_with(result, "ZIP central-directory envelope is inconsistent")

    def test_rejects_zip_archive_comment(self) -> None:
        repo = self.new_repo()
        artifact = self.safe_zip()
        with zipfile.ZipFile(artifact, "a") as archive:
            archive.comment = b"unexpected archive comment"

        result = self.run_release(repo, artifact=artifact)

        self.assert_failed_with(result, "ZIP has a comment or trailing envelope bytes")

    def test_zip_preflight_rejects_oversized_central_directory_claim(self) -> None:
        repo = self.new_repo()
        artifact = self.safe_zip()
        self.inflate_zip_central_directory_size(artifact)

        result = self.run_release(repo, artifact=artifact)

        self.assert_failed_with(result, "ZIP central directory exceeds the allocation limit")

    def test_rejects_divergent_local_zip_filename(self) -> None:
        repo = self.new_repo()
        artifact = self.artifact_path()
        with zipfile.ZipFile(artifact, "w") as archive:
            self.add_zip_governance(archive)
            archive.writestr("example-project/docs/", b"")
        self.replace_local_zip_name(
            artifact,
            b"example-project/docs/",
            b"example-project/docx/",
        )

        result = self.run_release(
            repo,
            artifact=artifact,
            extra_arguments=(
                "--allow-member",
                f"{artifact.name}=example-project/**",
            ),
        )

        self.assert_failed_with(result, "ZIP local and central filenames differ")

    def test_rejects_local_only_zip_extra_field(self) -> None:
        repo = self.new_repo()
        artifact = self.artifact_path()
        with zipfile.ZipFile(artifact, "w") as archive:
            self.add_zip_governance(archive)
        self.add_local_only_zip_extra(artifact)
        with zipfile.ZipFile(artifact) as archive:
            self.assertIsNone(archive.testzip())
            self.assertTrue(all(not member.extra for member in archive.infolist()))

        result = self.run_release(repo, artifact=artifact)

        self.assert_failed_with(result, "ZIP local extra fields are not allowed")

    def test_rejects_zip_path_traversal(self) -> None:
        repo = self.new_repo()
        artifact = self.artifact_path()
        with zipfile.ZipFile(artifact, "w") as archive:
            self.add_zip_governance(archive)
            archive.writestr("../escape.txt", "unsafe\n")

        result = self.run_release(repo, artifact=artifact)

        self.assert_failed_with(result, "unsafe archive member path")

    def test_rejects_tar_path_traversal(self) -> None:
        repo = self.new_repo()
        artifact = self.artifact_path(suffix=".tar.gz")
        payload = b"unsafe\n"
        with tarfile.open(artifact, "w:gz") as archive:
            self.add_tar_governance(archive)
            self.add_tar_bytes(archive, "../escape.txt", payload)

        result = self.run_release(repo, artifact=artifact)

        self.assert_failed_with(result, "unsafe archive member path")

    def test_rejects_zip_symlink_member(self) -> None:
        repo = self.new_repo()
        artifact = self.artifact_path()
        with zipfile.ZipFile(artifact, "w") as archive:
            self.add_zip_governance(archive)
            member = zipfile.ZipInfo("example-project/link")
            member.create_system = 3
            member.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(member, "target.txt")

        result = self.run_release(repo, artifact=artifact)

        self.assert_failed_with(result, "archive symlink is not allowed")

    def test_rejects_tar_symlink_member(self) -> None:
        repo = self.new_repo()
        artifact = self.artifact_path(suffix=".tar")
        with tarfile.open(artifact, "w") as archive:
            self.add_tar_governance(archive)
            member = tarfile.TarInfo("example-project/link")
            member.type = tarfile.SYMTYPE
            member.linkname = "target.txt"
            archive.addfile(member)

        result = self.run_release(repo, artifact=artifact)

        self.assert_failed_with(result, "archive link or special member is not allowed")

    def test_rejects_nonzero_data_after_tar_end_marker(self) -> None:
        repo = self.new_repo()
        artifact = self.artifact_path(suffix=".tar")
        with tarfile.open(artifact, "w") as archive:
            self.add_tar_governance(archive)
        with artifact.open("ab") as stream:
            stream.write(b"hidden data after the TAR end marker\n")

        result = self.run_release(repo, artifact=artifact)

        self.assert_failed_with(result, "TAR has nonzero")

    def test_rejects_case_colliding_archive_members(self) -> None:
        repo = self.new_repo()
        artifact = self.artifact_path()
        with zipfile.ZipFile(artifact, "w") as archive:
            self.add_zip_governance(archive)
            archive.writestr("example-project/Readme.txt", "one\n")
            archive.writestr("example-project/README.txt", "two\n")

        result = self.run_release(repo, artifact=artifact)

        self.assert_failed_with(result, "case-colliding archive member path")

    def test_single_star_member_glob_does_not_cross_directory_boundaries(self) -> None:
        repo = self.new_repo()
        artifact = self.artifact_path()
        with zipfile.ZipFile(artifact, "w") as archive:
            self.add_zip_governance(archive)
            archive.writestr("example-project/nested/payload.txt", "safe\n")

        result = self.run_release(repo, artifact=artifact)

        self.assert_failed_with(result, "archive member is outside the approved allowlist")

    def test_rejects_windows_reserved_archive_member_name(self) -> None:
        repo = self.new_repo()
        artifact = self.artifact_path()
        with zipfile.ZipFile(artifact, "w") as archive:
            self.add_zip_governance(archive)
            archive.writestr("example-project/CON.txt", "unsafe\n")

        result = self.run_release(repo, artifact=artifact)

        self.assert_failed_with(result, "unsafe archive member path")

    def test_rejects_exclamation_mark_in_archive_member_name(self) -> None:
        repo = self.new_repo()
        artifact = self.artifact_path()
        with zipfile.ZipFile(artifact, "w") as archive:
            self.add_zip_governance(archive)
            archive.writestr("example-project/bang!.txt", "unsafe\n")

        result = self.run_release(repo, artifact=artifact)

        self.assert_failed_with(result, "unsafe archive member path")

    def test_rejects_private_file_inside_nested_archive(self) -> None:
        repo = self.new_repo()
        artifact = self.artifact_path()
        nested_bytes = io.BytesIO()
        with zipfile.ZipFile(nested_bytes, "w") as nested:
            nested.writestr("source/plan.md", "private plan\n")
        with zipfile.ZipFile(artifact, "w") as archive:
            self.add_zip_governance(archive)
            archive.writestr("example-project/sources.zip", nested_bytes.getvalue())

        result = self.run_release(repo, artifact=artifact)

        self.assert_failed_with(result, "private planning file is present in artifact")
        self.assertIn("source/plan.md", combined_output(result))

    def test_decompresses_nested_metadata_gzip_before_secret_scan(self) -> None:
        repo = self.new_repo()
        artifact = self.artifact_path()
        secret = "ghp_" + "12345678901234567890"
        with zipfile.ZipFile(artifact, "w") as archive:
            self.add_zip_governance(archive)
            archive.writestr(
                "example-project/metadata.gz",
                gzip.compress(f"token={secret}\n".encode()),
            )

        result = self.run_release(repo, artifact=artifact)

        self.assert_failed_with(result, "possible GitHub token")
        self.assertIn("metadata.gz", combined_output(result))
        self.assertNotIn(secret, combined_output(result))

    def test_rejects_utf16_secret_inside_archive(self) -> None:
        repo = self.new_repo()
        artifact = self.artifact_path()
        secret = "ghp_" + "12345678901234567890"
        with zipfile.ZipFile(artifact, "w") as archive:
            self.add_zip_governance(archive)
            archive.writestr(
                "example-project/config.txt",
                f"token={secret}\n".encode("utf-16"),
            )

        result = self.run_release(repo, artifact=artifact)

        self.assert_failed_with(result, "possible GitHub token")
        self.assertNotIn(secret, combined_output(result))

    def test_rejects_renamed_private_input_content_inside_archive(self) -> None:
        repo = self.new_repo()
        private_idea = repo.parent / f"{repo.name}-private-inputs" / "idea.md"
        artifact = self.artifact_path()
        with zipfile.ZipFile(artifact, "w") as archive:
            self.add_zip_governance(archive)
            archive.writestr(
                "example-project/public-design.md",
                private_idea.read_bytes(),
            )

        result = self.run_release(repo, artifact=artifact)

        self.assert_failed_with(result, "private planning content is present in artifact")

    def test_rejects_binary_encoded_private_fragment_inside_archive(self) -> None:
        repo = self.new_repo()
        secret = "Distinctive confidential release sequence for maintainers only, never public."
        private_idea = repo.parent / f"{repo.name}-private-inputs" / "idea.md"
        private_idea.write_text(f"{secret}\n", encoding="utf-8")
        artifact = self.artifact_path()
        with zipfile.ZipFile(artifact, "w") as archive:
            self.add_zip_governance(archive)
            archive.writestr(
                "example-project/payload.bin",
                b"\x00opaque-prefix\x00" + secret.encode("utf-16-le") + b"\x00suffix",
            )

        result = self.run_release(repo, artifact=artifact)

        self.assert_failed_with(result, "private planning content is present in artifact")
        self.assertNotIn(secret, combined_output(result))

    def test_allows_approved_public_policy_values_in_repo_and_artifact(self) -> None:
        repo = self.new_repo()
        public_values = (
            "Commit-signing policy: required by default\n"
            "Release-tag signing policy: required by default\n"
        )
        private_idea = repo.parent / f"{repo.name}-private-inputs" / "idea.md"
        private_idea.write_text(
            public_values + "Private rollout details: midnight-orchid remains confidential.\n",
            encoding="utf-8",
        )
        write_text(repo, "PUBLIC-POLICY.md", public_values)
        commit_all(repo, "docs: publish approved policy values")
        artifact = self.artifact_path()
        with zipfile.ZipFile(artifact, "w") as archive:
            self.add_zip_governance(archive)
            archive.writestr("example-project/POLICY.md", public_values)

        result = self.run_release(repo, artifact=artifact)

        self.assertEqual(result.returncode, 0, combined_output(result))

    def test_adjacent_private_text_remains_protected_after_public_line_stripping(
        self,
    ) -> None:
        repo = self.new_repo()
        public_values = (
            "Commit-signing policy: required by default\n"
            "Release-tag signing policy: required by default\n"
        )
        secret = "Private rollout details: midnight-orchid remains confidential."
        private_idea = repo.parent / f"{repo.name}-private-inputs" / "idea.md"
        private_idea.write_text(f"{public_values}{secret}\n", encoding="utf-8")
        write_text(repo, "PUBLIC-POLICY.md", public_values)
        commit_all(repo, "docs: publish approved policy values")
        artifact = self.artifact_path()
        with zipfile.ZipFile(artifact, "w") as archive:
            self.add_zip_governance(archive)
            archive.writestr("example-project/rollout.txt", f"{secret}\n")

        result = self.run_release(repo, artifact=artifact)

        self.assert_failed_with(result, "private planning content is present in artifact")
        self.assertNotIn(secret, combined_output(result))

    def test_nonarchive_artifact_requires_adapter_acknowledgement(self) -> None:
        repo = self.new_repo()
        artifact = self.artifact_path(suffix=".bin")
        artifact.write_bytes(b"safe compiled payload\n")

        result = self.run_nonarchive_release(
            repo,
            artifact,
            adapter_inspected=False,
        )

        self.assert_failed_with(result, "lacks digest-bound --adapter-inspected proof")

    def test_adapter_inspected_nonarchive_artifact_passes_bounded_scan(self) -> None:
        repo = self.new_repo()
        artifact = self.artifact_path(suffix=".bin")
        artifact.write_bytes(b"safe compiled payload\n")

        result = self.run_nonarchive_release(
            repo,
            artifact,
            adapter_inspected=True,
        )

        self.assertEqual(result.returncode, 0, combined_output(result))
        self.assertIn("bounded non-archive scan", result.stdout)

    def test_rejects_adapter_proof_for_different_artifact_bytes(self) -> None:
        repo = self.new_repo()
        artifact = self.artifact_path(suffix=".bin")
        artifact.write_bytes(b"safe compiled payload\n")

        result = self.run_nonarchive_release(
            repo,
            artifact,
            adapter_inspected="0" * 64,
        )

        self.assert_failed_with(result, "adapter inspection digest mismatch")

    def test_rejects_staging_directory_inside_repository(self) -> None:
        repo = self.new_repo()
        artifact = self.safe_zip()

        result = self.run_release(
            repo,
            artifact=artifact,
            staging_directory=repo / "artifact-staging",
        )

        self.assert_failed_with(
            result, "artifact staging directory must be outside the audited worktree"
        )

    def test_release_rejects_live_plan_reused_as_approved_snapshot(self) -> None:
        repo = self.new_repo()
        artifact = self.safe_zip()
        idea, plan = private_inputs(repo)
        arguments = release_arguments(repo, artifact=artifact)
        snapshot_index = arguments.index("--approved-plan-snapshot") + 1
        digest_index = arguments.index("--private-input-set-sha256") + 1
        arguments[snapshot_index] = plan
        arguments[digest_index] = private_input_set_digest([idea, plan])

        result = run_script(RELEASE_SCRIPT, *arguments)

        self.assertEqual(result.returncode, 2, combined_output(result))
        self.assertIn("approved plan snapshot must be separate", combined_output(result))

    def test_release_rejects_hardlink_alias_for_approved_plan_snapshot(self) -> None:
        repo = self.new_repo()
        artifact = self.safe_zip()
        _, plan = private_inputs(repo)
        approved = approved_plan_snapshot(repo)
        approved.unlink()
        try:
            os.link(plan, approved)
        except OSError as error:
            self.skipTest(f"hardlinks are unavailable: {error}")
        arguments = release_arguments(repo, artifact=artifact)

        result = run_script(RELEASE_SCRIPT, *arguments)

        self.assertEqual(result.returncode, 2, combined_output(result))
        self.assertIn("inventory contains aliased files", combined_output(result))

    def test_release_rejects_snapshot_with_different_plan_bytes(self) -> None:
        repo = self.new_repo()
        artifact = self.safe_zip()
        approved = approved_plan_snapshot(repo)
        approved.write_text("A different private plan revision.\n", encoding="utf-8")
        arguments = release_arguments(repo, artifact=artifact)

        result = run_script(RELEASE_SCRIPT, *arguments)

        self.assertEqual(result.returncode, 2, combined_output(result))
        self.assertIn(
            "live plan does not match the approved plan snapshot",
            combined_output(result),
        )

    def test_rejects_artifact_larger_than_approved_plan_limit(self) -> None:
        repo = self.new_repo()
        artifact = self.safe_zip()

        result = self.run_release(
            repo,
            artifact=artifact,
            max_artifact_bytes=artifact.stat().st_size - 1,
        )

        self.assert_failed_with(result, "artifact exceeds the approved maximum byte size")

    def test_rejects_nonempty_external_staging_directory(self) -> None:
        repo = self.new_repo()
        artifact = self.safe_zip()
        staging = self.root / "occupied-staging"
        staging.mkdir()
        (staging / "unrelated.txt").write_text("occupied\n", encoding="utf-8")

        result = self.run_release(
            repo,
            artifact=artifact,
            staging_directory=staging,
        )

        self.assert_failed_with(
            result, "artifact staging directory must be a new or empty plain directory"
        )

    def test_legal_bundle_member_read_is_bounded_by_public_artifact_size(self) -> None:
        repo = self.new_repo()
        artifact = self.artifact_path(suffix=".bin")
        artifact.write_bytes(b"safe compiled payload\n")

        result = self.run_nonarchive_release(
            repo,
            artifact,
            adapter_inspected=True,
            bundled_payload=artifact.read_bytes() + b"unexpected trailing byte",
        )

        self.assert_failed_with(
            result, "bundled artifact member size does not match approved bytes"
        )

    def test_rejects_symlink_artifact_path(self) -> None:
        repo = self.new_repo()
        real_artifact = self.safe_zip(self.artifact_path(stem="real-project"))
        linked_artifact = self.artifact_path(stem="linked-project")
        try:
            os.symlink(real_artifact, linked_artifact)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"symbolic links are unavailable: {error}")

        result = self.run_release(repo, artifact=linked_artifact)

        self.assert_failed_with(result, "artifact path is a symlink")

    def test_rejects_nonempty_git_grafts(self) -> None:
        repo = self.new_repo()
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

        result = self.run_release(repo, artifact=self.safe_zip())

        self.assertEqual(result.returncode, 2, combined_output(result))
        self.assertIn("grafts", combined_output(result).casefold())

    def test_rejects_assume_unchanged_index_entries(self) -> None:
        repo = self.new_repo()
        artifact = self.safe_zip()
        git(repo, "update-index", "--assume-unchanged", "README.md")

        result = self.run_release(repo, artifact=artifact)

        self.assertEqual(result.returncode, 2, combined_output(result))
        self.assertIn("assume-unchanged", combined_output(result))

    def test_clean_filter_cannot_hide_modified_worktree_content(self) -> None:
        repo = self.new_repo()
        artifact = self.safe_zip()
        canonical = "canonical filtered contents\n"
        execution_marker = self.root / "clean-filter-executed.txt"
        write_text(repo, ".gitattributes", "filtered.txt filter=mask\n")
        write_text(
            repo,
            "tools/mask_filter.py",
            "from pathlib import Path\n"
            "import sys\n"
            "sys.stdin.buffer.read()\n"
            f"Path({str(execution_marker)!r}).write_text('executed\\n', encoding='utf-8')\n"
            f"sys.stdout.buffer.write({canonical.encode()!r})\n",
        )
        write_text(repo, "filtered.txt", canonical)
        git(
            repo,
            "config",
            "filter.mask.clean",
            f'"{Path(sys.executable).as_posix()}" tools/mask_filter.py',
        )
        commit_all(repo, "test: configure a content-masking clean filter")
        filtered_path = write_text(repo, "filtered.txt", "modified filtered contents!\n")
        metadata = filtered_path.stat()
        os.utime(
            filtered_path,
            ns=(metadata.st_atime_ns, metadata.st_mtime_ns + 2_000_000_000),
        )
        self.assertNotEqual(filtered_path.read_text(encoding="utf-8"), canonical)
        masked_status = git(
            repo,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        )
        self.assertEqual("", masked_status.stdout, combined_output(masked_status))
        self.assertTrue(execution_marker.is_file(), "fixture clean filter did not execute")
        execution_marker.unlink()

        result = self.run_release(repo, artifact=artifact)

        self.assertFalse(
            execution_marker.exists(),
            "release audit executed a repository clean filter",
        )
        self.assertEqual(result.returncode, 2, combined_output(result))
        self.assertIn(
            "repository-local Git config contains includes or execution-capable settings",
            combined_output(result),
        )


if __name__ == "__main__":
    unittest.main()
