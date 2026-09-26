# Resume Helper

Keep a resume library and tailor it to each job with small, evidence-backed edits. Includes the original project-bullets workflow for developing stronger achievements.

## Use

Install the complete `resume-helper` folder in your agent's skill directory. The workspace helper needs Python 3.10+ with no extra packages. Resume rendering and project tests use the user's available tools.

| Task | Codex | Claude Code |
| --- | --- | --- |
| Choose folder and base | `$resume-helper setup` | `/resume-helper setup` |
| Match a pasted JD | `$resume-helper match-jd` | `/resume-helper match-jd` |
| Develop project bullets | `$resume-helper project-bullets /path/to/project --bullets 2` | `/resume-helper project-bullets /path/to/project --bullets 2` |

Natural language works too. In an active Resume Helper conversation, `/setup`, `/match-jd`, and `/project-bullets` are shorthand if your host passes them through. This package supplies one skill with three modes, not three registered native commands. Codex uses explicit `$skill` invocation; Claude Code uses `/skill-name` with arguments. See the [Codex](https://learn.chatgpt.com/docs/build-skills) and [Claude Code](https://code.claude.com/docs/en/skills) documentation.

Example:

```text
$resume-helper setup
Use /path/to/resumes and tex/Main.tex as my base. Keep three projects.
I also have two projects that are not on that resume.

$resume-helper match-jd
Suggest small changes for this JD. Preserve my metrics and categories.
[Paste the job description here.]

$resume-helper project-bullets /path/to/project --bullets 3 --role "backend engineer"
Use my saved resume template and keep evidence locally.
```

## What it remembers

Setup asks for the resume folder, base resume, extra projects, and missing preferences. It keeps sources in `tex/`, outputs in `pdf/`, and private working context in `.resume-helper/`. Existing files stay where they are unless you ask to reorganize them. A small user-local registry remembers the chosen folder across sessions.

Previous variants supply useful wording and project-selection lessons. Confirmed skills, accepted edits, rejected suggestions, and unresolved questions stay distinct. Your base supplies current personal facts; an older tailored version cannot silently replace it.

## What a JD match returns

1. Skills to add, reorder, or omit, with questions about unknown requirements.
2. Which projects to include and in what order, considering your full inventory.
3. Focused before/after bullet edits that retain mechanisms, metrics, and scope.
4. Any useful section changes and, when requested, a separate tailored source/PDF.

Suggestions are the default. "Make this resume" also authorizes creating a variant. Unknown skills remain questions until confirmed. The skill does not invent experience, promise ATS passage, submit applications, or publish personal files.

## Project bullets

The bundled module inspects implementation, runs relevant tests and fair local benchmarks, and writes two or three distinct achievements. It retains reproducible evidence, metric status, and layout checks. Its workflow and measurement/writing guidance are unchanged; [the integration manifest](modules/project-bullets/UPSTREAM.json) records hashes. The standalone install README and UI metadata are replaced by this package's entry point. Relative module paths resolve from `modules/project-bullets/`.

Ordinary JD wording edits do not trigger new benchmarks. Request `project-bullets` when you need new achievements or stronger evidence.

## Install

Copy the complete folder to a location discovered by your host, for example `~/.agents/skills/resume-helper/` for Codex or `~/.claude/skills/resume-helper/` for Claude Code. Existing Codex hosts may use `~/.codex/skills/`; use one discovered location. Reload the agent if needed. No API key is required by the skill itself.

## Maintain

From this folder:

```text
python -B -m unittest discover -s tests -v
python scripts/workspace.py --help
```

The tests exercise workspace persistence, stale-file detection, source preservation, path boundaries, and the unchanged project-bullets helpers. [Behavioral scenarios](tests/scenarios.md) cover agent decisions; passing helper tests is not an end-to-end agent evaluation.

Add a future mode with a focused reference and a row in the command table. Keep shared rules in `SKILL.md`, optional procedures in references, and personal data in the workspace. Preserve unknown profile fields; a schema change needs an explicit migration.

Apache-2.0 for Resume Helper. The bundled project-bullets module retains its MIT license. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
