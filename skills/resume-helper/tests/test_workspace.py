"""Exercise persistence and file boundaries with synthetic resume workspaces."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Callable, Iterator
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import workspace


class WorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.root = self.home / "Resume library"
        self.root.mkdir()
        self.base = self.root / "main.tex"
        self.base.write_text("Baseline: 12 ms on a local workload.", encoding="utf-8")
        self.environment = patch.dict(
            os.environ, {"RESUME_HELPER_HOME": str(self.home / "registry")}
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_setup_keeps_source_and_remembers_folder(self) -> None:
        before = self.base.read_bytes()
        workspace.initialize(self.root, "main.tex")
        self.assertEqual(self.base.read_bytes(), before)
        self.assertTrue((self.root / "tex").is_dir())
        self.assertTrue((self.root / "pdf").is_dir())
        self.assertEqual(workspace.locate(cwd=self.home), self.root.resolve())
        self.assertNotIn("12 ms", workspace.registry_path().read_text())

    def test_repeated_setup_preserves_user_memory_and_hash(self) -> None:
        workspace.initialize(self.root, "main.tex")
        path = self.root / workspace.STATE / "profile.json"
        profile = workspace.read_profile(self.root)
        original_hash = profile["baseline_sha256"]
        profile["skills"] = [{"name": "Jest", "status": "declined"}]
        profile["projects"] = [{"id": "parser", "ownership": "parser only"}]
        profile["preferences"]["project_slots"] = 4
        profile["future_extension"] = {"keep": True}
        workspace.write_json(path, profile)
        context = self.root / workspace.STATE / "context.md"
        context.write_text("Keep this user's rejected wording.", encoding="utf-8")
        self.base.write_text("Manually edited baseline", encoding="utf-8")
        workspace.initialize(self.root, "main.tex")
        actual = workspace.read_profile(self.root)
        self.assertEqual(actual, profile)
        self.assertEqual(actual["baseline_sha256"], original_hash)
        self.assertEqual(context.read_text(), "Keep this user's rejected wording.")

    def test_base_changes_require_explicit_replacement(self) -> None:
        workspace.initialize(self.root, "main.tex")
        other = self.root / "another.tex"
        other.write_text("Another resume", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "already selected"):
            workspace.initialize(self.root, "another.tex")
        workspace.initialize(self.root, "another.tex", replace_base=True)
        self.assertEqual(workspace.read_profile(self.root)["baseline"], "another.tex")

    def test_scan_detects_changes_and_missing_base_without_promoting_variant(self) -> None:
        workspace.initialize(self.root, "main.tex")
        first = workspace.scan(self.root)
        self.assertEqual(first["changed"], ["main.tex"])
        self.assertFalse(first["baseline_changed"])
        self.assertEqual(workspace.scan(self.root)["changed"], [])
        self.base.write_text("Changed metric with a different qualifier", encoding="utf-8")
        self.assertTrue(workspace.scan(self.root)["baseline_changed"])
        variant = self.root / "tex" / "a newer variant.tex"
        variant.write_text("Role-specific wording", encoding="utf-8")
        self.base.unlink()
        result = workspace.scan(self.root)
        self.assertTrue(result["baseline_missing"])
        self.assertIn("main.tex", result["removed"])
        self.assertEqual(workspace.read_profile(self.root)["baseline"], "main.tex")

    def test_inventory_is_recursive_and_skips_private_build_files(self) -> None:
        workspace.initialize(self.root, "main.tex")
        nested = self.root / "tex" / "old"
        nested.mkdir()
        (nested / "previous.TEX").write_text("Prior wording", encoding="utf-8")
        (self.root / "pdf" / "previous.pdf").write_bytes(b"synthetic PDF fixture")
        (self.root / workspace.STATE / "scratch.tex").write_text("scratch", encoding="utf-8")
        files = workspace.scan(self.root)["files"]
        self.assertEqual(
            [item["path"] for item in files],
            ["main.tex", "pdf/previous.pdf", "tex/old/previous.TEX"],
        )

    def test_current_workspace_takes_priority_over_registry(self) -> None:
        workspace.initialize(self.root, "main.tex")
        other = self.home / "other"
        workspace.initialize(other)
        self.assertEqual(workspace.locate(cwd=self.root / "tex"), self.root.resolve())
        self.assertEqual(workspace.locate(str(other), cwd=self.root), other.resolve())

    def test_missing_remembered_folder_does_not_fall_back(self) -> None:
        workspace.initialize(self.root, "main.tex")
        self.root.rename(self.home / "moved")
        with self.assertRaisesRegex(ValueError, "missing"):
            workspace.locate(cwd=self.home)

    def test_reject_external_baseline_and_preserve_external_file(self) -> None:
        other = self.home / "outside.tex"
        other.write_text("Private outside file", encoding="utf-8")
        for supplied in (str(other), "../outside.tex"):
            with self.subTest(supplied=supplied):
                with self.assertRaisesRegex(ValueError, "inside"):
                    workspace.initialize(self.root, supplied)
        self.assertEqual(other.read_text(), "Private outside file")
        self.assertFalse((self.root / workspace.STATE).exists())

    def test_incomplete_and_pdf_only_setup(self) -> None:
        workspace.initialize(self.root)
        self.assertIsNone(workspace.scan(self.root)["baseline"])
        pdf = self.root / "base.pdf"
        pdf.write_bytes(b"synthetic PDF fixture")
        workspace.initialize(self.root, "base.pdf")
        self.assertEqual(workspace.read_profile(self.root)["baseline"], "base.pdf")

    def test_corrupt_and_future_state_are_not_reset(self) -> None:
        workspace.initialize(self.root, "main.tex")
        path = self.root / workspace.STATE / "profile.json"
        for value in ('{"schema_version": 99}', '{"broken":'):
            path.write_text(value, encoding="utf-8")
            with self.assertRaises(ValueError):
                workspace.initialize(self.root)
            self.assertEqual(path.read_text(), value)

    def test_corrupt_registry_does_not_create_profile(self) -> None:
        path = workspace.registry_path()
        path.parent.mkdir(parents=True)
        path.write_text('{"schema_version": 1, "roots": "bad"}', encoding="utf-8")
        with self.assertRaises(ValueError):
            workspace.initialize(self.root, "main.tex")
        self.assertFalse((self.root / workspace.STATE).exists())

    def test_symlink_escape_is_rejected(self) -> None:
        outside = self.home / "outside"
        outside.mkdir()
        try:
            (self.root / workspace.STATE).symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("Symlink creation is unavailable on this host")
        with self.assertRaises(ValueError):
            workspace.initialize(self.root, "main.tex")
        self.assertEqual(list(outside.iterdir()), [])

    def test_failed_read_preserves_previous_snapshot(self) -> None:
        workspace.initialize(self.root, "main.tex")
        workspace.scan(self.root)
        inventory = self.root / workspace.STATE / "inventory.json"
        before = inventory.read_bytes()
        with patch.object(workspace, "digest", side_effect=PermissionError("Denied")):
            result = workspace.scan(self.root)
        self.assertTrue(result["errors"])
        self.assertEqual(inventory.read_bytes(), before)

    def test_unreadable_directory_preserves_previous_snapshot(self) -> None:
        workspace.initialize(self.root, "main.tex")
        workspace.scan(self.root)
        inventory = self.root / workspace.STATE / "inventory.json"
        before = inventory.read_bytes()

        def denied_walk(
            root: Path, *, followlinks: bool, onerror: Callable[[OSError], None]
        ) -> Iterator[tuple[str, list[str], list[str]]]:
            onerror(PermissionError(13, "Denied", str(root / "tex")))
            return iter(())

        with patch("workspace.os.walk", side_effect=denied_walk):
            result = workspace.scan(self.root)
        self.assertTrue(result["errors"])
        self.assertEqual(inventory.read_bytes(), before)

    def test_invalid_profile_shape_is_preserved(self) -> None:
        workspace.initialize(self.root, "main.tex")
        profile = workspace.read_profile(self.root)
        del profile["baseline"]
        path = self.root / workspace.STATE / "profile.json"
        workspace.write_json(path, profile)
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, "baseline fields"):
            workspace.initialize(self.root)
        self.assertEqual(path.read_bytes(), before)

    def test_cli_roundtrip_and_controlled_failure(self) -> None:
        script = Path(workspace.__file__)
        init = subprocess.run(
            [
                sys.executable,
                "-B",
                str(script),
                "init",
                "--root",
                str(self.root),
                "--base",
                "main.tex",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(json.loads(init.stdout)["profile"]["baseline"], "main.tex")
        located = subprocess.run(
            [sys.executable, "-B", str(script), "locate"],
            cwd=self.home,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(json.loads(located.stdout)["root"], str(self.root.resolve()))
        failed = subprocess.run(
            [sys.executable, "-B", str(script), "scan", "--root", str(self.home / "absent")],
            capture_output=True,
            text=True,
        )
        self.assertEqual(failed.returncode, 2)
        self.assertNotIn("Traceback", failed.stderr)


if __name__ == "__main__":
    unittest.main()
