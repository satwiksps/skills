# build-open-source-software

**Turn a private idea into tested, documented, release-ready open-source software.**

This Agent Skill guides a new project from `idea.md` through an approved private plan, implementation, documentation, ecosystem-native packaging, a verified `v0.1.0` release, and pull-request-only governance. Its shared `SKILL.md` format is supported by Claude Code, Codex, and Antigravity.

## Install

Install this directory in the location used by your agent:

| Agent | Personal or global location | Invocation |
| --- | --- | --- |
| Claude Code | `~/.claude/skills/build-open-source-software/` | `/build-open-source-software` |
| Codex | `~/.agents/skills/build-open-source-software/` | `$build-open-source-software` |
| Antigravity | `~/.gemini/config/skills/build-open-source-software/` | Mention `build-open-source-software` |

Claude Code also supports `.claude/skills/` for project-level installation. Codex and Antigravity support `.agents/skills/` for repository or workspace installation. See the repository's [complete installation guide](../../README.md#install-a-skill) for macOS, Linux, and Windows copy commands.

Codex users can install directly by asking Codex:

```text
Use $skill-installer to install the skill from https://github.com/satwiksps/skills/tree/main/skills/build-open-source-software
```

For a reproducible install, replace `main` with a release tag such as `v0.1.0`.

Invoke it in the style your agent supports:

```text
Claude Code: /build-open-source-software /path/to/idea.md
Codex: Use $build-open-source-software with /path/to/idea.md
Antigravity: Use the build-open-source-software skill with /path/to/idea.md
```

## Use it for

- creating a new public software project from a written idea;
- selecting and validating a real package or distribution path;
- producing code, tests, documentation, release assets, and repository governance;
- coordinating user-owned setup for services such as PyPI, npm, Read the Docs, or Vercel.

Do not use it for an isolated feature, a small fix, or routine maintenance in an established repository.

## How it works

1. It treats `idea.md` as private, untrusted requirements.
2. It writes `plan.md` outside the public repository and stops for explicit approval.
3. It implements the approved scope and verifies the shipped form, not only the source tree.
4. It asks for just-in-time authorization before public pushes, publishing, deployment, or governance changes.
5. It releases `v0.1.0`, then requires future source changes to arrive through pull requests.

The skill never asks for passwords, private keys, API keys, recovery codes, or long-lived registry tokens. It directs the user to provider-owned setup flows when human action is required.

## Requirements

- Claude Code, Codex, Antigravity, or another compatible Agent Skills host
- Git 2.34 or newer
- Python 3.11 or newer for the bundled deterministic audit scripts
- authenticated provider tooling only when the approved workflow reaches an external action

## Evidence and limits

The deterministic audit tooling has 90 unit and adversarial tests. Run them from this directory:

```console
python -m unittest discover -s tests -v
```

The suite exercises private-input guarding, authored-text review, release-state checks, archive handling, Git history inspection, and failure behavior. Three symlink-specific tests may skip on Windows systems that do not grant symlink privileges.

The suite validates the bundled deterministic tooling and repository package. It is not a host-level end-to-end test of Claude Code, Codex, or Antigravity.

The skill cannot prove that arbitrary generated software is correct, secure, or compatible with every ecosystem. It requires project-specific tests, clean-environment verification, evidence review, and explicit user approval at material checkpoints. Human judgment remains necessary for product scope, legal ownership, provider accounts, and final publication. Available tools and permissions depend on the host agent.

## License

Apache License 2.0. See the repository [LICENSE](../../LICENSE) and [NOTICE](../../NOTICE).
