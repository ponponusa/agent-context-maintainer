# Core Agent Context

<!-- agent-context-maintainer:begin -->
## Repository Snapshot

- Root: `sample-output`
- Detected languages: Markdown
- Approximate tracked context files scanned: 17

## Detected Manifests

- `package.json`

## Detected Documentation

- `AGENTS.md`
- `CLAUDE.md`
- `GEMINI.md`
- `README.md`
- `.github/copilot-instructions.md`

## Context Boundaries

- Keep shared rules in this file.
- Keep provider-specific behavior in `.agents/profiles/`.
- Keep task-specific procedures in `.agents/skills/*/SKILL.md`.
- Do not copy secrets, credentials, raw logs, private keys, or `.env*` values into context files.

## Editing Rules

- Preserve unrelated user changes.
- Prefer small patches that follow existing repository style.
- Update public-facing docs when private planning changes affect public behavior.

## Validation

- Prefer focused validation for the changed slice.
- Record exact commands run and any failures that appear unrelated.

## Handoff Notes

- Leave durable restart notes when work spans multiple sessions.
- Point future agents to the most current implementation or planning checkpoint.
<!-- agent-context-maintainer:end -->