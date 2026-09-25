"""Behavioral tests use only fictional employers and temporary private workspaces."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import tracker


def job(**changes: Any) -> dict[str, Any]:
    item: dict[str, Any] = dict(
        kind="jobs",
        company="Example",
        role="Backend Engineer / 123",
        url="https://example.com/jobs/123",
        exact_link=True,
        score={"skills": 30, "experience": 25, "duties": 18, "eligibility": 10},
        evidence="Employer full JD observed",
        fit="Python and SQL",
        eligibility="Student joining uncertain",
        pay_company="Pay unknown; profile allows it",
    )
    item.update(changes)
    return item


class TrackerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        tracker.setup(self.root, "none")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def add(self, *items: dict[str, Any], discovery: str = "2026-09-25 09:30") -> dict[str, int]:
        return tracker.apply(self.root, {"discovery": discovery, "add": list(items)})

    def text(self, kind: str = "jobs") -> str:
        return (self.root / f"{kind}.md").read_text(encoding="utf-8")

    def status(self, state: str, evidence_kind: str, **extra: Any) -> dict[str, int]:
        change = dict(
            url="https://example.com/jobs/123",
            state=state,
            evidence=dict(
                kind=evidence_kind,
                url="https://example.com/jobs/123",
                observed_at="2026-09-25T10:00:00+05:30",
                reason="Explicit employer notice",
            ),
        )
        change.update(extra)
        return tracker.apply(self.root, {"status": [change]})

    def test_setup_preserves_profile_lists_and_command_conflicts(self) -> None:
        (self.root / "me.md").write_text("My custom preferences", encoding="utf-8")
        self.add(job())
        path = self.root / ".agents/skills/scrap/SKILL.md"
        path.parent.mkdir(parents=True)
        path.write_text("Unrelated skill", encoding="utf-8")
        before = self.text()
        result = tracker.setup(self.root, "both")
        self.assertEqual((self.root / "me.md").read_text(), "My custom preferences")
        self.assertEqual(path.read_text(), "Unrelated skill")
        self.assertEqual(len(result["preserved_command_conflicts"]), 1)
        self.assertEqual(self.text(), before)
        self.assertTrue((self.root / ".claude/skills/scrap/SKILL.md").exists())

    def test_idempotent_aliases_and_tracking_parameters(self) -> None:
        self.add(job(aliases=["https://board.example/123"]))
        result = self.add(
            job(url="https://board.example/123?utm_source=alert", role="Mirrored title")
        )
        self.assertEqual(result["duplicates"], 1)
        self.assertEqual(len(tracker.rows(self.text())), 1)

    def test_generic_portal_does_not_collapse_distinct_roles(self) -> None:
        common = dict(
            url="https://example.com/careers",
            exact_link=False,
            link_label="Career portal - exact role unverified",
        )
        result = self.add(job(**common), job(role="SRE / 456", **common))
        self.assertEqual(result["new_jobs"], 2)

    def test_distinct_requisitions_and_internship_classification(self) -> None:
        result = self.add(
            job(),
            job(role="Backend Engineer / 124", url="https://example.com/jobs/124"),
            job(kind="internships", role="Intern / 9", url="https://example.com/jobs/9"),
        )
        self.assertEqual(result["new_jobs"], 2)
        self.assertEqual(result["new_internships"], 1)

    def test_newest_sections_and_preserved_notes(self) -> None:
        self.add(job(), discovery="2026-09-24 12:00")
        path = self.root / "jobs.md"
        path.write_text(
            self.text().replace("[ ]", "[x]") + "\nMy private note.\n", encoding="utf-8"
        )
        self.add(job(role="SRE / 2", url="https://example.com/jobs/2"))
        self.add(job(role="SRE / 3", url="https://example.com/jobs/3"))
        self.assertEqual(
            tracker.DATE.findall(self.text()), ["2026-09-25 09:30", "2026-09-24 12:00"]
        )
        self.assertIn("| [x] |", self.text())
        self.assertIn("My private note.", self.text())
        self.assertEqual(tracker.check(self.root)["jobs"], 3)

    def test_closed_all_cells_reopened_preserves_applied_and_date(self) -> None:
        self.add(job())
        path = self.root / "jobs.md"
        path.write_text(self.text().replace("[ ]", "[x]"), encoding="utf-8")
        before = self.text()
        self.assertEqual(self.status("closed", "employer_closed_notice")["closed"], 1)
        cells = tracker.rows(self.text())[0][1]
        self.assertTrue(all(c.startswith("~~") and c.endswith("~~") for c in cells))
        self.assertEqual(cells[0], "~~[x]~~")
        self.assertEqual(self.status("closed", "employer_closed_notice")["closed"], 0)
        self.assertEqual(self.status("open", "employer_accepting_applications")["reopened"], 1)
        self.assertEqual(self.text(), before)

    def test_access_error_is_not_closure_and_uncertainty_keeps_row(self) -> None:
        self.add(job())
        before = self.text()
        with self.assertRaises(ValueError):
            self.status("closed", "http_404")
        self.status("uncertain", "http_404")
        self.assertEqual(self.text(), before)

    def test_invalid_batch_does_not_partially_write(self) -> None:
        before = self.text()
        with self.assertRaises(ValueError):
            self.add(job(), job(role="Other", url="https://example.com/other", exact_link=False))
        self.assertEqual(self.text(), before)
        self.assertFalse((self.root / ".job-tracker/write.lock").exists())

    def test_unknown_profile_can_be_unscored_and_markdown_is_escaped(self) -> None:
        self.add(job(company="Example | Partners", role="ML [Engineer] ~test~ / 123", score=None))
        cells = tracker.rows(self.text())[0][1]
        self.assertEqual(cells[1], "Unscored*")
        self.assertIn("&#124;", cells[2])
        self.assertIn("\\[Engineer\\]", cells[3])

    def test_alert_score_cap_and_invalid_component(self) -> None:
        with self.assertRaises(ValueError):
            self.add(job(evidence_level="alert_only"))
        bad = copy.deepcopy(job())
        bad["score"]["skills"] = 36
        with self.assertRaises(ValueError):
            self.add(bad)

    def test_existing_malformed_manual_edit_is_not_overwritten(self) -> None:
        path = self.root / "jobs.md"
        path.write_text("| [x] | broken | row |\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.add(job())
        self.assertEqual(self.text(), "| [x] | broken | row |\n")

    def test_lock_prevents_overlapping_writer(self) -> None:
        lock = self.root / ".job-tracker/write.lock"
        lock.write_text("other writer", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            self.add(job())
        self.assertTrue(lock.exists())

    def test_audit_and_backup_are_local_and_complete(self) -> None:
        self.add(job())
        self.status("closed", "employer_closed_notice")
        events = list((self.root / ".job-tracker/events").glob("*.json"))
        self.assertEqual(len(events), 2)
        self.assertTrue(all(json.loads(p.read_text())["complete"] for p in events))
        self.assertEqual(len(list((self.root / ".job-tracker/backups").glob("*/jobs.md"))), 2)
        self.assertEqual(tracker.check(self.root)["incomplete_writes"], [])


if __name__ == "__main__":
    unittest.main()
