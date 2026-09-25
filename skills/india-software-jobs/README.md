# India Software Jobs

Find software jobs and internships in India, matched to your experience and preferences. Supports students, freshers and experienced engineers.

## Start

Install this directory using the [repository instructions](../../README.md#install-a-skill), then open a private tracker folder in your agent and say:

```text
Use the india-software-jobs skill and /setup in this folder.
```

Setup creates `me.md`, `source.md`, `jobs.md` and `internships.md`. Fill whichever profile fields matter to you, including roles, experience, salary basis, company preferences and a local resume path. You can edit `me.md` anytime; blank fields are fine. The agent asks before saving new preferences learned later in chat.

Sign in to the sources you want it to read, such as LinkedIn, Naukri, Wellfound, Indeed and Telegram. Available access depends on your agent's browser/connectors. Public sources work without connecting everything. Never paste login codes or credentials into chat.

## Commands

| Request | Result |
| --- | --- |
| `/setup` | Prepare the tracker and access; fill optional profile details. |
| `/scrap` | Research new openings, Telegram first, then portals and job boards. |
| `/validate` | Check saved openings and strike confirmed-closed rows. Never delete them. |
| `/repair` | Fix source links, find new sources and retire persistently bad ones. |

In Codex, use `$india-software-jobs /scrap`; setup can also create workspace `$scrap`, `$validate`, `$repair` and `$setup` skills. Claude Code can use the workspace `/scrap` shortcuts. If your app doesn't expose shortcuts, say “Use india-software-jobs to validate my saved jobs.”

## What you get

- Separate job/internship lists, only searching the types you want.
- Applied checkbox, match out of 100, company, role/ID and helpful apply/source link.
- New discoveries grouped by date and time, latest first; duplicates kept out.
- Unverified links labelled in each row; uncertain availability kept visible.
- Short reports of additions, closures, source changes and remaining gaps.

The source seed includes Telegram channels, employer portals and job boards. It needs live checking and may lean toward fresher alerts; `/repair` adapts it to your profile. A skill cannot guarantee every opening or bypass blocked sites. No automatic applications or schedules. Resume and tracker data stay local unless you separately authorize sharing.

## Requirements and checks

An agent with local file access and web research; a connected browser improves signed-in coverage. The optional file helper needs Python 3.11+ and no external packages. It manages setup, deduplication and closed-row formatting; it is **not a standalone scraper**. Research is performed by the agent using its available tools. Telegram API collection requires a separately configured client if public/browser access is insufficient.

```sh
python -m unittest discover -s skills/india-software-jobs/tests -v
```

Tests cover file safety, duplicate handling, closure evidence and preservation of Applied marks. They do not establish live portal coverage. See [workflow details](references/workflow.md) and [file/helper reference](references/tracking.md) for operational details.
