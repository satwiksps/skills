<div align="center">
  <img src="assets/banner.svg" alt="Skills: tested workflows for Codex" width="100%">
  <h1>skills</h1>
  <p><strong>Production-grade Codex skills. I cook them; you steal them.</strong></p>
  <p>
    <a href="https://github.com/satwiksps/skills/actions/workflows/ci.yml"><img src="https://github.com/satwiksps/skills/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache--2.0-7c3aed.svg" alt="Apache-2.0"></a>
    <a href="https://github.com/satwiksps/skills/releases"><img src="https://img.shields.io/github/v/release/satwiksps/skills?display_name=tag&sort=semver" alt="Latest release"></a>
  </p>
</div>

This is my public collection of focused, tested workflows for Codex. Each skill is a self-contained directory with clear activation rules, supporting references, and validation appropriate to the work it performs.

The goal is not to collect prompts. The goal is to make difficult work repeatable.

## Available skills

| Skill | What it does | Status |
| --- | --- | --- |
| [`build-open-source-software`](skills/build-open-source-software) | Turns a private `idea.md` into an approved plan, working software, documentation, a verified `v0.1.0` release, and PR-only repository governance. | `v0.1.0` |

More skills will be added only when they solve a real workflow and include evidence that they work.

## Install a skill

Ask Codex:

```text
Use $skill-installer to install the build-open-source-software skill from https://github.com/satwiksps/skills/tree/main/skills/build-open-source-software
```

The skill becomes available on the next turn. Invoke it with:

```text
Use $build-open-source-software with C:\path\to\idea.md
```

Manual installation through Codex's bundled installer is also available:

```console
python ~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo satwiksps/skills \
  --path skills/build-open-source-software
```

On Windows PowerShell, use `py` and the corresponding path under `$env:USERPROFILE\.codex\skills`.

## Why trust these skills?

The first skill includes a suite of 90 unit and adversarial tests for its deterministic audit tooling. Its checks cover private planning data, transformed content, Git history, authored prose, archive structure, release metadata, legal files, artifact staging, signing contracts, and clean-checkout behavior.

Every skill in this repository must:

- state exactly when it should and should not run;
- keep private inputs and credentials outside public state;
- distinguish verified behavior from claims;
- include a concrete validation path;
- avoid placeholders, fabricated proof, and hidden manual steps;
- document its limitations honestly.

Codex is the tested target. Compatibility with other agents is not claimed until it has been exercised there.

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
