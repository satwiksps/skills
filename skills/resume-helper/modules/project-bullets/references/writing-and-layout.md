# Writing and layout

## Shape each achievement

Lead with the project identity: `Built a streaming ...`, `Developed an indexing ...`, or a similarly clear noun phrase in the first 4-8 words. An interviewer should understand the tool before reading its mechanism. Prefer a specific mechanism over a list of technologies.

Connect action, purpose, mechanism and result in one sentence. For subsequent bullets, lead with the actual change: Reduced, Implemented, Optimized, Eliminated, Isolated, Validated, Integrated. Match the verb to evidence: 'deployed' needs deployment evidence; 'prevented' needs a defined fault/duplication experiment; 'built' must reflect the user's contribution. Use 'extended' or 'implemented X within Y' when ownership is narrower.

Different bullets should answer different engineering questions. Examples of complementary pairs are streaming recovery plus duplicate-work elimination, incremental indexing plus refresh memory, static analysis correctness plus efficient change discovery, or constraint-based planning plus safe environment inspection. These are choices to investigate, not mandatory assignments or promised results.

Use one meaningful quantitative result per bullet. A comparison may need two numbers; avoid adding sample counts, test counts, configuration counts and versions just to look technical. Retain required scope in the sentence, then place full denominators/workload details in the evidence table. Do not reuse any result or technology from another user's examples.

Avoid vague praise, 'robust/scalable', unexplained acronyms, 'industry standard' without meaning, generic Python/CLI/automation stories, and invented business impact. A small benchmark does not imply production load, user adoption or company savings. Jargon like AC-3 or SSE is useful when central to the implementation and explainable by the user; expand it when the intended reader would otherwise miss the achievement.

## Count visible text

Use an `entry.json` with a `bullets` array of plain strings. Store literal `%`, `&`, `_`, and other visible symbols, not Markdown emphasis or LaTeX source. The helper uses Unicode code-point length including spaces/punctuation and whitespace-delimited words; it is an estimate of visible length, not font width or grapheme count.

```text
python /path/to/project-bullets/scripts/measure_text.py /path/to/entry.json --expected-count 2
```

Change the count to 3 when requested. The default 210-245 character range is advisory. If a supplied template needs shorter text, honor its layout rather than padding or shrinking typography. Preserve useful specifics over an arbitrary word-count target.

When converting existing TeX, first establish the actual visible text: `\%` counts as `%`, formatting commands add no characters, and `\href{url}{label}` displays its label. Do not pretend a generic regular expression can correctly interpret arbitrary TeX; derive from the finished plain draft or extracted/rendered output and compare.

## Verify wrapping honestly

If a resume source is present, compile/render a temporary copy with the same page size, margins, body font, font size, line spacing, bullet indentation and hyphenation settings. Read its definitions rather than guessing from a screenshot. Use its available renderer (for example pdfLaTeX for TeX or the relevant document renderer); no specific external skill is required by this package.

For the default compact target, verify exactly two natural lines, with the second occupying at least half the usable bullet line width. Use PDF text positions or the document layout model to count lines and measure the second-line span, then visually inspect a rendered page for clipping, third lines, overlap and unexpected extraction. Verify after the final wording or bolding change. Do not insert manual line breaks, negative spacing or changed typography to force a fit.

If only typography settings are supplied, an explicitly labeled minimal harness can verify that configuration. If no layout is supplied, report character/word counts and 'fit estimated; template not supplied'. An attractive harness is not proof of fitting the user's real resume. Do not install an entire typesetting stack just to avoid honestly reporting that rendering is unavailable.

For LaTeX output, supply only the project snippet unless the user asked for a full document. Escape `%`, `&`, `_`, `#`, `$`, braces and other special characters as appropriate, preserve verified links, and use the user's bullet environment. Do not invent `rbullets` if the template defines a different environment. Keep link/title/technology text out of bullet-length counts.

## Final quality pass

Check each sentence against the implementation and its evidence record. Ensure the statistic names the behavior actually timed/counted; units, denominator and comparison direction agree; scope and any material quality loss remain visible; and ownership is not inflated. Verify title, link, technologies and bullet count. Mark gaps plainly and keep hypothetical candidates outside submission-ready text.
