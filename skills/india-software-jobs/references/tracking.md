# Files, matching and helpers

## Workspace files

- `me.md`: editable local profile, initialized from the asset. Optional placeholders are intentional template fields, never user facts.
- `source.md`: public source registry, Telegram first; active sources, unresolved companies and retired sources separated. The bundled seed is a starting list, not verified access on another installation.
- `jobs.md`, `internships.md`: five-column tables grouped by immutable discovery time, latest section first. Only populate requested types; do not move an existing entry when rediscovered.
- `.job-tracker/`: private evidence, run checklists, decisions, URL aliases, backups and continuation state. Keep fetched/reviewed/pagination completion separate. Never publish this folder or a filled profile/resume with the skill.

For each scan save `runs/<timestamp>/coverage.json` with every source's name, URL, scope, attempted time, transport, fetched state, pagination cursor/completeness, reviewed state and error/next action. Save decisions keyed by employer plus requisition ID (or canonical URL and role if no ID), including aliases, evidence URLs, eligibility, compensation units, company-quality reasoning and score components. Record exclusions and unresolved leads as well as additions. A new posting or changed ID is not automatically a duplicate.

Use minimal necessary local evidence, not a republished channel archive. Credentials and API sessions belong in the host's secure store outside the tracker. A `.gitignore` prevents accidental new tracking but does not untrack files already committed; inspect Git state before any publication. Do not print private profile contents in public logs.

## Matching

Score known candidate facts against the full JD: skills 35, relevant professional/project/open-source experience 30, duties 20, eligibility 15. Use the profile/resume appropriate to the candidate; projects do not manufacture professional years. Save reasons and component values. A score is prioritization, not hiring probability. Exclude proven hard mismatches regardless of score.

Mark material uncertainty with `*`. Alert/title-only assessments are provisional and capped at 60; with insufficient candidate information use `Unscored*`, not an invented score. Compensation, brand and recency must not inflate match. Keep unspecified minimum pay/company preferences broad. If salary basis is unknown, ask and retain the uncertainty rather than silently assuming take-home or gross.

## List format

```markdown
## 2026-09-25 09:30 IST

| Applied | Match | Company | Role / ID | Apply link |
| --- | --- | --- | --- | --- |
| [ ] | 84/100* | Example employer | Backend Engineer / REQ-123 | [Apply](https://example.com/jobs/REQ-123) |
```

Use real evidence-backed values, never copy the example as a discovery. A fallback link's label must say that the exact link/role is unverified, for each affected row. Preserve unchecked/checked Applied values; only user confirmation changes them. Do not add a README discovery log. When no new rows qualify, report zero rather than a dummy table. Confirmed closure keeps the original row and date, rendering e.g. `~~[x]~~`, `~~84/100*~~`, `~~Example employer~~`, `~~Backend Engineer / REQ-123~~`, `~~[Apply](...)~~` in the five cells.

## Bundled helper

Python 3.11+; standard library only. Paths below are placeholders for the actual installed skill and chosen workspace. Run one writer at a time. The helper does no network fetching, resume parsing or automatic job decisions; the agent performs research with available host tools.

```sh
python <skill>/scripts/tracker.py setup --root <workspace> --host codex
python <skill>/scripts/tracker.py apply --root <workspace> --input <reviewed-decisions.json>
python <skill>/scripts/tracker.py check --root <workspace>
```

Setup preserves existing files. Choose `claude`, `both` or `none` for other host needs. It creates workspace skill wrappers under `.agents/skills/` or `.claude/skills/`. Codex can explicitly invoke `$scrap`; Claude Code can invoke `/scrap`. Bare mode text is also understood once the main skill is active, but custom slash-menu availability depends on the host. Use `$india-software-jobs /scrap` or “Use india-software-jobs to scrap jobs” if a shortcut is unavailable. For Antigravity use the main skill in natural language. Restart/refresh skill discovery if required by the host. Move/reinstall the main skill only after updating wrapper references; setup reports conflicting wrappers rather than replacing them.

The apply helper requires agent-reviewed JSON:

```json
{
  "discovery": "2026-09-25 09:30",
  "add": [{
    "kind": "jobs",
    "company": "Example employer",
    "role": "Backend Engineer / REQ-123",
    "url": "https://example.com/jobs/REQ-123",
    "aliases": [],
    "exact_link": true,
    "link_label": "Apply",
    "score": {"skills": 30, "experience": 26, "duties": 18, "eligibility": 10},
    "provisional": true,
    "evidence_level": "full_jd",
    "evidence": "Employer URL and observed time; requirements summary",
    "fit": "Specific supported candidate overlaps and gaps",
    "eligibility": "Required versus preferred; unresolved joining date",
    "pay_company": "Actual amount, period and basis, or unknown; profile rule applied"
  }],
  "status": []
}
```

Use `score: null` for unscored roles. Use `exact_link: false` with an unverified label for fallback sources. Normalize employer/role/requisition identity and supply all known aliases before merging. Generic career/source URLs may represent several different roles and must not collapse them. Preserve records when profile preferences change; don't remove jobs during repair.

Availability changes take this form:

```json
{
  "status": [{
    "url": "https://example.com/jobs/REQ-123",
    "company": "Example employer",
    "role": "Backend Engineer / REQ-123",
    "state": "closed",
    "evidence": {
      "kind": "employer_closed_notice",
      "url": "https://example.com/jobs/REQ-123",
      "observed_at": "2026-09-25T10:00:00+05:30",
      "reason": "Exact requisition explicitly says it no longer accepts applications"
    }
  }]
}
```

Allowed states: `closed`, `open`, `uncertain`. Affirmative evidence kinds: `employer_closed_notice`, `employer_deadline_confirmed`, `employer_accepting_applications`. For uncertain observations use a descriptive kind such as `access_error`. Include company/role to disambiguate shared fallback URLs. Helpers validate structure, not truth; the agent must actually establish evidence. They preserve manual text and checked Applied marks, back up changed lists and write an audit event before mutation. An interrupted multi-file write leaves an incomplete event: reconcile its backup/request against current rows and retry idempotently; never silently mark it complete. Investigate a stale `write.lock` and ensure its process is gone before removing it.

After updates run `check`, inspect the touched rows, reconcile counts and audit missing evidence. It is a structural check, not proof that the scan covered all sources or that jobs are open.
