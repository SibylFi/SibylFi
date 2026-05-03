# /specs/prompts/

This directory holds AI-coding prompts used during the SibylFi build. Per the
`hackathon-compliance` skill, ETHGlobal's AI involvement clause requires
disclosure of how AI assistants were used in the project.

## What goes here

- Cursor / Claude Code prompts that resulted in non-trivial code changes
- Architecture-discussion prompts that shaped major decisions
- Any prompt > a single sentence that produced > 50 lines of output

## What does NOT go here

- Trivial autocomplete uses (e.g., asking Claude to rename a variable)
- Read-only queries ("explain what this function does")
- Prompts that produced output rejected by the human reviewer

## Naming convention

`<YYYY-MM-DD>-<short-description>.md`

Examples:
- `2026-04-29-validator-algorithm-initial.md`
- `2026-05-02-frontend-leaderboard-reorder-animation.md`
- `2026-05-04-x402-python-client-fallback.md`

## Required fields per prompt file

```markdown
# <title>

**Author:** <teammate name>
**Date:** YYYY-MM-DD
**Tool:** Cursor / Claude Code / Anthropic API
**Files affected:** <list>

## Prompt
<the prompt verbatim>

## Outcome
<2-3 sentences: was the output used, modified, or rejected?>
```

This isn't bureaucracy — this is what protects the team from disqualification.
The reviewers can spot empty `/specs/prompts/` folders instantly.
