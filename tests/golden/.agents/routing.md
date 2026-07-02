# Agent Routing

<!-- agent-context-maintainer:begin -->
## Universal First Reads

- `AGENTS.md`
- `.agents/core.md`
- Matching provider profile in `.agents/profiles/`

## Task Routes

- Code review: inspect changed files first, then relevant tests and docs.
- Implementation: inspect manifests, existing patterns, and nearest tests before editing.
- Documentation: reconcile private planning docs with public docs when both exist.
- Security or privacy: read security guidance before changing storage, logging, sync, or agent-context behavior.
- New repeated workflow: create or update `.agents/skills/<task>/SKILL.md`.

## Detected Tests

- No obvious tests detected. Identify the narrowest available validation manually.

## Missing Context Rule

If required context is absent, state the gap clearly, make the safest local assumption, and avoid broad rewrites.
<!-- agent-context-maintainer:end -->
