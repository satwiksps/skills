# Defensible project measurements

Use this reference when choosing or auditing a number. Optimize for what an interviewer can reproduce and what the implementation actually contributes.

## Select a workload and baseline

Write down the claim, metric, input corpus, and correctness invariant before timing. Prefer bundled representative examples or a documented local workload. Synthetic scenarios are useful when their construction, distribution, limits and random seed are disclosed; do not choose only easy cases after looking at results. Retain successes, failures, unsupported cases, and degraded quality separately.

A baseline must perform the same useful work with comparable semantics and inputs. State whether it is an earlier revision, full recomputation, a simple implementation, unkeyed requests, or an established alternative. Avoid deliberately slow code, needless repeated imports, disabled optimizations, uneven batching, different hardware or hidden quality reductions. Both arms must have the same validation boundary. A simpler algorithm can be the strongest fair baseline on small real domains.

When a comparison is not fair or informative, measure an absolute result instead: end-to-end latency for a fixed workload, sustained throughput with bounded error, or peak memory while preserving output. Do not call an absolute latency a speedup. A verified workload size is useful only when tied to demonstrated behavior; test counts and feature counts are weak substitutes for results.

## Repeat and measure the right boundary

- Time the behavior named in the bullet. Distinguish solver-only, in-process handler, subprocess CLI, API round trip, model load, and complete job duration.
- Use several measured repetitions after a declared warmup; five to ten alternating/rotated paired runs are a practical starting point, not a universal statistical guarantee. Increase samples when variation changes the conclusion. Report a median and spread; avoid selecting the best run. Tail percentiles require enough independent observations to be meaningful: with very few samples, use a median and range instead of promoting the maximum as p95.
- Distinguish fresh interpreter/process, warm dependency cache, warm filesystem, warm model, and result-cache hits. A fresh process does not imply cold disk. Do not silently mix states or exclude failed/slow runs. Record any justified exclusions before presenting the result.
- Separate repeats of the same input from genuinely different inputs. For unequal case sizes, report whether you pooled observations, averaged per-case rates, or divided totals; these answer different questions. For paired reductions, distinguish the median of per-pair reductions from the reduction of medians.
- Keep timed runs free of other intentional heavy tests/benchmarks. Independent code review and log inspection can run concurrently. Avoid treating noisy background load as a claimed project regression.
- For operation counts, instrument the real boundary: backend generations, external calls, cache misses, bytes read, or records processed. Check whether saved counted work is offset elsewhere. Fewer branches/requests/allocations alone do not establish runtime or total resource savings.
- For memory, name the counter: peak process resident/working set, allocation tracer, device allocation, or total machine usage. Include/exclude child processes consistently; do not call Python-only tracemalloc output total process memory. Avoid summing sequential process peaks as if simultaneous.

The bundled `scripts/summarize_samples.py` accepts raw numeric arrays and reports median, nearest-rank p95, range and signed ratio-of-medians changes. It does not run benchmarks, establish statistical significance, or decide whether lower is better. Keep raw samples and perform independent spot checks.

## Preserve correctness and quality

Use an independent oracle or reference output where practical. Check every timed output, not just one untimed pilot. A solver oracle using the same constraints proves modeled consistency, not the truth/completeness of external compatibility facts. A mocked service demonstrates orchestration under that mock, not live service performance.

For failure handling, name the fault model: dropped connection, killed process, timeout, malformed input, or duplicate request. Record whether output is replayed, lost, repeated, reordered, or recomputed. Do not infer production availability, zero data loss, exactly-once effects, or mean time to recovery from a passing unit test.

For seeded detection, preserve positive/negative labels and a confusion matrix. Recall is TP/(TP+FN), precision is TP/(TP+FP); accuracy requires the correct total labeled denominator. A seeded detection rate is not real-world accuracy. Perfect observed results can be reported on their finite workload, but avoid universal 100%/0% assertions and do not nudge numbers to look more believable.

For retrieval/ML, keep the same documents, queries, labels and evaluation definition. Report quality tradeoffs: a fall in nDCG is a degradation, even if recall is unchanged. Faster processing with lower quality is not a like-for-like speedup unless the tradeoff is explicit.

For LLM/RAG cost claims, distinguish characters, bytes, chunks, requests, tokens submitted, tokens billed, and backend generations. Count tokens with a named tokenizer/version/model convention. Cached text or embeddings are not automatically saved billable tokens. Monetary savings require measured volume plus an explicitly sourced price and pricing assumptions; call that a calculation, not observed billing savings.

## Calculations and presentation

- Relative reduction: `(baseline - candidate) / baseline * 100`, with nonzero baseline. Preserve a negative result when the candidate is worse.
- Relative increase: `(candidate - baseline) / baseline * 100`.
- Speedup factor for equal-work runtimes: `baseline_time / candidate_time`. A throughput ratio has the opposite orientation for improvement.
- Percentage-point difference: `candidate_percentage - baseline_percentage`. It is not the relative percentage change.
- Throughput: successful work / elapsed wall time, with concurrency, work unit and failures stated.
- p95: document the quantile method. The helper uses sorted observation at one-based index `ceil(0.95 * n)`; do not silently swap percentile conventions.

Do not divide by zero, include booleans/nonfinite values as samples, round before calculations, clamp regressions away, or substitute predicted values for measurements. Choose display precision consistent with variability. Valid perfect results need honest scope, not invented fractional outcomes.

## Evidence record

Keep an `evidence.md` dossier plus raw results and runnable scripts in a dedicated local output directory. For each candidate bullet, record:

| Field | Required content |
|---|---|
| Identity | Project path, revision, dirty state; hashes/diff context for relevant uncommitted code |
| Ownership | What contribution the user can claim, including team/inherited-code limits when material |
| Claim/status | Exact proposed statement; measured, recorded, calculated, estimate, or gap |
| Implementation | Relevant source paths/lines and whether the behavior is production code, optional integration, or experiment |
| Reproduction | Exact command, working directory, relevant environment variables, required dependency/service versions, input files and generation seed |
| Workload | Input sizes/distribution, scenario selection, concurrency, warmup/repeats, cold/warm state, timed boundary |
| Baseline | Comparator implementation, why equivalent, and named denominator; use 'none: absolute result' when appropriate |
| Environment | OS, runtime, CPU/RAM, GPU/model if used, dependency versions and material configuration |
| Raw evidence | Every observation, process exit status, outputs/log paths, failed/unsupported cases and exclusions |
| Verification | Output/oracle/quality invariants; tested fields and known non-equivalent fields |
| Arithmetic | Statistic, aggregation rule, units, exact values, formula, rounding |
| Limits | Local/synthetic scope, missing hardware/services, quality losses, uncertainty; no unsupported production extrapolation |
| Interview | One plain sentence explaining the result and its denominator/baseline |

Record relevant setup and run commands so another person can reproduce the result without the original agent's environment. Do not bundle secrets, proprietary data, private resume details or local evidence into a public skill release. Evidence belongs to the user's assessment output, not the reusable skill directory.

If blocked, keep the actual error and supply a runnable project-specific validation command. Reuse documented metrics only when their provenance, workload and relevant version can be traced. A README claim without underlying evidence is a lead to investigate, not a result to copy.
