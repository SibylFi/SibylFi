# Agent Policy

Agents assist with editing files, running checks, and preparing local commits.
The human owner controls the remote.

## Project context first

Before creating or editing code, read `CLAUDE.md` and load the relevant
`.claude/skills/<skill-name>/SKILL.md` files for the task. Keep every change
anchored to the Signal Market lifecycle (research → purchase → risk → trade →
validate → reputation).

For 0G-related work, check `https://www.0gskills.com/SKILL.md` first; for
coding also read `https://0gskills.com/ship/SKILL.md`, then verify live details
against official 0G docs.

## Git authority

- **Never run `git push`, `git push --tags`, `git push --force`**, or any
  command that updates a remote branch or tag.
- **Never merge to `main`**, publish a branch, open a PR, or change remote
  settings unless the human explicitly asks for that specific remote action.
- **Local commits are allowed only when the human asks for a commit.**
- The human owner performs all pushes to `main`.

## Commit shape

When asked to commit:

- One commit = one reviewable intent.
- Do not mix frontend, backend, contracts, docs, or assets unless it is a
  coordinated milestone the human has described.
- Inspect `git status` and the staged diff before committing.
- Never include `.env`, private keys, generated caches, or local machine noise.
- Use descriptive scope-prefixed messages, e.g.:
  `validator: add TWAP window config`
  `frontend: show risk rejection reason inline`
  `contracts: redeploy ValidatorSettle after ABI change`

## AI transparency

- Add or update `AI_USAGE.md` for any meaningful AI-assisted code, docs, or
  assets.
- Save important prompts or prompt summaries in `specs/prompts/`.
- Distinguish human-authored design decisions from AI-assisted implementation.
