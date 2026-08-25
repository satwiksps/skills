# README, documentation, brand, and website

Use this reference during the Phase 1 decision pass to specify the public surface, without creating it. Execute it only after the product contract is approved and derive public evidence from working software, not from an incomplete implementation. Documentation and a landing site are defaults; the plan may waive either only with a concrete product reason and a replacement discovery path.

## One coherent visual system

Define a small brand brief before drawing assets:

- project name, pronunciation if needed, and one-sentence value proposition;
- target user's context and the project's most important mechanism;
- one restrained accent color, neutral background and text colors, and accessible contrast;
- a project-specific visual metaphor derived from the actual mechanism;
- wordmark, compact mark, banner composition, social-card composition, and icon behavior at small sizes.

Avoid generic robot heads, glowing orbs, random glass panels, stock isometric cubes, decorative charts, and gradients unrelated to the domain. A dark technical style is acceptable only when it matches the product and remains readable. Use system fonts or bundled fonts so the site does not depend on an avoidable remote request.

Keep an editable source for every asset. Add any private generation brief, reference image, or source capture to the approved private-input inventory and preserve it outside every public repository. Export a clean final file. Inventory raster EXIF, XMP, ICC, text chunks, GPS, author, prompt, software, filename, and path metadata; retain only fields approved by the plan, strip the rest, and verify the result with a pinned local metadata tool. Inspect SVG/XML comments, processing instructions, editor namespaces, embedded files, scripts, links, and metadata blocks; keep only accessible `<title>` and `<desc>` content plus deliberate public metadata. Then verify dimensions, color mode, compression, transparent edges, legibility, crop behavior, and private-content fingerprints before commit and packaging.

Create and keep consistent across selected surfaces:

- a full-width README banner, preferably an editable SVG around a 4:1 aspect ratio;
- a simple mark that remains clear at favicon size;
- matching website and documentation favicons when those surfaces are selected;
- a social preview image at 1200 by 630 unless the selected platform documents a different requirement;
- explicit Open Graph and Twitter metadata whose declared dimensions match the real file.

Do not reuse another project's name, mark, illustration, output, numbers, or copy. Reuse the discipline: wordmark plus mechanism-specific illustration, high contrast, restrained palette, and shared visual language.

## README contract

Center only the masthead. A reliable structure is:

```html
<div align="center">
  <h1 align="center">Project name</h1>
  <img src="https://raw.githubusercontent.com/OWNER/REPO/main/assets/banner.svg" alt="Project name" width="100%">
  <p>One precise sentence describing the outcome and mechanism.</p>
  <p>Documentation &middot; Quick start &middot; API or CLI &middot; Architecture &middot; Contributing</p>
  <p>Only badges whose targets exist and currently pass</p>
</div>
```

Use an absolute raw-repository banner URL when the README must render on a package registry. Keep meaningful `alt` text. Verify every badge target and remove badges that do not help a user decide compatibility, trust, or release state.

After the closing `div`, return to normal left-aligned Markdown. Adapt the body to the project, but normally cover this order:

1. The specific user and supported deployment.
2. An at-a-glance capability and boundary table.
3. Why the problem exists and how this implementation approaches it.
4. Implemented scope and explicit limitations.
5. Installation from the public package or artifact.
6. Uninstall steps and retained data.
7. A fully copyable first-use workflow that works offline when the product claims offline behavior.
8. Expected output or an observable success condition captured from the artifact.
9. Configuration and safety warnings.
10. Supported providers, backends, runtimes, and platforms.
11. Reproducible results, if there are defensible measurements, with non-generalization notes.
12. Architecture or design invariants that contributors must preserve.
13. Documentation map, upgrades or migrations, fit and non-fit guidance.
14. Contribution, security, and Apache-2.0 license links.

Apply one publication-state rule across the README, documentation, and website. Never show a registry badge or package link before its target exists. A release-candidate surface may contain the final registry install command only after the namespace, package metadata, trusted-publisher binding, and authorized publication path are verified; label the version as pending until it is public. Otherwise show a tested source or local-artifact install and defer the registry command. Verify the public command immediately after publication. Add any deferred command, badge, or provider link through the first post-release pull request, then rerun the affected install, link, docs-build, site-build, and deployed-page checks.

## Documentation architecture

When documentation is selected, it should help a new user, an operator, an integrator, and a contributor without duplicating the README. If it is waived, follow the approved replacement discovery path instead of creating an empty docs tree.

Use only relevant sections:

```text
docs/
|-- index
|-- getting-started/
|   |-- installation
|   |-- quickstart
|   `-- core-model
|-- guides/
|-- concepts/
|-- reference/
|-- operations/
|-- compatibility
|-- limitations
`-- development/
    |-- setup
    |-- testing
    |-- documentation
    |-- security
    `-- release-process
```

- The docs index is a portal with a crisp scope, publication-state-correct install snippet, real workflow, audience routes, and supported deployment.
- Getting started reaches a successful result quickly and states prerequisites.
- Guides are task-oriented and include failure and recovery paths.
- Concepts explain invariants and tradeoffs without repeating reference material.
- Reference pages list every stable flag, method, field, default, exit code, schema, and compatibility guarantee.
- Operations covers state, backup, restore, capacity, upgrade, rollback, observability, and cleanup when applicable.
- Limitations is an honest risk register, not a roadmap disguised as documentation.
- Development docs contain exact locked setup and full verification commands.
- The root `SECURITY.md` is authoritative; deeper security docs should link to it rather than conflict with it.
- Include the root changelog in the docs build instead of maintaining a copy.

Use Read the Docs when approved. Check its current official configuration reference at execution time. Keep `.readthedocs.yaml` at the repository root, use schema version 2, pin a supported build image and toolchain, install locked documentation dependencies, build with warnings as errors, and test the same command in CI. Sphinx with MyST is a strong choice for Python API documentation; MkDocs, Docusaurus, rustdoc, Javadoc, DocFX, or another native system can be better for other ecosystems. Do not force a tool that produces weaker reference material.

Share the site palette, mark, typography, and link structure with the docs without hiding normal documentation navigation. Test dark and light modes if both are offered. Inspect wide and narrow layouts, code blocks, tables, callouts, search, headings, deep links, edit links, and canonical URLs.

## Website blueprint

When a website is selected, use a separate, private website package directory when the product package should not carry frontend dependencies. If it is waived, do not add a frontend scaffold. Next.js with TypeScript and Tailwind is a good default for a polished static or server-rendered landing site, but the approved constraints may favor Astro, Eleventy, plain HTML and CSS, or another framework.

Build one focused page before considering multiple marketing routes:

1. Skip link, responsive navigation, and visible product identity.
2. Outcome-led hero with one primary action and one documentation or repository action.
3. Authentic terminal, API, or UI evidence from the working artifact.
4. A concrete workflow or data flow.
5. Explanation of the problem and the implementation's boundaries.
6. Capability or compatibility matrix.
7. Architecture or trust boundary.
8. Copyable installation and first-use path.
9. License, version, selected docs, security, contributing, verified package when public, and repository links.

Do not add fake customer logos, testimonials, download counts, stars, performance claims, pricing, enterprise sections, or generic feature cards. Every section must teach the product or help the user act.

Centralize site identity and validated URLs. Accept only absolute HTTPS production URLs without embedded credentials. If no canonical production URL exists, omit canonical and social metadata and prevent robots or sitemap output from advertising localhost.

Provide:

- accurate title, description, application name, canonical URL, Open Graph, Twitter card, theme color, icons, robots, and sitemap;
- semantic landmarks and heading order;
- keyboard operation, visible focus, screen-reader labels, reduced-motion behavior, forced-color support, and responsive overflow;
- strict transport, content-type, framing, referrer, and permissions headers appropriate to the host;
- a narrow content security policy that matches actual assets and scripts;
- no secret or server-only data in public environment variables;
- production-only deployment behavior when that is the approved policy.

Use components only for real interaction or repetition. A copy button needs an accessible label and status announcement. A mobile menu needs Escape, outside-click, focus restoration, and correct expanded state.

## Website verification

For a selected website, run the locked install, dependency audit, lint, format check, type check, unit or component tests, production build, and a production-server smoke test. The smoke test should allocate a free local port and verify at least:

- home page status, title, primary heading, main landmark, and essential product copy;
- security headers;
- robots and sitemap behavior with and without a real canonical URL;
- favicon and social-card status plus MIME type;
- selected documentation, repository, currently valid package, security, and contribution links;
- copyable installation text;
- intentional 404 behavior and clean server shutdown.

Render screenshots at representative desktop and mobile widths. Inspect them visually for clipping, overflow, unreadable contrast, broken navigation, asset crops, awkward empty space, and generic-looking composition. Exercise keyboard navigation and run an accessibility audit. Test the actual deployment after publication.

For Vercel, confirm the production branch, website root directory, framework detection, environment variables, build command, and domain. If previews are intentionally disabled, encode that policy in current supported configuration and verify it remotely. If previews are enabled, make sure fork protection prevents secret exposure. Production promotion should follow the project's CI policy rather than making a failed commit live.
