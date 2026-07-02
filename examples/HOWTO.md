# Regenerating examples/sample-output

`examples/sample-output/` is a committed example of what `scaffold` generates.
CI regenerates it from scratch and diffs the result against the committed tree,
so it must be refreshed whenever generated output changes intentionally.

Constraints that make the regeneration reproducible:

- The fixture directory **must be named `sample-output`** — the directory name
  is embedded in the generated `.agents/core.md` (`Root:` line).
- The fixture starts from exactly two files: `README.md` and `package.json`
  with the contents currently committed in `examples/sample-output/`.
- `scaffold` is run **twice**: the first run's generated files become part of
  the inventory (file count and detected docs in `.agents/core.md`), so output
  converges on the second run. The committed tree is that fixed point, and any
  further run reports `no changes`.
- `.agents/skills/` is created empty by `scaffold`; git cannot track empty
  directories, so a `.gitkeep` file is committed there **after** the scaffold
  runs (it would otherwise be counted by the inventory). Diff comparisons must
  exclude `.gitkeep`.

Steps (mirrored by `scripts/run_checks.sh`):

```bash
tmp="$(mktemp -d)"
mkdir "$tmp/sample-output"
cp examples/sample-output/README.md examples/sample-output/package.json "$tmp/sample-output/"
python3 scripts/agent_context.py scaffold "$tmp/sample-output" --agent generic
python3 scripts/agent_context.py scaffold "$tmp/sample-output" --agent generic
python3 scripts/agent_context.py check "$tmp/sample-output"
diff -r -x .gitkeep -x snapshots examples/sample-output "$tmp/sample-output"
```

To refresh the committed tree after an intentional template change:

```bash
rm -rf examples/sample-output/.agents examples/sample-output/.gemini examples/sample-output/.github \
  examples/sample-output/AGENTS.md examples/sample-output/CLAUDE.md examples/sample-output/GEMINI.md
python3 scripts/agent_context.py scaffold examples/sample-output --agent generic
python3 scripts/agent_context.py scaffold examples/sample-output --agent generic
rm -rf examples/sample-output/.agents/snapshots
touch examples/sample-output/.agents/skills/.gitkeep
```

The second scaffold run may write a pre-overwrite snapshot under
`.agents/snapshots/`; snapshots are runtime byproducts (with timestamped
names) and are not part of the committed example.

Record intentional output changes in `CHANGELOG.md` and regenerate
`tests/golden/` the same way (fixture name `golden-fixture`, empty fixture).
