# Set up a workspace

Use existing context before asking questions. Group the remaining questions:

1. Which folder should hold the resumes? Which existing resume is the base?
2. Are there other projects not shown? Request names, short descriptions, contribution/ownership, and optional local paths or repository links. Ask how many projects should fit; suggest three only when no preference exists.
3. Infer format, typography, categories, and section order from the baseline. Ask only about unresolved preferences such as page target, protected wording, or whether future matches should remain suggestions or also create variants.

Do not ask for every project detail before analyzing a supplied JD. Record unknowns and return to them when they affect selection. If the user has already described their inventory, ask only whether there are additions.

## Select the base

- Inspect the named folder. If a path is missing, check obvious nearby filename variants and report what was found. Ask if multiple candidates remain; never silently use an unrelated file.
- A specifically named base takes priority. Otherwise suggest an obvious main/general resume. If multiple resumes could be the base, ask; do not select by modification time alone.
- Review all resume names and available text on first setup to identify projects, useful alternate bullets, and role variants. Deduplicate identical contents. For a large collection, inventory everything and progressively read changed or relevant entries rather than filling context with every document.
- Ask about contradictory personal facts, dates, or metrics instead of merging them. Keep the latest explicit user correction authoritative. Store older wording as a candidate with provenance and original qualifiers.
- If no resume exists, ask for an existing file or the essential content and format. Do not invent a starter identity, employment history, or achievements. A PDF-only base can support suggestions; editable source is needed to preserve its exact LaTeX layout. Reconstructed source must be labeled as reconstructed and reviewed.

## Folder layout

```text
resume-workspace/
  tex/                       Base and application-specific LaTeX sources
  pdf/                       Matching compiled PDFs
  .resume-helper/
    profile.json             Base selection, preferences, skills, project inventory
    context.md               Concise decisions and reusable heuristics
    inventory.json           Paths, content hashes, and changed/missing files
    runs/<application-id>/   JD, suggestions, decisions, evidence, build files
```

Reuse existing `tex/` and `pdf/` folders. Do not reorganize or delete existing files automatically. A base already elsewhere inside the workspace can remain there. If the user selects an external base, copy it and required local TeX assets/includes into the chosen workspace without overwriting files; retain the original. Inspect references rather than treating a TeX source as a self-contained file by default.

From the installed skill directory:

```text
python scripts/workspace.py init --root /path/to/resumes --base tex/Main.tex
python scripts/workspace.py scan --root /path/to/resumes
```

`--base` may name a `.tex` or `.pdf` inside the workspace. Omit it only for an unfinished setup. Re-running `init` preserves saved preferences, projects, skills, context, and the chosen base. Changing the base explicitly requires `--replace-base`; use it only when the user has selected a replacement. Relative paths resolve from the resume root, not the shell directory.

The helper remembers the selected folder in `~/.config/resume-helper/workspaces.json`; `RESUME_HELPER_HOME` can select a different registry directory. It never stores resume contents there. Read/write permissions still come from the host.

Finish by reporting the folder, chosen base, project count/inventory, and unresolved inputs. Save only confirmed preferences and clearly attributed observations. Do not convert an unaccepted suggestion into a permanent preference.
