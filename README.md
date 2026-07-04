# Agent Context Maintainer

`agent-context-maintainer` is a portable toolkit and agent skill for creating and maintaining repository-local instructions for AI coding agents.

It inspects a target repository, creates a small layered context structure, and keeps generated content bounded so future agents can update it safely. It works the same whether it is driven by Codex, Claude Code, Gemini, Copilot, Cursor, another agent, or a human at a terminal.

## When to Use This

This tool provides structure, update safety, and secret-handling boundaries — not the repository-specific content itself. Its value scales with how many tools, repositories, and people share the same instructions. It earns its footprint when at least one of these is true:

- **Multiple AI tools work in the same repository.** Two or more of Codex, Claude Code, Gemini CLI, Copilot, or Cursor read instructions from different file names, and you want one source of truth instead of hand-synchronized copies.
- **You maintain several repositories** and want the same context structure, and the same scaffold/check commands, in every one of them.
- **Agents or teammates regenerate instruction files**, and you need a machine-enforced guarantee that hand-written rules survive updates.
- **Instruction files keep drifting from the code**, and you want the inventory-derived sections refreshed by a command instead of by memory.

When none of these hold, skip it:

- **A single tool on a single repository** is better served by one hand-written `CLAUDE.md` or `AGENTS.md`. The layered structure adds indirection you are not using, and most of the seven provider profiles will sit unused.
- **The instructions that matter are repository-specific judgment** — architecture rules, workflow conventions, review policy. This tool cannot write that content for you; if nobody will fill in the hand-written sections, the scaffold alone adds little.
- **Your platforms already read `AGENTS.md` directly** and you have no per-provider differences. A plain `AGENTS.md` may be enough; the bridge files exist for today's inconsistent loading contracts and lose value as platforms converge on the standard.

## What It Creates

```text
AGENTS.md
CLAUDE.md
GEMINI.md
.github/
  copilot-instructions.md
.gemini/
  settings.json
.agents/
  core.md
  routing.md
  provider-registry.yaml
  profiles/
    codex.md
    claude.md
    gemini.md
    cursor.md
    copilot.md
    antigravity.md
    generic.md
  skills/
```

`AGENTS.md` stays small. `CLAUDE.md`, `GEMINI.md`, and `.github/copilot-instructions.md` act as provider bridges so tools can find the same shared source of truth without duplicating policy. Shared policy lives in `.agents/core.md`, task routing lives in `.agents/routing.md`, provider/model differences live in `.agents/profiles/`, and `.agents/provider-registry.yaml` records bridge files and source URLs.

See [examples/sample-output/](examples/sample-output/) for a complete generated example. This repository itself deliberately has no `AGENTS.md` or `.agents/` at its root: the repository *is* the distributable skill, and keeping generated artifacts out of the package keeps skill installs clean.

## Installation

The core is a single dependency-free Python script (`scripts/agent_context.py`, Python 3.9+), so every integration below is "put this folder somewhere and run the script".

**Codex** — place this folder in a skills directory. Codex discovers skills from `.agents/skills` at repo scope (`<repo>/.agents/skills/agent-context-maintainer/`) or user scope (`~/.agents/skills/agent-context-maintainer/`). Since this tool itself creates `.agents/skills/` in target repositories, you can self-host it there. Prefer the user scope: with a repo-scope install, files bundled with the skill (`examples/`, `tests/`) show up in that repository's own inventory as docs/tests.

**Claude Code** — place this folder at `~/.claude/skills/agent-context-maintainer/` (personal) or `<repo>/.claude/skills/agent-context-maintainer/` (project).

**Agents without a skill mechanism** — check the folder out anywhere and point the agent at the script from your repository instructions, for example: "To maintain agent context files, run `python3 <path>/scripts/agent_context.py scaffold . --agent <name>` and `check .`".

**Humans** — run the CLI directly; see Quick Start.

Installation paths were verified against the platform documentation on 2026-07-02; sources are recorded in `reports/provider-review-2026-07.md`.

## Quick Start

From this folder:

```bash
python3 scripts/agent_context.py providers
python3 scripts/agent_context.py inventory /path/to/repo
python3 scripts/agent_context.py inventory /path/to/repo --json --explain-skips
python3 scripts/agent_context.py scaffold /path/to/repo --agent auto
python3 scripts/agent_context.py check /path/to/repo
python3 scripts/agent_context.py skills inventory /path/to/repo --json
python3 scripts/agent_context.py skills check /path/to/repo
python3 scripts/agent_context.py skills sync /path/to/repo
```

`providers` lists supported providers, their bridge files, and whether they can be auto-detected. Use `--agent codex`, `--agent claude`, `--agent gemini`, `--agent cursor`, `--agent copilot`, `--agent antigravity`, or `--agent generic` to generate a different active profile.

`--agent auto` detects the runtime from environment variables that were confirmed against first-party sources (see `reports/provider-review-2026-07.md`) and prints what it detected. Detection is deliberately conservative: unknown environments fall back to `generic`, and some providers can only be selected explicitly. Codex in particular sets its variables only while sandboxing is active, so pass `--agent codex` when detection falls back.

`scaffold` supports three safety controls:

- `--dry-run`: show planned writes without changing files.
- `--append-generated-block`: preserve an existing unmarked Markdown file and append a managed block.
- `--force-recreate`: explicitly replace an existing scaffold target that has no generated marker.

## SkillOps

The nested `skills` command group audits and maintains repository-local Agent Skills under `.agents/skills/`.

```bash
python3 scripts/agent_context.py skills inventory /path/to/repo
python3 scripts/agent_context.py skills inventory /path/to/repo --json
python3 scripts/agent_context.py skills check /path/to/repo
python3 scripts/agent_context.py skills report /path/to/repo
python3 scripts/agent_context.py skills sync /path/to/repo
python3 scripts/agent_context.py skills routes /path/to/repo
python3 scripts/agent_context.py skills eval /path/to/repo --skill code-review --plan
python3 scripts/agent_context.py skills eval /path/to/repo --skill code-review --init-workspace
```

`skills inventory` scans only direct child directories under `ROOT/.agents/skills/`, then validates the `SKILL.md` inside each one. It parses a safe dependency-free frontmatter subset, validates required Agent Skills fields, checks safe local references, validates `evals/evals.json` when present, and reports symlinked skill directories without following them. Missing evals are warnings only; valid skills default to `active`.

`skills sync` writes `.agents/skill-registry.yaml` and `.agents/skill-reports/skill-health.md` with deterministic content and generated markers. It preserves human content outside managed blocks and refuses unmarked files by default. `skills routes` adds compact active/watch skill routes to `.agents/routing.md` without copying skill bodies. `skills eval --init-workspace` creates local planning workspaces under `.agents/skill-workspaces/`; it does not run Codex unless `--runner codex` is explicitly provided with a prompt and output path.

Codex eval execution uses `codex exec --json --sandbox ...` and writes JSONL trace output only under `.agents/skill-workspaces/`. Prefer `--sandbox read-only` or `--sandbox workspace-write`. `--sandbox danger-full-access` also requires `--i-understand-danger` and is suitable only for isolated CI/container environments. `--full-auto` is a deprecated legacy alias and should not be used for new automation.

## Safety

The inventory skips common secrets, keys, dependency caches, build outputs, local databases, and raw logs. Generated context should describe safety boundaries, not copy sensitive values.

Generated Markdown sections are wrapped with:

```md
<!-- agent-context-maintainer:begin -->
...
<!-- agent-context-maintainer:end -->
```

The updater replaces only the marked block when both markers exist, preserving hand-written content outside the markers.

Markers are recognized only as standalone lines outside Markdown code fences.

When `scaffold` runs, existing marked files are updated marker-first: only the generated block is replaced, and hand-written content outside the markers is preserved. Existing unmarked Markdown files are refused by default; pass `--append-generated-block` to add a managed block or `--force-recreate` to replace them. Generated-block changes that are not recoverable from git are snapshotted under `.agents/snapshots/agent-context-maintainer/` before they are overwritten. Existing `.gemini/settings.json` files are merged by adding required bridge keys while preserving other settings.

Inventory skips sensitive directory components, symlinks, binary files, large files, archives, dependency caches, build outputs, local databases, and raw logs. Use `inventory --explain-skips` to see bounded skip reasons.

## Repository Layout

- `SKILL.md`: runtime instructions for skill-compatible agents (Codex, Claude Code, and other Agent Skills readers).
- `agents/openai.yaml`: Codex-specific adapter metadata (display name and default prompt). Other platforms ignore this file; delete it if you do not use Codex.
- `scripts/agent_context.py`: the platform-neutral core CLI. Dependency-free, single file.
- `examples/sample-output/`: a committed example of what `scaffold` generates (see `examples/HOWTO.md` for how it is regenerated).
- `tests/`: unit tests plus golden files pinning generated output.
- `references/`: contracts and guides for maintaining and extending the skill.
- `reports/`: dated records of verified platform facts (installation paths, detection variables).

## Development

```bash
scripts/run_checks.sh
```

runs the same steps as CI: byte-compilation, the unit-test suite, and a sample-output round-trip (regenerate, check, idempotency, diff against `examples/sample-output/`).

Changes to generated output are tracked in [CHANGELOG.md](CHANGELOG.md).

## Documentation

- `references/context-file-contract.md`: generated file roles and update boundaries.
- `references/provider-profiles.md`: provider/model profile guidance.
- `references/inventory-heuristics.md`: safe inventory rules.
- `references/extension-guide.md`: product intent, extension rules, and how this skill itself is distributed.

Japanese versions are available as `README.ja.md` and `references/*.ja.md`. English documentation is authoritative; the Japanese companion files follow it in the same commit.

## License

MIT — see [LICENSE](LICENSE).
