# Ecosystem adapter contract

Use this reference during the Phase 1 decision pass to select and specify an adapter, without executing its commands. Use it again after approval to execute the selected adapter. Do not pretend that one command set supports every language. Verify current official tool and distribution documentation and put exact commands in `plan.md`.

## Required adapter fields

Every project adapter must define:

| Field | Required decision |
| --- | --- |
| Runtime | Minimum, current, and unsupported versions |
| Platforms | Operating systems and architectures actually tested |
| Manifest | Package name, license, metadata, dependencies, and entry points |
| Version | One authoritative source and how code reads it |
| Locking | Reproducible dependency resolution for development and release |
| Formatting | Write command and check-only command |
| Lint | Exact command and configured rules |
| Static analysis | Type, compiler, or semantic checks |
| Tests | Unit, integration, negative, end-to-end, and optional live tests |
| Coverage | Branch-aware command and maintained threshold |
| Build | Exact source and binary artifact commands |
| Canonical CI | Unprivileged repository-only build and validation jobs, candidate-commit trigger, artifact names and retention, immutable repository, commit, workflow, run, and artifact identity fields, and an optional separate non-building job with only narrow provider-attestation permissions; never private inputs or their hashes or fingerprints |
| Inspection | Outer `tar` or `zip` type, recursive required-member and scoped allowlist contracts, exact project LICENSE, NOTICE, and project-owned metadata paths, metadata/owner/mode/time invariants, asset metadata checks, and type-specific inspection commands; otherwise a digest-bound adapter proof |
| Consumer test | Fresh install and first-use command outside the source tree |
| Local approval | Exact artifact download, attestation and SHA-256 verification, private-input-aware audit, content-addressed snapshot, and explicit user digest approval |
| Distribution | Registry, immutable source tag, OCI digest, installer, or other channel; include name preflight, authentication, ownership, protected retrieval of the original CI artifact or interactive use of the exact local snapshot, and exact-file publish commands that cannot rebuild, repackage, or execute project hooks under credentials |
| Public verification | Exact version install, metadata, hashes, provenance, and smoke test |
| Documentation | Native API reference generator and hosted docs build, or the approved reason and replacement discovery path when waived |
| Security | Exact pinned commands for dependency, static, and artifact scanning plus a local offline full-history and LFS secret scanner with telemetry and updates disabled, verified provenance and digest, and a non-echoing staged mode |

Use `N/A` only with a concrete reason and the source-tag or commit equivalent. A source-only module may have no registry upload or file archive, but it still defines license location, semantic tag version, native consumer command, immutable commit evidence, documentation path, security checks, and public tag resolution. If the chosen ecosystem is not listed below, derive these fields from its official toolchain and distribution documentation. Use an isolated sample build to prove the commands before relying on the adapter. A missing adapter decision is a plan gap, not permission to guess during release.

Choose the artifact model explicitly. File-based registries and release downloads require inspection, hashes, and a clean install of the exact files. Build canonical files once in unprivileged, repository-only hosted CI on the pushed candidate commit. Download and audit them locally with private inputs, obtain explicit digest approval, and publish either by fetching the same original run artifacts or by using the exact local snapshots. Source-only ecosystems such as Go modules and many Swift packages use the signed, immutable Git tag as the distribution object and run the release audit with `--tag-only-distribution`. Container releases use immutable OCI digests, inspect an OCI layout or exported archive before upload, and verify the public digest plus a credential-free runtime smoke test. A deployment is not a substitute for an installable artifact unless the approved product is itself a hosted service.

## Python and PyPI

Prefer modern `pyproject.toml` metadata with a `src/` layout. Choose a maintained PEP 517 backend based on actual needs. Do not add multiple environment or dependency managers.

Define:

- `build-system` with a deliberate, reproducible version policy;
- PEP 621 name, `0.1.0` version, description, README, Python range, Apache-2.0 license expression or file, authors, keywords, classifiers, dependencies, optional extras, entry points, and project URLs;
- explicit wheel and source-distribution contents;
- a typed-package marker when the public package is typed;
- pytest strict configuration, Ruff or an approved equivalent, strict type checking where appropriate, and branch coverage;
- Sphinx/MyST or another approved documentation stack with pinned documentation dependencies.

A typical gate, adjusted to the project's tools, includes:

```console
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m ruff check .
python -m ruff format --check .
python -m mypy src/<import_name>
python -m pytest --cov=<import_name> --cov-branch
python -m build
python -m twine check dist/*
```

Then inspect both wheel and sdist. Create separate clean virtual environments, install the wheel and the sdist without editable mode, run `python -m pip check`, import the package, invoke every declared CLI entry point, and execute the README workflow. Make sure imports resolve from the installed distribution rather than the checkout.

CI should test the minimum supported Python, representative intermediate versions, the newest supported stable Python, and Windows, macOS, and Linux when those platforms are claimed. Optional providers need import-boundary tests, actionable missing-extra errors, and live tests only when credentials and cost approval exist.

Publish the exact approved canonical wheel and source archive with a protected PyPI GitHub environment and trusted publishing OIDC when current PyPI supports the project. The publish job needs job-level `id-token: write`, no username or password, and the exact workflow and environment registered on PyPI. It fetches the original candidate-run files, checks the approved hashes, and invokes only an upload path that cannot build or run project hooks. Verify PyPI metadata, wheel tags, source archive, hashes, attestations or provenance, and a clean `pip install <name>==0.1.0`.

## JavaScript or TypeScript and npm

Use one package manager and commit its lockfile. Set `private: true` on packages that must never publish, especially a standalone website. For a public package, define the package name, `0.1.0` version, description, license, repository, bugs, homepage, files allowlist, entry points, exports, types, engines, side-effects behavior, and publish access deliberately.

Use TypeScript strict mode for TypeScript source unless the plan records a justified exception. Define separate write and check formatting commands. A typical npm gate, adjusted to selected tools, includes:

```console
npm ci
npm audit --audit-level=high
npm run format:check
npm run lint
npm run typecheck
npm test
npm run build
npm pack --dry-run
npm pack
```

Inspect the tarball allowlist. In a new directory with a separate `package.json`, install the tarball by filename and exercise CommonJS, ESM, types, browser, CLI, or framework entry points exactly as advertised. Confirm that development source and undeclared workspace packages are not required.

CI should test the minimum supported Node version, a current active LTS, and the operating systems actually claimed. Libraries need consumer tests for each exported module format. CLIs need exit-code, stdout, stderr, path, signal, and shell tests. Browser packages need a real browser smoke test when practical.

Prefer npm trusted publishing with OIDC and provenance when current npm supports the repository, package, and CI provider. Publish only the exact approved canonical tarball through a command proven not to rebuild, repackage, or run lifecycle hooks. A public scoped package may need explicit public access. If the first publication requires interactive ownership bootstrap, the user performs it without sharing credentials and uses the exact local content-addressed snapshot. Verify the registry tarball, integrity digest, provenance, metadata, and a clean `npm install <name>@0.1.0` consumer test.

## Rust and crates.io

Define package metadata, edition, minimum supported Rust version, features, binaries, include or exclude rules, repository, documentation, readme, keywords, categories, and Apache-2.0 license in `Cargo.toml`. Commit `Cargo.lock` for applications and binaries; decide deliberately for libraries.

The gate normally includes `cargo fmt --check`, `cargo clippy --all-targets --all-features -- -D warnings`, `cargo test --all-features`, minimum-version and stable toolchain checks, documentation with warnings denied, `cargo package --list`, and `cargo package`. Unpack and inspect the crate, test the packaged source, and install or consume it from a fresh project.

Standard `cargo publish` does not accept a prebuilt audited `.crate`. It packages the source again and normally verifies that package with a build, so the exact-byte credentialed-upload invariant cannot be claimed. Default Rust v0.1.0 distribution to the signed immutable source tag and use `--tag-only-distribution`. Never state or imply that crates.io received the canonical CI `.crate` bytes when Cargo created the uploaded package itself.

Use crates.io only when the approved plan adopts a named Rust adapter exception and the user explicitly reapproves that material distribution and security change after seeing the reduced assurance. The exception must record the exact Cargo executable, version, and hash; prove repeated packaging reproducibility offline in a credential-free sandbox; inspect and smoke-test the resulting `.crate`; inventory package scripts and build hooks; document how the credentialed command disables the verification rebuild and lifecycle execution when the current Cargo version supports that separation; keep private inputs and their fingerprints out of hosted systems; and verify the downloaded public `.crate` immediately after publication. Treat the registry bytes as separately created bytes and report their actual public digest. If the adapter cannot prevent a project build or lifecycle hook while the crates.io credential is accessible, do not use crates.io. The user logs in or stores a scoped token directly in the provider secret store only after approving this exception; never request the token.

## Go modules

Use a stable module path in `go.mod`. Public distribution is normally the Git repository and immutable semantic-version tags rather than an upload to a central registry. Run `gofmt` check, `go vet`, `go test ./...`, `go test -race ./...` where supported, static analysis, vulnerability scanning, and cross-platform builds for claimed binaries. Test `go install <module>/cmd/<name>@v0.1.0` after publication. Major versions v2 and later must follow Go module path rules.

For binary releases, build canonical binaries once from the exact pushed candidate commit in the unprivileged repository-only workflow, attach checksums and provenance, and smoke-test each target artifact. After local private-input-aware audit and digest approval, require the signed tag to resolve to that same commit and publish the original run artifacts without rebuilding. Do not claim a platform whose binary was not executed or otherwise validated on that platform.

## JVM, .NET, Ruby, PHP, Swift, and native projects

Use the same adapter contract with the ecosystem's official tools:

- Java or Kotlin: commit a verified Gradle or Maven wrapper, run formatting, compiler warnings, tests, static analysis, documentation, local publication, and consumer tests before Maven Central. Complete current namespace, signing, and Central Portal setup through the user's account.
- .NET: define package metadata in the project file or central props, run restore with a lock, format check, build with warnings as errors, tests and coverage, `dotnet pack`, package validation, local NuGet source install, and public NuGet verification.
- Ruby: use a gemspec with an explicit file list, locked development bundle, formatter and linter, tests, `gem build`, archive inspection, clean `gem install`, and RubyGems ownership and MFA setup.
- PHP: use `composer.json` with an appropriate platform range, lock applications, run `composer validate --strict`, formatting, static analysis, tests, archive inspection, and a fresh Composer consumer. Verify Packagist webhook and tag discovery.
- Swift: define supported platforms and products in `Package.swift`, run formatting and lint if selected, `swift build`, `swift test`, documentation, and a clean package consumer. When distribution is source-only, validate the immutable signed tag and commit through Swift Package Manager; inspect archives or binaries only when those are actual selected channels.
- C, C++, Zig, or other native software: use a documented build system, compiler warning policy, sanitizers, unit and integration tests, supported compiler and platform matrix, install and uninstall targets, package manifests, reproducible release archives, checksums, signatures, and real binary smoke tests.

For any language, add Docker images, Homebrew, Scoop, Winget, Linux packages, app stores, or installer formats only when they serve the approved users. Each additional channel needs its own clean install, upgrade, uninstall, signing, provenance, and public verification path.

## Multi-language repositories

Use a separate adapter for each independently built or published component. A Python library plus a Next.js website needs separate locks, checks, caches, and artifact rules. Keep the website package private. The stable CI aggregate depends on both.

Do not let a documentation or site toolchain become an undeclared runtime dependency of the product. Do not publish a monorepo root accidentally. Explicitly map which tag, manifest, artifact, registry, and workflow owns each releasable component.
