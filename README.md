# skills

<div align="center">
  <img src="assets/banner.svg" alt="One skill format for Claude, Codex, and Antigravity" width="100%">
  <p>
    <a href="https://github.com/satwiksps/skills/actions/workflows/ci.yml"><img src="https://github.com/satwiksps/skills/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-7c3aed.svg" alt="Apache-2.0"></a>
    <a href="https://github.com/satwiksps/skills/releases"><img src="https://img.shields.io/github/v/release/satwiksps/skills?display_name=tag&sort=semver" alt="Latest release"></a>
  </p>
</div>

Reusable agent skills for Claude Code, Codex, and Antigravity. Each skill is a self-contained `SKILL.md` package with focused activation rules, supporting resources, and validation appropriate to the work it performs.

The goal is not to collect prompts. The goal is to make difficult work repeatable.

## Available skills

| Skill | What it does | Status |
| --- | --- | --- |
| [`build-open-source-software`](skills/build-open-source-software) | Turns a private `idea.md` into an approved plan, working software, documentation, a verified `v0.1.0` release, and PR-only repository governance. | `v0.1.0` |

More skills will be added only when they solve a real workflow and include evidence that they work.

## Install a skill

These skills use the portable Agent Skills layout. Install a skill directory in the location used by your agent:

| Agent | Personal or global location | Invocation |
| --- | --- | --- |
| Claude Code | `~/.claude/skills/<skill-name>/` | `/skill-name` |
| Codex | `~/.agents/skills/<skill-name>/` | `$skill-name` |
| Antigravity | `~/.gemini/config/skills/<skill-name>/` | Mention the skill by name or let Antigravity discover it |

Claude Code also supports project skills in `.claude/skills/`. Codex and Antigravity support repository or workspace skills in `.agents/skills/`.

### Install directly with Codex

Ask Codex to install the latest version:

```text
Use $skill-installer to install the build-open-source-software skill from https://github.com/satwiksps/skills/tree/main/skills/build-open-source-software
```

For a reproducible install, replace `main` with a release tag such as `v0.1.0`.

### Install manually with any supported agent

Clone the collection, then copy the skill directory you want into the appropriate location above:

```console
git clone --depth 1 https://github.com/satwiksps/skills.git satwiksps-skills
```

The commands below install `build-open-source-software`. Run the pair for your agent.

macOS and Linux:

```sh
# Claude Code
mkdir -p ~/.claude/skills
cp -R satwiksps-skills/skills/build-open-source-software ~/.claude/skills/

# Codex
mkdir -p ~/.agents/skills
cp -R satwiksps-skills/skills/build-open-source-software ~/.agents/skills/

# Antigravity
mkdir -p ~/.gemini/config/skills
cp -R satwiksps-skills/skills/build-open-source-software ~/.gemini/config/skills/
```

Windows PowerShell:

```powershell
# Claude Code
New-Item -ItemType Directory -Force "$env:USERPROFILE\.claude\skills" | Out-Null
Copy-Item ".\satwiksps-skills\skills\build-open-source-software" "$env:USERPROFILE\.claude\skills" -Recurse

# Codex
New-Item -ItemType Directory -Force "$env:USERPROFILE\.agents\skills" | Out-Null
Copy-Item ".\satwiksps-skills\skills\build-open-source-software" "$env:USERPROFILE\.agents\skills" -Recurse

# Antigravity
New-Item -ItemType Directory -Force "$env:USERPROFILE\.gemini\config\skills" | Out-Null
Copy-Item ".\satwiksps-skills\skills\build-open-source-software" "$env:USERPROFILE\.gemini\config\skills" -Recurse
```

### Invoke the skill

Use the form supported by your agent:

```text
Claude Code: /build-open-source-software /path/to/idea.md
Codex: Use $build-open-source-software with /path/to/idea.md
Antigravity: Use the build-open-source-software skill with /path/to/idea.md
```

The shared skill format works across all three agents. Host tools, permissions, and invocation behavior can differ.

## Why trust these skills?

The first skill includes a suite of 90 unit and adversarial tests for its deterministic audit tooling. Its checks cover private planning data, transformed content, Git history, authored prose, archive structure, release metadata, legal files, artifact staging, signing contracts, and clean-checkout behavior.

These tests validate the bundled deterministic tooling and repository package. They are not a host-level end-to-end test matrix for every agent UI.

Every skill in this repository must:

- state exactly when it should and should not run;
- keep private inputs and credentials outside public state;
- distinguish verified behavior from claims;
- include a concrete validation path;
- avoid placeholders, fabricated proof, and hidden manual steps;
- document its limitations honestly.

## Repository layout

```text
skills/
`-- <skill-name>/
    |-- SKILL.md
    |-- agents/
    |-- assets/
    |-- references/
    |-- scripts/
    `-- tests/
```

Not every skill needs every optional directory. Every skill does need a valid `SKILL.md` and enough evidence for its risk level.

## Contributing

Bug reports, focused improvements, and real usage reports are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) before proposing a change. If a skill helped you ship something public, use the project showcase issue form so the repository can link only to real work.

Security reports belong in GitHub's private vulnerability reporting flow, not in public issues. See [SECURITY.md](SECURITY.md).

## License

Apache License 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
