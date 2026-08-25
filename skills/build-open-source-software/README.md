<div align="center">
  <h1>build-open-source-software</h1>
  <p><strong>Turn a private idea into tested, documented, release-ready open-source software.</strong></p>
</div>

This Codex skill guides a new project from `idea.md` through an approved private plan, implementation, documentation, ecosystem-native packaging, a verified `v0.1.0` release, and pull-request-only governance.

## Install

Ask Codex:

```text
Use $skill-installer to install the skill from https://github.com/satwiksps/skills/tree/main/skills/build-open-source-software
```

The skill becomes available on the next turn. Invoke it with:

```text
Use $build-open-source-software with C:\path\to\idea.md
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

- Codex with skill support
- Git 2.34 or newer
- Python 3.11 or newer for the bundled deterministic audit scripts
- authenticated provider tooling only when the approved workflow reaches an external action

## Evidence and limits

The deterministic audit tooling has 90 unit and adversarial tests. Run them from this directory:

```console
python -m unittest discover -s tests -v
```

The suite exercises private-input guarding, authored-text review, release-state checks, archive handling, Git history inspection, and failure behavior. Three symlink-specific tests may skip on Windows systems that do not grant symlink privileges.

The skill cannot prove that arbitrary generated software is correct, secure, or compatible with every ecosystem. It requires project-specific tests, clean-environment verification, evidence review, and explicit user approval at material checkpoints. Human judgment remains necessary for product scope, legal ownership, provider accounts, and final publication.

## License

Apache License 2.0. See the repository [LICENSE](../../LICENSE) and [NOTICE](../../NOTICE).
