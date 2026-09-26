"""Validate the preserved module and its actual helper behavior."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "modules/project-bullets"


class BundleTests(unittest.TestCase):
    def test_preserved_module_hashes(self) -> None:
        manifest = json.loads((MODULE / "UPSTREAM.json").read_text(encoding="utf-8"))
        for name, source in manifest["files"].items():
            with self.subTest(name=name):
                self.assertEqual(
                    hashlib.sha256((MODULE / name).read_bytes()).hexdigest(), source["sha256"]
                )
        self.assertEqual(manifest["files"]["WORKFLOW.md"]["source"], "SKILL.md")

    def test_original_helper_suite(self) -> None:
        result = subprocess.run(
            [sys.executable, "-B", "-m", "unittest", "discover", "-s", "scripts/tests", "-v"],
            cwd=MODULE,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_local_document_links_resolve(self) -> None:
        for document in ROOT.rglob("*.md"):
            if document.parent == ROOT / "tests":
                continue
            for target in re.findall(r"\]\(([^)]+)\)", document.read_text(encoding="utf-8")):
                if "://" in target or target.startswith("#"):
                    continue
                path = (document.parent / target.split("#", 1)[0]).resolve()
                with self.subTest(document=document.name, target=target):
                    self.assertTrue(path.is_relative_to(ROOT))
                    self.assertTrue(path.is_file())

    def test_single_discoverable_skill(self) -> None:
        self.assertEqual(list(ROOT.rglob("SKILL.md")), [ROOT / "SKILL.md"])


if __name__ == "__main__":
    unittest.main()
