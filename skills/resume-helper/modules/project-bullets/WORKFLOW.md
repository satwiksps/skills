---
name: project-bullets
description: Inspect local software projects, run relevant tests and fair benchmarks, and write two or three evidence-backed resume bullets with reproducible metrics. Use when turning project implementations into resume achievements or strengthening existing project bullets.
license: MIT
---

# Project Bullets

Turn implemented engineering into concise, interview-defensible resume entries. Investigate, verify, measure, and finish the writing in the same task. Do not stop at a benchmark proposal when local execution is practical.

## Inputs and defaults

Accept a project path or several paths, a choice of **two or three bullets per project**, and optional existing bullets, resume/template, target role, technology count, or execution constraints. Understand natural-language requests and prompt arguments such as `--bullets 3`, `--resume "path"`, and `--role "backend SDE"`; these are prompt conventions, not executable CLI flags.

- Default to **two bullets**, **five core technologies**, and general SDE positioning when unspecified. Follow explicit user choices.
- Infer the intended project from context when unambiguous; ask for the path if it cannot be identified. Ask about ownership only when ambiguity materially changes the claims. A clone's presence or Git author name alone does not establish authorship of all its code.
- If no resume or explicit typography settings are supplied, use the compact writing defaults below and mark layout **estimated**. Do not impose a particular person's typography on other users.
- Proceed autonomously with reasonable implementation and measurement choices. Ordinary temporary local verification is part of this request; no separate permission ritual is needed. Respect actual tool permissions and explicit execution limits.

## Inspect what exists

Read applicable `AGENTS.md` instructions. Record repository revision, dirty state, and supplied resume hash. Inspect entry points, central algorithms/data structures, APIs and interfaces, dependencies, tests, examples, benchmarks, CI, and relevant documentation. Prioritize code paths connected to potential achievements; a large repository need not be read indiscriminately.

Identify who would use the project, the problem it solves, what works, and what is a stub, plan, example, generated artifact, or optional integration. Verify README and old resume claims against implementation and evidence. Do not treat counts of tests, formats, flags, supported constraints, or files as engineering impact. Passing tests support behavior, not real-world accuracy or reliability.

Preserve existing changes and resume files. Keep experiments, dependencies, datasets, logs, and rendering copies in a dedicated evidence directory outside the project by default. Inspect scripts for side effects before running them; use isolated environments and temporary test outputs. Do not implement missing product features, commit, publish, upload private source/data, execute generated deployment/install plans, or incur paid API/cloud work solely to obtain stronger bullets. Existing user authorization still applies; isolate ordinary dependency setup rather than changing global environments. Cap experimental workloads and retain failures when a required service, tool, or dependency is unavailable.

## Select and obtain evidence

Choose a different substantial contribution for each bullet. For multiple projects, choose complementary primary capabilities. A three-bullet request needs a third contribution, not the same latency benchmark described three ways.

Before designing experiments, read [references/measurement.md](references/measurement.md). Prefer fresh measurements, then traceable existing results, then transparent calculations from verified facts. Choose outcomes relevant to the implementation: end-to-end latency, throughput, peak memory, eliminated backend work, recovery behavior, or correctness on a defined workload. A modest absolute result is better than a misleading percentage.

Run relevant existing tests/examples and a small reproducible experiment when needed. Use equivalent inputs and behavior for a fair baseline; repeat timing runs, preserve correctness checks, document cold/warm state, and retain adverse results. Do not run competing timed experiments concurrently. Look beyond convenient counters: fewer search branches can still mean more total work and slower execution. Do not compare a cached replay with fresh computation without explicitly limiting the claim to replay/retry behavior.

For **every proposed number**, keep an evidence record with command and working directory, source revision/dirty state, workload and seed, baseline, raw observations, environment, statistic and calculation, correctness check, and limitations. Store full records and raw outputs locally; keep only concise explanations beside the final resume text. Reproduction commands must work with the supplied artifacts and identify any required unavailable service.

Label metric status as **measured**, **recorded** (traceable pre-existing result), **calculated**, **estimate**, or **gap**. Estimates belong in a separate optional candidate section with assumptions and a validation command, never among submission-ready achievements. Do not claim production users, savings, adoption, deployment, or prevented incidents without evidence.

If an honest metric is unavailable, use a verified workload/scope result when it communicates meaningful behavior; otherwise flag that bullet's measurement gap and give a runnable validation command. If fewer distinct achievements are supported than requested, deliver the supported bullets and explicitly identify the missing slot. Never manufacture a number or split a weak claim merely to reach the requested count.

## Write and fit the entry

Read [references/writing-and-layout.md](references/writing-and-layout.md) before drafting. Each bullet should describe one coherent achievement with a strong action verb, a specific mechanism, and a meaningful supported outcome.

- **Bullet 1:** the first 4-8 words explain what the project is, for example, `Built an offline GPU dependency resolver ...`. Then connect purpose, mechanism, and result.
- **Bullet 2:** a distinct optimization, correctness mechanism, reliability improvement, or integration with its own outcome.
- **Bullet 3, when requested:** another substantial verified contribution; avoid repeating the same metric or architecture in different words.
- Prefer one quantitative result per bullet, or two numbers to express a necessary comparison. Keep workload/denominator detail in the evidence note when it would overload the sentence. Qualify synthetic/local/seeded claims within the bullet when omitting that scope would mislead.
- Default drafting target: **210-245 visible characters**, preferably **220-235**; approximately 30-40 words is secondary. User length limits and actual rendered fit take precedence. Do not pad content to reach a count.
- Select the requested number of genuinely central technologies from the implementation. Avoid incidental dev tools or a deployment/framework claim based solely on an optional integration or generated file. If fewer technologies are substantive, explain the gap rather than invent a stack.

Maintain plain visible bullet strings in `entry.json` before adding Markdown or LaTeX markup. Count them with `scripts/measure_text.py` or equivalent code. Do not count LaTeX commands or treat escaped symbols as two visible characters. This helper counts plain text only; it does not parse TeX or verify layout.

When an editable resume/template and a renderer are available, use a temporary copy. Preserve its fonts, margins, spacing, and bullet indentation; compile/render, inspect the output, and adjust wording naturally. If the requested style is the default compact format, aim for exactly **two lines per bullet**, with the second at least **50% occupied**, no third line, manual line breaks, or spacing tricks. Only claim verified fit for the supplied or explicitly chosen template. A source-free harness verifies its own layout, not the user's unseen resume. If compilation is unavailable, clearly label fit estimated.

## Deliver

Return, in this order, unless the user requests a simpler presentation:

1. A short positioning table: project, capability, and suggested order when comparing projects.
2. The finished entry: concise descriptive title, verified repository link if available, selected technologies, and exactly the requested supported bullets. Keep evidence and counts outside resume text.
3. A compact evidence table per bullet: character/word counts, verified or estimated fit, metric status, source/reproduction command, baseline and workload. Add one interview sentence per number. Keep estimates and gaps clearly separate.
4. Matching project-only LaTeX snippets when a LaTeX resume was supplied/requested; reuse its environment (such as `rbullets`), `\textbf{}`, `\href{}`, and `\textit{}` where appropriate. Otherwise provide copyable plain text/Markdown. Do not rewrite the full resume without a request.

Link the local evidence directory or dossier, summarize relevant checks and material limitations, and verify that the project worktree and original resume are preserved. Never suggest that small scripts validate the truth of a claim: their arithmetic and length checks supplement source review, fair experimental design, and correctness verification.
