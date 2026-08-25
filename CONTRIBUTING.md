# Contributing

Thank you for improving these skills. Contributions should make a workflow more correct, more usable, or easier to verify.

## Before opening a pull request

1. Open or find an issue describing the observed problem.
2. Keep the change focused on one concern.
3. Add or update a regression test when behavior changes.
4. Run `python tools/check.py` from the repository root.
5. Review the staged diff for private inputs, credentials, local paths, placeholders, and unsupported claims.

Do not commit `idea.md`, `plan.md`, approved-plan snapshots, private fixtures, credentials, generated caches, or output copied from a private project.

## Adding a skill

Create `skills/<skill-name>/SKILL.md`. The frontmatter name must match the directory name. Add only the references, scripts, assets, and tests the skill actually needs.

A new skill must include:

- a narrow description with positive and negative activation boundaries;
- a usable workflow, not a collection of aspirations;
- explicit privacy, credential, and external-action boundaries;
- validation proportional to the risk of its work;
- a catalogue entry in the root README;
- a changelog entry.

## Commit and pull request style

Use concise conventional commits such as `feat:`, `fix:`, `docs:`, `test:`, `ci:`, and `chore:`. Keep each commit reviewable. Pull requests should explain the user-visible outcome, validation performed, and any remaining limitation.

By contributing, you agree that your contribution is licensed under Apache License 2.0.
