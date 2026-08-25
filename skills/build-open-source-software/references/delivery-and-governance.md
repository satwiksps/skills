# Repository delivery, releases, publishing, and governance

Use this reference before creating public repository files, CI, release automation, provider setup, or remote controls.

## Repository contract

Create project-specific versions of these public files:

- `LICENSE`: copy `../assets/APACHE-2.0.txt` without edits. The release audit permits only line-ending and final-newline normalization.
- `NOTICE`: the user-confirmed copyright year and legal holder. Add required third-party attributions without inventing any.
- `README.md`: installable product contract, not a design plan.
- `CHANGELOG.md`: Keep a Changelog structure with `Unreleased`, semantic versions, dates, and compare links.
- `CONTRIBUTING.md`: exact setup and verification commands, architecture invariants, issue expectations, commit style, PR evidence, compatibility review, and contribution licensing.
- `CODE_OF_CONDUCT.md`: a current recognized code of conduct with a real, monitored private enforcement contact and no invented service promise.
- `SECURITY.md`: supported versions, private reporting path, requested evidence, coordinated disclosure expectations, and actual trust boundaries.
- `.editorconfig` and `.gitattributes`: UTF-8, final newline, line endings, indentation, and binary classifications.
- issue forms: reproducible bug reports, secret-redaction warning, security routing, environment and version, observed versus expected behavior, and minimal reproduction.
- pull request template: summary, motivation, validation, compatibility and safety effects, documentation, and a scoped checklist.
- dependency update configuration for every maintained ecosystem in the repository.

Add only real governance. `CODEOWNERS` needs real maintainers. `GOVERNANCE.md` needs an actual decision model. `SUPPORT.md` needs a monitored channel. `CITATION.cff` is useful for research software. Keep every required third-party attribution in `NOTICE` factual and evidence-backed. Never invent a team, steering committee, funding link, response SLA, supported version, or company identity.

Commit subjects should follow `type(optional-scope)!: imperative subject`. Keep commits narrow and follow the signing policy approved in `plan.md`; the default policy requires signed commits and signed release tags. Only an explicit plan exception may waive signing. Do not replace the user's name or email and do not add assistant coauthor trailers.

Record signer identities before the first commit. For GPG, the user confirms the full primary fingerprint shown by `gpg --list-secret-keys --keyid-format=long --with-subkey-fingerprint`; configure their existing key with `git config user.signingkey <fingerprint>`, `git config commit.gpgsign true`, and `git config tag.gpgsign true`. Verification requires the matching public key in the verifier's keyring. For SSH signing, obtain the approved key fingerprint with `ssh-keygen -lf <path-to-public-key> -E sha256`, configure `git config gpg.format ssh`, `git config user.signingkey <path-to-public-key>`, and the two signing booleans. When `user.signingkey` points to a public key, its private half must be available through `ssh-agent`. Create a local, untracked allowed-signers file containing the confirmed principal and public key, then set `git config gpg.ssh.allowedSignersFile <absolute-local-path>`. Never commit a private key or ask the user to reveal it.

Use `git commit -S` and `git tag -s`. Verify commits with `git verify-commit --raw <sha>` and tags with `git verify-tag --raw <tag>`. The release audit accepts only typed identities from the approved plan: `gpg:<full-fingerprint>`, `ssh-key:SHA256:<fingerprint>`, or `ssh-principal:<principal>`. Confirm the identity from structured verification output, not from an untrusted UID substring. CI verifiers need the approved public key or allowed-signers file provisioned without a private key. If the approved plan explicitly waives signing, omit the signing audit flags and signed-commit repository rule, and report the reduced assurance.

## Continuous integration

CI runs for every pull request and the default branch. Use locked dependency resolution and cache keys tied to the lock or manifest.

Include the gates selected in `plan.md`:

- formatting and lint;
- static or type analysis;
- unit, integration, negative-path, property, and end-to-end tests as applicable;
- branch coverage with a maintained local threshold;
- minimum and current runtimes plus every claimed operating system or architecture;
- package build, metadata validation, archive inspection, artifact upload, clean artifact install, and consumer smoke test;
- docs build with warnings as errors and link or example validation;
- website dependency audit, lint, type check, production build, and production-server smoke test;
- dependency review, a pinned full-history, refs, messages, LFS, worktree, index, and artifact secret scan, security analysis, and SBOM or provenance where supported.

For GitHub Actions:

- start with workflow-level `contents: read` and add narrower job permissions only where required;
- pin every third-party action to a full commit SHA and retain a comment with the human-readable release;
- set `persist-credentials: false` on checkout;
- use explicit job timeouts and concurrency cancellation for superseded branch runs;
- never expose secrets to forked pull requests;
- do not use `pull_request_target` to run code from an untrusted checkout;
- separate untrusted build and test jobs from privileged publication jobs;
- upload artifacts with failure on missing files and a finite retention period;
- configure the repository's Actions policy to match the workflow's pinning policy when the provider supports it.

The canonical artifact workflow must run on the exact pushed candidate commit. Its build, test, inspection, and consumer jobs have no environment, repository, registry, or deployment secrets and no `id-token: write`. Their inputs are the repository checkout, lockfiles, explicitly public workflow parameters, and provider-generated repository and commit context only. If the provider requires an identity permission to create an attestation, place it in a separate non-building job that receives only the already built artifacts, has only the narrow attestation permissions, cannot access a publication environment, and cannot execute project code. Never upload, hash, encode, fingerprint, or pass `idea.md`, `plan.md`, an approved-plan snapshot, another private-input file, the private-input inventory, or any value derived from them. Hosted secret scanning is limited to repository and artifact content; private-input comparison occurs only in the later local audit.

Create one final job with a stable name such as `Required` that depends on every required job and fails unless each dependency succeeded. Branch rules require this stable aggregate context rather than individual matrix cell names. This prevents a harmless matrix rename from locking the repository and prevents a newly added gate from being omitted accidentally.

CI configuration is not evidence until a run on the exact candidate commit passes. Read the remote check suite and report every required job.

## Release workflow

Use semantic versions and one version source of truth. Separate canonical construction, private audit and approval, and publication into distinct trust domains. The canonical artifact workflow runs before tag creation on the exact candidate commit. It builds file artifacts once in an unprivileged, repository-only job and retains them under immutable identity: provider repository ID plus expected owner/name, full commit object ID, workflow ID and path, run ID and attempt, and artifact ID and name. A passing hosted run is not private-input clearance and is not user approval.

After that run, a local operator downloads the artifacts by those exact identities, verifies that provider attestations bind them to the expected repository, workflow, and commit, verifies SHA-256, and runs the private-input-aware audit locally with the complete inventory. The audit copies exact passing bytes to a content-addressed directory outside the repository. Present the artifact identities and digests and stop for explicit user approval. Never send the private inputs, their locations, inventories, hashes, fingerprints, or other derived values back to hosted CI, repository settings, workflow inputs, caches, artifacts, logs, or attestations.

Only after artifact-digest approval and the separately authorized repository rules and provider bindings may a signed tag and publication proceed. A protected publisher fetches the original artifacts from the approved run by the same immutable identities and fails unless each SHA-256 equals the approved local snapshot. If publication is interactive, upload only the exact local content-addressed snapshots. The credentialed environment contains only minimal publisher tooling, public release metadata, the approved run identities and artifact digests, and the exact upload files. It must not contain a source checkout, build toolchain, private-input data, or a command path that can rebuild, repackage, or invoke project lifecycle hooks. The only repackaging exception is the explicitly reapproved Rust/crates.io adapter described in the ecosystem reference; it still forbids verification builds and project lifecycle execution while credentials are accessible.

Before publication, verify that the tag:

- is an annotated tag and satisfies the approved signing policy, which requires a valid signature by default;
- points to the exact candidate commit;
- is reachable from the protected default branch;
- has the full required CI result, not only a shortened release test;
- has never existed publicly before.

For file distributions, the canonical candidate workflow should:

1. run the full source, test, documentation, and selected site validation from a fresh checkout or source export with no writable `.git` metadata;
2. build every selected release file exactly once without credentials;
3. inspect, install, and exercise those exact files with repository-only checks, including every source and binary variant produced by the ecosystem;
4. generate artifact SHA-256 files and an SBOM without credentials, then use a separate non-building, narrowly permissioned job for provider attestations when required; and
5. upload the files with failure on missing output and enough finite retention for local approval and later publication, recording the provider repository ID and expected owner/name, full commit object ID, workflow ID and path, run ID and attempt, artifact ID and name, per-file name, and per-file SHA-256.

After the local audit, artifact-digest approval, settings application, and signed tag, protected publication automation should:

1. verify the tag exactly equals `v<approved-version>`, points to the approved candidate commit, is reachable from the protected default branch, and satisfies the approved signature policy;
2. accept only the approved canonical run identity and per-file SHA-256 values as non-secret inputs;
3. download only the original candidate-run artifacts plus minimal publisher tooling, without checking out project source;
4. verify artifact identity, attestation, and every approved digest before acquiring or using a short-lived publication credential;
5. upload exact files through a command that cannot build, repackage, run install or prepare scripts, load project plugins, or invoke any project lifecycle hook;
6. after repository release immutability is enabled, create a draft release, attach every approved artifact and checksum, verify the complete draft, publish it, and verify that its tag and assets are immutable and attested; release title and notes may remain editable where the provider permits;
7. publish stable releases to each selected registry or deployment target through the isolated environment, handle prereleases explicitly, and fail if a release or registry version already exists; and
8. prove every destination received the approved canonical digest.

Do not rerun source validation, documentation builds, packaging, or consumer install commands in the credentialed publisher. Defense-in-depth validation belongs in an earlier unprivileged job. Do not build separately for GitHub Releases and a registry. If a registry cannot accept the exact verified file, stop and redesign the release channel unless the Rust adapter's narrowly scoped crates.io exception has been explicitly reapproved. Even that exception may allow only Cargo's unavoidable repackaging, never a verification rebuild or project lifecycle execution while the credential is accessible. For a source-only distribution, validate and consume the exact signed tag commit through the ecosystem's native tool and record the tag object plus commit identity.

Never use `--clobber`, force-push a release tag, overwrite release assets, or rebuild a published version. A failed public release receives a fix through a pull request and a higher version. Yank or deprecate a harmful version according to the registry's policy without pretending it never existed.

Keep publication disabled with an explicit repository variable or manual environment gate until the user has completed account setup and authorized the release. Close or disable the bootstrap gate after verification if the regular process uses protected tags and environments instead.

## Secret-free provider handoffs

Provider interfaces change. At execution time, read the current official documentation for the selected provider and tailor these steps. Give the user exact values for owner, repository, workflow filename, environment, package name, root directory, and production URL. Ask them to report completion, not credentials.

Start from these official references and recheck them at execution time:

- [GitHub rulesets and branch protection](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/about-rulesets)
- [GitHub repository rules REST API](https://docs.github.com/en/rest/repos/rules)
- [GitHub immutable releases](https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/establish-provenance-and-integrity/prevent-release-changes)
- [Verify GitHub release integrity](https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/secure-your-dependencies/verify-release-integrity)
- [PyPI trusted publishing](https://docs.pypi.org/trusted-publishers/)
- [npm trusted publishing](https://docs.npmjs.com/trusted-publishers/)
- [Read the Docs configuration](https://docs.readthedocs.com/platform/stable/config-file/index.html)
- [Vercel Git deployments](https://vercel.com/docs/git)

### GitHub

Before an authorized repository creation or push:

1. Ask the user to authenticate with `gh auth login` or the GitHub browser if needed.
2. Confirm owner, repository name, public visibility, description, default branch, and whether issues and discussions are wanted.
3. Confirm that no planning file, secret, private fixture, local database, build output, or environment file is tracked.
4. Push the verified bootstrap history only after explicit authorization, using the full refspec `refs/heads/<local-candidate-branch>:refs/heads/<default-branch>`.

Every bootstrap and release push names one exact source ref and one exact destination ref. Do not use `git push --tags`, `git push --follow-tags`, a wildcard refspec, an implicit multi-ref push, or a push configuration that adds other refs. After the bootstrap push, read `refs/heads/<default-branch>` from the remote and compare it with the audited local candidate commit. After the release tag push, read both `refs/tags/v0.1.0` and its peeled `refs/tags/v0.1.0^{}` value from the remote and compare them with the audited local tag-object and commit identities. A typical explicit tag command is `git push <remote> refs/tags/v0.1.0:refs/tags/v0.1.0`; do not start publication until both remote identities match.

After the repository exists, canonical CI has passed on the exact candidate commit, the local private-input-aware audit has snapshotted the artifacts, and the user has approved their digests, include these mutations in one named, just-in-time authorized repository-settings batch. The authorization must enumerate the branch rule, both `v*` tag rulesets and their bypass actors, release immutability, security features, and Actions policy:

1. Apply the approved PR-only default-branch rule and both aggregated `v*` tag rulesets.
2. Enable release immutability so published release tags and assets cannot be changed; do not claim that titles or notes are frozen when the provider still permits metadata edits.
3. Enable private vulnerability reporting and the security features available for the repository, including secret scanning, push protection, validity checks, dependency security updates, and code scanning when appropriate.
4. Restrict Actions to trusted sources or full-SHA use when supported. Keep the default workflow token read-only and prevent Actions from approving pull requests unless a real workflow requires it.
5. Read every changed setting, rule condition, bypass actor, and immutable-release state back through the provider API and compare it with the approved plan.

Do not infer repository rules from files. Read them through the REST or GraphQL API.

### PyPI

Prefer trusted publishing with GitHub Actions OIDC:

1. The user signs in to PyPI themselves.
2. For a new project, they create a pending trusted publisher if current PyPI supports it. For an existing project, they open the project's Publishing settings.
3. Give them the exact PyPI project name, GitHub owner, repository name, release workflow filename, and protected environment name, normally `pypi`.
4. The workflow's publish job uses that exact environment and job-level `id-token: write`; it does not receive a username or password.
5. Protect the GitHub environment with the strictest tag or branch policy supported, plus a human reviewer when another trusted maintainer exists.
6. After publishing, verify the PyPI JSON metadata, filenames, hashes, provenance or attestations, project links, license, classifiers, and a clean install of the exact version.

If trusted publishing is unavailable, the user creates a project-scoped token and stores it directly as a protected repository secret. Never ask them to paste it into chat or a file you can read.

### npm

Prefer npm trusted publishing with OIDC when the current registry and CI combination support the package. The user signs in to npm, establishes ownership of the package or scope, enables two-factor authentication and trusted publishing, and selects the exact repository and workflow. The CI job receives `id-token: write` only where needed.

For a first publication that cannot use a pending publisher, have the user download the exact gated canonical CI tarball and publish that file interactively, or store a granular automation-scoped token directly in the provider secret UI for the protected publish job. Never rebuild during an interactive bootstrap. Check the current npm process first and never request the token. Publish public scoped packages with the required access setting, verify provenance, inspect the registry tarball, and install the exact public version in a clean consumer project.

### Read the Docs

The user connects their source provider and imports the repository. Give them the exact project slug, default branch, documentation configuration path, and desired visibility. Commit a root `.readthedocs.yaml` version 2 file first. After import, verify the build log, canonical URL, stable and versioned builds, webhook, search, edit links, and badge. Do not add the badge before the project exists.

### Vercel

The user connects GitHub or runs an interactive `vercel login`. Give them the repository, website root directory, framework, production branch, build settings, and exact public environment variables. They enter sensitive environment variables directly in Vercel.

Confirm whether preview deployments are enabled. If disabled, encode production-only branch deployment. If enabled, retain fork protection and make sure preview secrets have the minimum scope. Gate production so a commit with failing required CI is not promoted. After deployment, verify the deployment's commit SHA, domain, TLS, security headers, canonical metadata, robots, sitemap, social card, mobile rendering, and rollback path.

### Domains and other registries

For DNS, code signing, app stores, container registries, Maven Central, NuGet, RubyGems, crates.io, package managers, or cloud hosts, use the same pattern:

1. Read current official instructions.
2. List the non-secret identifiers and exact account action.
3. Prefer federated identity or interactive login.
4. Have the user store any unavoidable scoped secret directly with the provider.
5. Verify ownership, least privilege, release bytes, provenance, public installation, and revocation or rollback.

## v0.1.0 bootstrap and protection

The initial direct-to-default-branch history is a one-time bootstrap. Complete all local readiness gates, obtain authorization for the named repository creation and exact branch refspec, push the `0.1.0` candidate, read back the remote branch commit, and wait for repository-only canonical CI on that commit. Download the exact run artifacts by immutable repository, commit, workflow, run, and artifact identity; verify attestation and SHA-256; run the private-input-aware audit locally; and snapshot the passing bytes. Stop for the user's explicit approval of those canonical digests. Only then obtain authorization to apply and read back default-branch protection, both active `v*` tag rulesets, release immutability, security settings, and Actions policy. Complete separately authorized repository-dependent provider setup and keep publication gated. After final publication authorization, create the signed local `v0.1.0` tag, record its tag-object and peeled commit identities, rerun private-input and offline secret scans, and audit it against the approved canonical snapshots. Push only `refs/tags/v0.1.0:refs/tags/v0.1.0`, read back the remote tag object and peeled commit, and require exact identity matches. The protected publisher then fetches the same original CI artifacts and verifies their approved hashes, or the interactive publisher uses the exact local snapshots. Create a draft release, attach the approved assets, verify it, and only then publish. No credentialed step may rebuild or run a project lifecycle hook. Repackaging is also forbidden except under the explicitly reapproved Rust/crates.io adapter exception.

Prefer a GitHub repository ruleset for the default branch, with branch protection as a fallback. Match the actual default branch and require these outcomes:

- every update enters through a pull request;
- the stable `Required` check passes against an up-to-date branch;
- all review conversations are resolved;
- linear history is required and one merge method is documented;
- force pushes and branch deletion are blocked;
- required signed commits match the approved signing policy and merge flow;
- no administrator, app, deploy key, or role has an unintended direct-push bypass.

For a solo maintainer, set required approving reviews to zero while still requiring a pull request, CI, and conversation resolution. Requiring approval from the PR author is impossible. If another maintainer is available, require at least one fresh independent approval, dismiss stale approvals, and require real code-owner review for sensitive paths such as release workflows.

Use two active rulesets with the same `v*` condition because GitHub bypass permission applies to an entire ruleset. One ruleset restricts creation and gives only the intended release actor a bypass. The second blocks updates and deletion with no bypass actors. Their aggregate result permits that actor to create a new release tag but permits nobody, including that actor, to move or delete one. A tag protection that makes the release workflow impossible is not correct. Inspect both rulesets, then use the first real, locally audited `v0.1.0` push as the creation-path test. Never create a sacrificial `v*` probe tag that the immutability rules intentionally make undeletable.

Read back and report the active rules, conditions, bypass actors, approval count, required status context, strictness, force-push policy, deletion policy, signed-commit policy, and both tag rulesets. Do not test protection by making an unauthorized direct push. Use the provider API and a pull request for the next real change.

After this point:

- create a branch for every change;
- run the full local gate before pushing;
- open a focused pull request with evidence and compatibility notes;
- wait for required remote checks and review;
- merge using the configured linear method;
- create each later release tag only from the protected default branch;
- never temporarily disable protection to save time.

## Post-publication verification

Verify from outside the source checkout:

- selected registry or source-tag metadata, ownership, version, license, project URLs, artifact names, sizes, hashes, provenance, and yanked status where applicable;
- installation or native source-tag consumption and first-use behavior on the supported minimum runtime;
- GitHub release notes, immutable tag and asset state, checksums, signatures, release and asset attestations using the provider's current verification commands, tag type, tag signature, tag SHA, and reachability from the default branch;
- exact agreement between registry and release artifact hashes for file distributions, or exact public resolution to the signed commit for a source-only distribution;
- selected documentation stable and versioned URLs, navigation, search, examples, and canonical links;
- selected website deployment SHA, domain, TLS, metadata, social card, robots, sitemap, accessibility, responsive layout, and security headers;
- active branch and tag rule state;
- the release workflow's environment and permission scope.

On GitHub, use the current `gh release verify` and `gh release verify-asset` forms when available, and also read the repository's immutable-release setting through the API. Bind every verification result to the expected repository, tag, asset name, and SHA-256. Do not treat an attestation for different bytes as release proof.

If any check fails, state the impact plainly. Do not declare completion while the advertised installation or first-use path is broken.
