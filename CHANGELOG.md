# Changelog

## Unreleased — 2026-08-04

### Added

- `skills check` / `skills report` now verify the Codex skill adapter file
  itself: a symlinked `agents/openai.yaml` warns `codex-metadata-symlink`, and
  a non-regular, binary, oversized, or invalid-UTF-8 adapter warns
  `codex-metadata-unreadable`. Readable adapters keep the existing
  `codex-metadata-unparsed` warning, and the adapter path stays recorded in
  the inventory and registry in all cases.
- Skill listing budget checks (warnings only, sourced from
  `reports/provider-review-2026-08.md`):
  - `long-listing-entry` — per skill, when combined `description` +
    `when_to_use` exceed 1,536 characters (Claude Code truncates the listing
    entry; the host-side limit is configurable via
    `skillListingMaxDescChars`). `when_to_use` is now a typed
    `SkillFrontmatter` field; skills without it are unaffected.
  - `listing-budget-estimate` — across all valid skills, when the estimated
    Codex listing (names + descriptions + paths) exceeds the 8,000-character
    fallback budget. The message states it is a fallback estimate; the real
    budget is 2% of the context window. No always-on estimate line is added,
    so within-budget repositories see unchanged `skills report` /
    skill-health.md output; over-budget repositories gain the warning in both.
- Eval workspace snapshots (`skills eval --init-workspace`) now skip files
  that are not valid UTF-8 instead of crashing mid-copy.

### Changed

- Provider registry review refreshed: `reports/provider-review-2026-08.md`
  records the 2026-08-03 platform facts (custom subagent locations for four
  providers, path-scoped instruction rules, skill listing budgets, the
  `agents/openai.yaml` adapter schema, and the OpenAI docs URL migration), and
  `PROVIDER_REGISTRY_REVIEWED` moves to `2026-08-04`. Generated output changes
  only in the provider registry `reviewed:` line.

## Unreleased — 2026-07-02

Platform-neutral redesign. The project is now a portable toolkit + agent skill
rather than a Codex-only skill. Markers, generated file paths, existing CLI
subcommands/flags, and the registry `schema_version` are unchanged.

### Added

- `providers` subcommand (text and `--json`) listing supported providers,
  bridge files, and auto-detection status.
- `skills` command group for SkillOps:
  - `skills inventory ROOT [--json]` scans direct child skills under
    `.agents/skills`.
  - `skills check ROOT` validates Agent Skills frontmatter, local references,
    and optional `evals/evals.json` manifests.
  - `skills report ROOT` and `skills sync ROOT` produce deterministic skill
    registry and health report files.
  - `skills routes ROOT` syncs compact active/watch skill routes into
    `.agents/routing.md`.
  - `skills eval ROOT --plan|--init-workspace` creates repository-local eval
    planning workspaces, and `--runner codex` can run an explicit prompt with
    explicit sandbox flags.
- `PROVIDERS` registry in `scripts/agent_context.py` as the single source of
  truth for provider knowledge; `PROFILES`, the generated provider registry,
  profile bodies, and detection all derive from it.
- Installation guide covering Codex (`.agents/skills`), Claude Code
  (`.claude/skills`), agents without a skill mechanism, and direct CLI use.
- `examples/sample-output/` (committed scaffold example) and
  `scripts/run_checks.sh` / CI running tests plus a sample-output round-trip.
- Safety regression tests: mismatched-marker refusal, dirty-tracked `.diff`
  snapshots, clean-tracked no-snapshot contract, fake-import detection; golden
  files pinning generated output.

### Changed

- **Inventory ordering** is now deterministic across platforms: directory
  traversal sorts entries, so the detected manifest/documentation/test lists
  in `core.md` and `routing.md` no longer depend on filesystem enumeration
  order (macOS and Linux previously produced different orders, which the CI
  sample-output round-trip caught). The next `scaffold` run on an existing
  repository may rewrite the managed blocks once to reorder those lists.
- **Runtime detection** (`--agent auto`) now matches confirmed environment
  variables exactly instead of substring matching, with an explicit priority
  order (`DETECT_PRIORITY`) that preserves the historical multi-hit
  precedence. Behavior differences:
  - Environments that were previously misdetected via substring matches (for
    example a `COPILOT_*` telemetry variable in a non-Copilot session) now
    fall back to `generic` or detect correctly.
  - Codex is detected via `CODEX_SANDBOX` / `CODEX_SANDBOX_NETWORK_DISABLED`,
    which are only set while sandboxing is active; unsandboxed Codex sessions
    fall back to `generic` — pass `--agent codex` explicitly.
  - Cursor, Copilot, and Antigravity have no confirmed detection variables yet
    and are selected explicitly with `--agent <name>`.
- **Generated output**: fixed leaked 4-space indentation in generated profile
  files (and in `core.md` / `routing.md` lists with more than one item), which
  Markdown rendered as code blocks. The next `scaffold` run on an existing
  repository rewrites the managed blocks once (marker-first, as usual).
- **Inventory** now excludes this tool's own `.agents/snapshots/` directory.
  Counting snapshots made repeated `scaffold` runs non-convergent: every
  update wrote a snapshot, which changed the file count, which changed
  `core.md` again. With the fix, `scaffold` reaches a fixed point on the
  second run and is a no-op afterwards.
- `detect_agent()` returns `(agent, matched_variable)` instead of a bare
  string; `scaffold --agent auto` prints what was detected and from which
  variable.
- SKILL/README/reference wording is platform-neutral; `agents/openai.yaml` is
  documented as a Codex-specific adapter that other platforms ignore.
