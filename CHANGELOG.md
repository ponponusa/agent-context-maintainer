# Changelog

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
