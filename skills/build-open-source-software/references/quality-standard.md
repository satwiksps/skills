# Engineering and writing quality standard

Use this reference during the Phase 1 decision pass, without executing commands, and again after plan approval during implementation and every release review.

## A usable product, not a scaffold

The first release must complete one valuable workflow end to end. A repository full of interfaces, TODOs, mocked paths, or future-facing documentation is not complete.

- Implement the approved behavior and explicit non-goals. Do not add speculative extension points.
- Prefer a small number of clear modules with explicit boundaries over generic factories, managers, helpers, and service layers.
- Keep deterministic core logic separate from files, environment variables, databases, subprocesses, clocks, randomness, and networks.
- Validate input at the boundary. Return actionable errors that state what failed, what was expected, and how the user can recover.
- Define idempotency, retries, timeouts, cleanup, partial failure, cancellation, and concurrency behavior wherever they apply.
- Make dangerous operations previewable and opt-in. Require narrow targets and refuse ambiguous deletion, overwrite, migration, or publication.
- Minimize dependencies. Record why each runtime dependency is needed, pin or lock development and deployment resolution, and audit licenses and known vulnerabilities.
- Remove dead code, unused dependencies, commented-out implementations, generated demo filler, and stale scaffolding before release.

Do not ship `TODO`, `FIXME`, or `XXX` markers in project-authored release files. Put later work in the issue tracker. Do not leave `pass`, `NotImplemented`, empty handlers, hardcoded sample results, or mock implementations on a path advertised as supported. A deliberately unsupported path must fail clearly and appear in limitations.

## Evidence ladder

Every public claim needs the strongest practical evidence:

1. A unit test for local logic.
2. An integration test for boundaries between real components.
3. A negative-path test for invalid input and failure recovery.
4. An end-to-end test from the built artifact.
5. A clean consumer smoke test following the public documentation.
6. A reproducible benchmark only for performance, cost, scale, or quality claims.

Mocks can isolate failures, but mock-only confidence is insufficient for a package, protocol, database, filesystem, subprocess, network adapter, or deployment. Use real local components where possible. Keep paid or credentialed live tests separate, opt-in, budgeted, and documented.

For each acceptance criterion, record the exact command, input, expected observation, and result. Preserve reproducible evidence in tests or versioned benchmark fixtures when it benefits users. Do not commit private corpora, credentials, or machine-specific logs.

Coverage is a diagnostic, not proof. Use branch coverage and a project-specific threshold that cannot be lowered casually, but prioritize critical invariants, error branches, and public behavior. Add property tests, fuzzing, concurrency tests, mutation testing, or crash injection when those techniques address a real risk.

## Artifact-first verification

Release confidence comes from what users install:

1. Start from a fresh detached checkout or source export of the exact candidate commit. Reject sparse checkout, `assume-unchanged`, and `skip-worktree` state.
2. Perform the locked dependency install.
3. Run formatting checks, lint, static analysis, tests, selected docs and site builds, and security scans.
4. Perform a local rehearsal build for every file artifact, inspect its contents, and install it by filename in a fresh consumer directory with no editable install or repository import path. Check dependency integrity, every declared entry point, and the README quick start, including failure and cleanup behavior. Reject planning files, secrets, development caches, local databases, oversized fixtures, and unintended sources. Record rehearsal hashes only as readiness evidence; these bytes are never canonical or approvable for release.
5. For an approved source-only distribution before tag authorization, consume the exact candidate commit through a detached checkout or native local replacement that cannot escape into public metadata. Reserve signed candidate-tag creation and tag-addressed consumption for the authorized Phase 5 gate.
6. After explicit authorization, push only the candidate branch with the full source:destination refspec and verify the remote default-branch commit. Never use a wildcard, `--tags`, or `--follow-tags`.
7. On that exact commit, run canonical hosted CI without credentials or private inputs. An unprivileged job builds each file artifact once from repository content, exercises and inspects the exact bytes with repository-only checks, records hashes, and stores them under immutable repository, commit, workflow, run, and artifact identities. If provider attestation requires an identity permission, use a separate non-building job that receives only the exact built bytes, has only the narrow attestation permissions, and cannot publish or execute project code. Do not pass `idea.md`, `plan.md`, another private input, or any private-input path, inventory, excerpt, encoding, hash, digest, or fingerprint to hosted CI.
8. In the local private environment, download every artifact by the full immutable identity. Verify that its provider attestation binds the expected repository, workflow, and commit, then verify its SHA-256.
9. Supply the complete private-input inventory only to the local release audit. Audit the downloaded canonical files and copy the exact passing bytes into a content-addressed staging directory outside the checkout.
10. Present the immutable run and artifact identities plus the canonical file digests and stop for explicit user approval. A passing hosted run, a local rehearsal, plan approval, and bootstrap-push authorization are not artifact-digest approval.
11. After digest approval, obtain the named authorization and apply and read back the repository rules, tag rules, release immutability, security settings, and Actions policy before tag creation.
12. After final publication authorization, create and audit the signed local tag on the approved commit and snapshots. Push only the exact tag source:destination refspec, then read back the remote tag object and peeled commit and compare both with the audited local identities.
13. A protected publisher fetches the original CI artifacts by the same identities and rejects any hash mismatch immediately before upload. An interactive publisher uses the exact local snapshots. Neither credentialed path may rebuild, repackage, run install or prepare scripts, load project plugins, or execute another project lifecycle hook.
14. Download and consume the exact public file, or consume the exact signed source tag, in a new credential-free sandbox and rerun the documented first-use path. Require every file destination to match the approved canonical CI hash; for source-only distribution, verify the public tag object and commit identity through the native consumer path.

Test the minimum supported runtime, a current runtime, and every operating system or architecture claimed. If a platform cannot be tested, do not badge or claim support for it.

Treat dependency installation, build backends, compiler plugins, package lifecycle scripts, test plugins, and newly published artifacts as untrusted code. Run them in a credential-free sandbox with a fresh task-specific home, no ambient Git, SSH, registry, cloud, browser, or package-manager credentials, no unrelated workspace mounts, bounded CPU, memory, disk, process count, and time, and only the network destinations needed for the current step. Before execution, record and read back the actual container or VM identity, every mount and access mode, sanitized environment and agent sockets, egress policy, limits, and whether `.git` is absent or read-only. Pause if the host cannot enforce and verify every boundary required by the plan; changing HOME or clearing environment variables is not sufficient isolation. Keep `.git` absent or read-only so package code cannot persist hooks, fsmonitor, diff, signing, or helper configuration for later host commands. Inspect package scripts and build hooks before enabling them. Separate artifact download from execution, then disable network access when the supported workflow is offline. After the sandbox exits, record limit and egress results and reject unexpected hooks or execution-capable local Git configuration. A protected publisher fetches only the original approved CI artifact plus minimal publisher tooling; an interactive publisher reads only the exact approved local snapshot. Acquire a short-lived credential only after identity and digest verification. Prove that the exact-file upload command cannot rebuild, repackage, or run project lifecycle hooks. If a registry requires credentialed rebuilding or lifecycle execution, stop and redesign the channel. The explicitly reapproved Rust/crates.io adapter exception may allow only Cargo's unavoidable repackaging and must still disable verification rebuilding and project lifecycle execution while the credential is accessible.

## Security baseline

- Select and pin a maintained local secret scanner in the approved adapter. Verify its binary or container provenance and digest. Run it with telemetry and update checks disabled, no credentials, and no network; never upload repository content or findings to a cloud API. Before displaying a raw staged diff, run its non-echoing index mode. Before every public push and in CI, scan the full reachable Git history and refs, commit and annotated-tag messages, Git LFS objects, current index and worktree, and every release artifact. Treat the bundled regex checks as supplemental tripwires. If a real secret is found, stop, avoid printing it, revoke or rotate it, then clean the repository according to an approved incident plan.
- Use least privilege for application credentials, filesystem access, network access, CI tokens, and deployment environments.
- Avoid shell construction from user input. Use argument arrays and language-native filesystem APIs.
- Define safe path handling, symlink behavior, archive extraction, serialization limits, request limits, and dependency trust where relevant.
- Do not log secrets, full tokens, private inputs, raw provider responses, or sensitive user data.
- Document the supported security-reporting channel only after the user confirms it is monitored. Do not invent response-time promises.
- Review transitive dependency licenses for Apache-2.0 compatibility and record any attribution requirement.
- Produce an SBOM, checksums, signatures, or provenance when the ecosystem supports them and users can verify them.

Use a threat model proportional to the software. A local text formatter does not need an enterprise security architecture. A network daemon, package installer, credentialed integration, parser, database migration tool, or destructive CLI needs explicit abuse and failure cases.

## Anti-slop code review

Review semantics, not authorship. Reject code when any of these are true:

- It compiles only in the source tree or depends on an undeclared local file.
- The happy path works but documented errors, cleanup, or upgrades do not.
- Names hide the domain behind vague terms such as `manager`, `processor`, `handler`, `utils`, or `data` without a precise role.
- Abstractions have one implementation and no current boundary that justifies them.
- Comments restate syntax instead of explaining invariants, reasons, or safety constraints.
- Tests mirror implementation details, assert only that mocks were called, or cannot fail when behavior is broken.
- Exceptions are swallowed, errors are converted to success, or retries can duplicate effects.
- Defaults trigger network calls, paid operations, data deletion, telemetry, or persistent mutation without clear disclosure.
- Public configuration exists but is ignored, unvalidated, or undocumented.
- A feature is advertised through a route, flag, badge, or example but is not exercised end to end.

Run a focused second review after tests pass. Search for shortcuts that the test suite may not expose.

## Concrete writing standard

Lead with the observable outcome and intended user. Use exact nouns, commands, defaults, limits, and failure behavior.

- State what the software does, what it does not do, and the supported deployment.
- Prefer a tested example over a paragraph of adjectives.
- Qualify measurements with workload, baseline, method, date, and limitations.
- Separate implemented support, architectural intent, experimental behavior, and future work.
- Write warnings as an action, consequence, and recovery path.
- Use tables for exact mappings, matrices, and schemas; prose for reasoning; numbered steps for stateful procedures.
- Keep examples copyable and free of hidden setup.
- Document uninstall, retained data, migration, backup, rollback, and compatibility where persistent state exists.

Reject vague or inflated language such as `revolutionary`, `effortless`, `seamless`, `cutting-edge`, `enterprise-ready`, `production-grade`, or `blazing fast`. Replace it with the concrete supported behavior or measured result, not different hype. Treat broad words such as `powerful` and `robust` with the same skepticism during manual review.

Do not use em dashes. Do not use ornamental headings, repetitive summaries, generic feature grids, fake personas, contrived comparisons, or long explanations of obvious code. Do not add AI-generation attribution to project prose, commit messages, changelogs, source headers, or contributor metadata.

## Release review questions

- Can a stranger consume the file artifact or source-only tag using only the README?
- Does the first command produce the documented result?
- Can they understand the supported scope before risking data or money?
- Are errors actionable and tested?
- Are all defaults safe and deterministic where promised?
- Does every selected file package contain only intended files?
- Do version, tag, changelog, selected docs and site, and applicable package or source-tag metadata agree?
- Are claims, badges, links, contacts, and compatibility statements true now?
- Can a maintainer reproduce the build and release without a local secret file?
- Is there any reason to withhold v0.1.0 rather than publishing a broken first impression?
