# Workspace memory

Keep personal state in the chosen resume workspace, never in the reusable skill or public repository. The registry only remembers selected roots. Avoid unrelated filesystem scans. These files are ordinary editable local files, not a private cloud service.

## `profile.json` (schema version 1)

The helper creates the structure; the agent maintains the semantic records while preserving unknown fields and user edits:

| Field | Meaning |
| --- | --- |
| `schema_version` | `1`; do not silently reset an unsupported version. |
| `baseline` / `baseline_sha256` | Workspace-relative base path and hash when selected. Null during incomplete setup. |
| `preferences` | Project slots (initially 3), suggest/apply mode, inferred skill categories, section order, and optional page target. User choices override defaults. |
| `projects` | All known projects, not just the selected three; records described below. |
| `skills` | Confirmed knowledge, evidence, and unresolved/declined terms; records described below. |

A project record should include `id`, `name`, `summary`, `ownership`, `path` or `repository_url`, `capabilities`, `evidence`, and `bullet_candidates`. Keep IDs stable. Each candidate stores `text`, `source` (resume/run/file), `status` (proposed/accepted/rejected), `role_fit`, `qualifiers`, and optional `evidence_path`. A saved accepted phrase is reusable only if still factually applicable.

A skill record should include `name`, `level` (hands-on/coursework/familiarity/none/unknown), `status` (confirmed/supported/needs-confirmation/declined), `source`, `scope` (which JD or explicit confirmation), and `confirmed_on` when known. Store the user's clarification faithfully. A generated resume or suggestion is not independent evidence of knowledge. Application-specific omissions never remove a skill from this general inventory.

## `context.md`

Keep this short: confirmed style preferences, useful role-selection heuristics, current decisions, unresolved facts, and links to relevant runs. Record the reason and source, not every turn. Example: "For backend roles, prefer the recovery project over the demo-only UI because the applicant owns its core implementation." Do not encode one user's favorite projects as a global rule for other users.

## `inventory.json`

`scan` indexes all `.tex` and `.pdf` files beneath the selected root, skipping state/cache directories and symlinked paths. Each entry has a relative path, size, mtime, and SHA-256. It reports changed and removed paths since the previous scan and whether the selected baseline changed or disappeared. It does not parse arbitrary TeX/PDF or validate claims.

Read newly changed relevant content before reusing it. If the baseline changed, reconcile it with saved records and report material conflicts; update its saved hash only after reviewing the change. A missing base needs a new user selection, not an automatic fallback to a tailored resume. If folders move, re-register the user-selected location; do not search the entire disk for personal files.

## Per-application runs

Use `.resume-helper/runs/<date-company-role-id>/` with a collision-safe suffix. Keep `jd.txt`, `changes.md`, and optional evidence/build files together. In `changes.md`, record base path/hash, relevant historical sources, skills proposed/confirmed/omitted, project selection/order and reasons, original/proposed bullets, user decisions, outputs, and validation status. A suggested change remains proposed until accepted or applied under an existing instruction. Rejected wording stays rejected unless the user revisits it.

On later matches, search these compact records and relevant resume text for useful wording. Reuse the mechanism and qualifiers, not another job's unsupported keywords. Never copy one candidate's facts into another person's workspace. Publish only the generic skill package; personal profiles, JDs, evidence, and resume files are not release assets.
