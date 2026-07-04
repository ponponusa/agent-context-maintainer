from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Optional
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import agent_context  # noqa: E402


class AgentContextTests(unittest.TestCase):
    def test_marker_update_preserves_human_content_outside_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agents = root / "AGENTS.md"
            agents.write_text(
                "# Local Rules\n\n"
                "Human lead.\n\n"
                f"{agent_context.BEGIN}\nold generated\n{agent_context.END}\n\n"
                "Human tail.\n",
                encoding="utf-8",
            )

            changes = agent_context.scaffold(root, "codex")

            text = agents.read_text(encoding="utf-8")
            self.assertIn("Human lead.", text)
            self.assertIn("Human tail.", text)
            self.assertNotIn("old generated", text)
            self.assertTrue(any(action == "updated-generated-block" and path == agents for action, path in changes))

    def test_unmarked_human_file_refused_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "AGENTS.md").write_text("# Human Rules\n", encoding="utf-8")

            with self.assertRaisesRegex(agent_context.AgentContextError, "no generated block marker"):
                agent_context.scaffold(root, "codex")

    def test_clean_tracked_human_file_refused_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "AGENTS.md").write_text("# Human Rules\n", encoding="utf-8")
            subprocess.run(["git", "init"], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(["git", "add", "AGENTS.md"], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Agent Context Test",
                    "-c",
                    "user.email=agent-context-test@example.invalid",
                    "commit",
                    "-m",
                    "add human agents",
                ],
                cwd=root,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            with self.assertRaisesRegex(agent_context.AgentContextError, "no generated block marker"):
                agent_context.scaffold(root, "codex")

    def test_marker_inside_markdown_code_fence_is_not_treated_as_managed_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agents = root / "AGENTS.md"
            agents.write_text(
                "# Human Rules\n\n"
                "```md\n"
                f"{agent_context.BEGIN}\n"
                "example only\n"
                f"{agent_context.END}\n"
                "```\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(agent_context.AgentContextError, "no generated block marker"):
                agent_context.scaffold(root, "codex")
            self.assertIn("example only", agents.read_text(encoding="utf-8"))

    def test_append_generated_block_preserves_unmarked_human_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agents = root / "AGENTS.md"
            agents.write_text("# Human Rules\n\nKeep this.\n", encoding="utf-8")

            agent_context.scaffold(
                root,
                "codex",
                agent_context.ScaffoldOptions(append_generated_block=True),
            )

            text = agents.read_text(encoding="utf-8")
            self.assertIn("# Human Rules", text)
            self.assertIn("Keep this.", text)
            self.assertIn(agent_context.BEGIN, text)
            self.assertIn("Agent Context Entry", text)

    def test_append_generated_block_refuses_unmarked_yaml_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = root / ".agents" / "provider-registry.yaml"
            registry.parent.mkdir()
            registry.write_text("providers: {}\n", encoding="utf-8")

            with self.assertRaisesRegex(agent_context.AgentContextError, "cannot safely append"):
                agent_context.scaffold(
                    root,
                    "codex",
                    agent_context.ScaffoldOptions(append_generated_block=True),
                )

    def test_dry_run_does_not_write_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            changes = agent_context.scaffold(
                root,
                "codex",
                agent_context.ScaffoldOptions(dry_run=True),
            )

            self.assertTrue(changes)
            self.assertTrue(all(action.startswith("would-") for action, _ in changes))
            self.assertFalse((root / "AGENTS.md").exists())

    def test_inventory_explains_sensitive_binary_large_archive_and_symlink_skips(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
            (root / ".ssh").mkdir()
            (root / ".ssh" / "id_rsa").write_text("secret", encoding="utf-8")
            (root / "data.bin").write_bytes(b"a\0b")
            (root / "bundle.zip").write_text("archive", encoding="utf-8")
            (root / "big.txt").write_text("x" * (agent_context.MAX_INVENTORY_FILE_BYTES + 1), encoding="utf-8")
            try:
                (root / "link.py").symlink_to(root / "src" / "app.py")
            except OSError:
                pass

            inv = agent_context.inventory(root, explain_skips=True)

            self.assertEqual(inv["file_count"], 1)
            self.assertEqual(inv["languages"], ["Python"])
            skipped = {item["path"]: item["reason"] for item in inv["skipped"]}
            self.assertEqual(skipped[".ssh/"], "sensitive-directory")
            self.assertEqual(skipped["data.bin"], "binary-file")
            self.assertEqual(skipped["bundle.zip"], "archive-file")
            self.assertEqual(skipped["big.txt"], "large-file")
            if "link.py" in skipped:
                self.assertEqual(skipped["link.py"], "symlink-file")

    def test_inventory_respects_gitignore_without_dropping_tracked_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
            (root / "kept.py").write_text("print('ok')\n", encoding="utf-8")
            (root / "ignored.txt").write_text("ignore me\n", encoding="utf-8")
            subprocess.run(["git", "init"], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            inv = agent_context.inventory(root, explain_skips=True)

            self.assertEqual(inv["languages"], ["Python"])
            skipped = {item["path"]: item["reason"] for item in inv["skipped"]}
            self.assertEqual(skipped["ignored.txt"], "ignored-file")

    def test_scaffold_creates_provider_bridges_and_check_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            agent_context.scaffold(root, "copilot")

            self.assertEqual(agent_context.check(root), [])
            self.assertTrue((root / ".agents" / "profiles" / "copilot.md").exists())
            self.assertTrue((root / ".agents" / "profiles" / "antigravity.md").exists())
            self.assertTrue((root / "GEMINI.md").exists())
            self.assertTrue((root / ".github" / "copilot-instructions.md").exists())
            self.assertTrue((root / ".agents" / "provider-registry.yaml").exists())
            settings = json.loads((root / ".gemini" / "settings.json").read_text(encoding="utf-8"))
            self.assertEqual(settings["contextFileName"], ["GEMINI.md", "AGENTS.md"])

    def test_existing_gemini_settings_are_merged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings_path = root / ".gemini" / "settings.json"
            settings_path.parent.mkdir()
            settings_path.write_text(
                json.dumps(
                    {
                        "theme": "dark",
                        "contextFileName": "LOCAL.md",
                        "fileFiltering": {"respectGitIgnore": False},
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            changes = agent_context.scaffold(root, "gemini")

            self.assertTrue(any(action == "updated-json-settings" for action, _ in changes))
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            self.assertEqual(settings["theme"], "dark")
            self.assertEqual(settings["contextFileName"], ["LOCAL.md", "GEMINI.md", "AGENTS.md"])
            self.assertEqual(settings["fileFiltering"]["respectGitIgnore"], False)

    def test_untracked_generated_block_update_is_snapshotted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agents = root / "AGENTS.md"
            agents.write_text(
                "# Agent Instructions\n\n"
                f"{agent_context.BEGIN}\n"
                "old generated\n"
                f"{agent_context.END}\n",
                encoding="utf-8",
            )

            agent_context.scaffold(root, "codex")

            snapshots = list((root / ".agents" / "snapshots" / "agent-context-maintainer").glob("*"))
            self.assertEqual(len(snapshots), 1)
            before_files = list(snapshots[0].glob("AGENTS.md.before"))
            self.assertEqual(len(before_files), 1)
            self.assertIn("old generated", before_files[0].read_text(encoding="utf-8"))

    def _git(self, root: Path, *args: str) -> None:
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Agent Context Test",
                "-c",
                "user.email=agent-context-test@example.invalid",
                *args,
            ],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def test_mismatched_marker_refuses_without_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agents = root / "AGENTS.md"
            original = (
                "# Human Rules\n\n"
                f"{agent_context.BEGIN}\n"
                "generated without end marker\n"
            )
            agents.write_text(original, encoding="utf-8")

            with self.assertRaisesRegex(agent_context.AgentContextError, "mismatched"):
                agent_context.scaffold(root, "codex")

            self.assertEqual(agents.read_text(encoding="utf-8"), original)
            self.assertEqual(sorted(p.name for p in root.iterdir()), ["AGENTS.md"])

    def test_tracked_dirty_generated_block_update_snapshots_diff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agents = root / "AGENTS.md"
            agents.write_text(
                "# Agent Instructions\n\n"
                f"{agent_context.BEGIN}\n"
                "committed generated\n"
                f"{agent_context.END}\n",
                encoding="utf-8",
            )
            self._git(root, "init")
            self._git(root, "add", "AGENTS.md")
            self._git(root, "commit", "-m", "add generated agents")
            agents.write_text(
                "# Agent Instructions\n\n"
                f"{agent_context.BEGIN}\n"
                "uncommitted local edit\n"
                f"{agent_context.END}\n",
                encoding="utf-8",
            )

            agent_context.scaffold(root, "codex")

            snapshots = list((root / ".agents" / "snapshots" / "agent-context-maintainer").glob("*"))
            self.assertEqual(len(snapshots), 1)
            diff_files = list(snapshots[0].glob("AGENTS.md.diff"))
            self.assertEqual(len(diff_files), 1)
            self.assertIn("uncommitted local edit", diff_files[0].read_text(encoding="utf-8"))

    def test_tracked_clean_generated_block_update_is_not_snapshotted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agents = root / "AGENTS.md"
            agents.write_text(
                "# Agent Instructions\n\n"
                f"{agent_context.BEGIN}\n"
                "committed generated\n"
                f"{agent_context.END}\n",
                encoding="utf-8",
            )
            self._git(root, "init")
            self._git(root, "add", "AGENTS.md")
            self._git(root, "commit", "-m", "add generated agents")

            changes = agent_context.scaffold(root, "codex")

            self.assertTrue(
                any(action == "updated-generated-block" and path == agents for action, path in changes)
            )
            self.assertFalse((root / ".agents" / "snapshots").exists())

    def test_fake_import_in_html_comment_fails_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "CLAUDE.md").write_text(
                "# Claude Code Instructions\n\n<!-- @AGENTS.md -->\n",
                encoding="utf-8",
            )

            errors = agent_context.check(root)

            self.assertIn("CLAUDE.md does not import @AGENTS.md", errors)

    def test_inventory_excludes_tool_snapshot_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")
            snapshot_dir = root / ".agents" / "snapshots" / "agent-context-maintainer" / "20260101T000000Z"
            snapshot_dir.mkdir(parents=True)
            (snapshot_dir / "AGENTS.md.before").write_text("old\n", encoding="utf-8")

            inv = agent_context.inventory(root, explain_skips=True)

            self.assertEqual(inv["file_count"], 1)
            self.assertIn(
                {"path": ".agents/snapshots/", "reason": "tool-snapshot-directory"},
                inv["skipped"],
            )

    def test_detect_agent_matches_confirmed_variables_exactly(self) -> None:
        for var, expected in (
            ("CLAUDECODE", "claude"),
            ("CLAUDE_CODE_ENTRYPOINT", "claude"),
            ("CODEX_SANDBOX", "codex"),
            ("CODEX_SANDBOX_NETWORK_DISABLED", "codex"),
            ("GEMINI_CLI", "gemini"),
        ):
            with mock.patch.dict(os.environ, {var: "1"}, clear=True):
                self.assertEqual(agent_context.detect_agent(), (expected, var))

    def test_detect_agent_ignores_unrelated_variables(self) -> None:
        env = {
            "COPILOT_OTEL_FILE_EXPORTER_PATH": "/tmp/otel",
            "CURSOR_TRACE_ID": "abc",
            "MY_CLAUDE_HELPER": "1",
            "CODEXIFY": "1",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(agent_context.detect_agent(), ("generic", None))

    def test_detect_agent_uses_detect_priority_on_multiple_hits(self) -> None:
        env = {"CODEX_SANDBOX": "seatbelt", "CLAUDECODE": "1", "GEMINI_CLI": "1"}
        with mock.patch.dict(os.environ, env, clear=True):
            agent, source = agent_context.detect_agent()
        self.assertEqual(agent, "claude")
        self.assertEqual(source, "CLAUDECODE")

    def test_providers_registry_is_consistent(self) -> None:
        self.assertEqual(agent_context.PROFILES, tuple(agent_context.PROVIDERS))
        self.assertEqual(
            set(agent_context.DETECT_PRIORITY),
            set(agent_context.PROFILES) - {"generic"},
        )
        for key, spec in agent_context.PROVIDERS.items():
            self.assertIn("AGENTS.md", spec["bridge_files"], key)
            self.assertTrue(spec["profile_bullets"], key)
            self.assertTrue(spec["source_urls"], key)

    def test_providers_cli_output_matches_registry(self) -> None:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "agent_context.py"), "providers", "--json"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(list(payload), list(agent_context.PROVIDERS))
        for key, spec in agent_context.PROVIDERS.items():
            self.assertEqual(payload[key]["bridge_files"], spec["bridge_files"])
            self.assertEqual(payload[key]["detect_env"], spec["detect_env"])
            self.assertEqual(payload[key]["profile"], f".agents/profiles/{key}.md")

    def test_inventory_json_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# Demo\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "agent_context.py"),
                    "inventory",
                    str(root),
                    "--json",
                    "--explain-skips",
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

            payload = json.loads(result.stdout)
            self.assertEqual(payload["root_name"], root.name)
            self.assertIn("README.md", payload["docs"])

    def _write_skill(
        self,
        root: Path,
        name: str = "code-review",
        frontmatter: Optional[str] = None,
        body: str = "# Code Review\n\nRead `references/guide.md`.\n",
        evals: Optional[dict[str, object]] = None,
    ) -> Path:
        skill = root / ".agents" / "skills" / name
        (skill / "references").mkdir(parents=True)
        (skill / "references" / "guide.md").write_text("# Guide\n", encoding="utf-8")
        if frontmatter is None:
            frontmatter = (
                "---\n"
                f"name: {name}\n"
                "description: Review code changes for correctness and regression risk. Use when asked to review diffs or PRs.\n"
                "compatibility: Python 3.9+\n"
                "metadata:\n"
                "  agent-context-maintainer.status: active\n"
                "---\n"
            )
        (skill / "SKILL.md").write_text(frontmatter + body, encoding="utf-8")
        if evals is not None:
            (skill / "evals").mkdir()
            (skill / "evals" / "evals.json").write_text(json.dumps(evals), encoding="utf-8")
        return skill

    def test_skills_inventory_json_empty_when_no_skills(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = agent_context.skill_inventory_json(agent_context.skill_inventory(Path(tmp)))
            self.assertEqual(payload["skill_count"], 0)
            self.assertEqual(payload["skills"], [])

    def test_skills_inventory_reads_valid_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_skill(
                root,
                evals={
                    "schema_version": 1,
                    "skill_name": "code-review",
                    "evals": [
                        {"id": "trigger", "kind": "trigger", "prompt": "Review this diff", "should_trigger": True, "assertions": ["triggers"]},
                        {"id": "negative", "kind": "trigger", "prompt": "Write a poem", "should_trigger": False},
                        {"id": "outcome", "kind": "outcome", "prompt": "Review this diff", "expected_output": "Finds risks", "assertions": ["risk"]},
                    ],
                },
            )

            inv = agent_context.skill_inventory(root)

            self.assertEqual(len(inv.skills), 1)
            skill = inv.skills[0]
            self.assertEqual(skill.validity, "valid")
            self.assertEqual(skill.lifecycle, "active")
            self.assertEqual(skill.quality.eval_coverage, "present")
            self.assertTrue(skill.quality.has_trigger_evals)
            self.assertTrue(skill.quality.has_negative_trigger_evals)
            self.assertTrue(skill.quality.has_assertions)

    def test_skills_check_rejects_missing_skill_md(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".agents" / "skills" / "empty-skill").mkdir(parents=True)

            _warnings, errors = agent_context.skill_inventory_diagnostics(agent_context.skill_inventory(root))

            self.assertIn("missing-skill-md", {item.code for item in errors})

    def test_skills_check_rejects_empty_skill_md(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / ".agents" / "skills" / "empty"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("", encoding="utf-8")

            _warnings, errors = agent_context.skill_inventory_diagnostics(agent_context.skill_inventory(root))

            codes = {item.code for item in errors}
            self.assertIn("invalid-frontmatter", codes)
            self.assertIn("missing-name", codes)
            self.assertIn("missing-description", codes)

    def test_skills_check_rejects_missing_description_and_name_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_skill(root, name="code-review", frontmatter="---\nname: other-skill\n---\n")

            _warnings, errors = agent_context.skill_inventory_diagnostics(agent_context.skill_inventory(root))
            codes = {item.code for item in errors}

            self.assertIn("missing-description", codes)
            self.assertIn("name-directory-mismatch", codes)

    def test_skills_check_rejects_consecutive_hyphen_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_skill(root, name="bad--skill")

            _warnings, errors = agent_context.skill_inventory_diagnostics(agent_context.skill_inventory(root))

            self.assertIn("invalid-directory-name", {item.code for item in errors})
            self.assertIn("invalid-name", {item.code for item in errors})

    def test_skills_check_rejects_long_compatibility(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_skill(
                root,
                frontmatter=(
                    "---\n"
                    "name: code-review\n"
                    "description: Review code changes for correctness. Use when asked to review diffs.\n"
                    f"compatibility: {'x' * 501}\n"
                    "---\n"
                ),
            )

            _warnings, errors = agent_context.skill_inventory_diagnostics(agent_context.skill_inventory(root))

            self.assertIn("long-compatibility", {item.code for item in errors})

    def test_missing_evals_warns_without_draft_or_top_level_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_skill(root)

            inv = agent_context.skill_inventory(root)
            warnings, errors = agent_context.skill_inventory_diagnostics(inv)

            self.assertEqual(inv.skills[0].lifecycle, "active")
            self.assertIn("missing-evals", {item.code for item in warnings})
            self.assertEqual(errors, [])
            self.assertEqual(agent_context.check_skill_errors_only(root), [])

    def test_top_level_check_does_not_require_agents_skills_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agent_context.scaffold(root, "generic")
            (root / ".agents" / "skills").rmdir()

            self.assertEqual(agent_context.check(root), [])

    def test_skill_frontmatter_supports_block_description(self) -> None:
        text = "---\nname: docs-helper\ndescription: |\n  Review documentation changes.\n  Use when docs are updated.\n---\n# Body\n"

        frontmatter, _body, errors, _warnings = agent_context.parse_skill_frontmatter(text)

        self.assertEqual(errors, [])
        self.assertIsNotNone(frontmatter)
        self.assertIn("Use when", frontmatter.description)

    def test_skill_frontmatter_unsupported_yaml_fails_required_fields(self) -> None:
        text = "---\nname:\n  nested: nope\ndescription: [bad]\n---\n# Body\n"

        frontmatter, _body, _errors, _warnings = agent_context.parse_skill_frontmatter(text)

        self.assertIsNotNone(frontmatter)
        self.assertIsNone(frontmatter.name)
        self.assertIsNone(frontmatter.description)

    def test_skill_frontmatter_malformed_quote_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_skill(
                root,
                name="bad",
                frontmatter=(
                    "---\n"
                    "name: bad\n"
                    "description: \"Review code changes carefully. Use when asked to review diffs.\n"
                    "---\n"
                ),
            )

            _warnings, errors = agent_context.skill_inventory_diagnostics(agent_context.skill_inventory(root))

            self.assertIn("invalid-frontmatter", {item.code for item in errors})
            self.assertIn("missing-description", {item.code for item in errors})

    def test_eval_manifest_rejects_unsafe_input_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_skill(
                root,
                evals={
                    "schema_version": 1,
                    "skill_name": "code-review",
                    "evals": [
                        {"id": "abs", "kind": "outcome", "prompt": "x", "expected_output": "x", "input_files": ["/tmp/x"]},
                        {"id": "parent", "kind": "outcome", "prompt": "x", "expected_output": "x", "input_files": ["../x"]},
                        {"id": "secret", "kind": "outcome", "prompt": "x", "expected_output": "x", "input_files": ["evals/.env"]},
                    ],
                },
            )
            env_path = root / ".agents" / "skills" / "code-review" / "evals" / ".env"
            env_path.write_text("TOKEN=x\n", encoding="utf-8")

            _warnings, errors = agent_context.skill_inventory_diagnostics(agent_context.skill_inventory(root))

            self.assertIn("unsafe-eval-input-file", {item.code for item in errors})

    def test_eval_manifest_file_symlink_is_not_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = self._write_skill(root)
            external = root / "external-evals.json"
            external.write_text(json.dumps({"schema_version": 1, "skill_name": "code-review", "evals": []}), encoding="utf-8")
            (skill / "evals").mkdir()
            try:
                (skill / "evals" / "evals.json").symlink_to(external)
            except OSError:
                self.skipTest("symlinks unavailable")

            _warnings, errors = agent_context.skill_inventory_diagnostics(agent_context.skill_inventory(root))

            self.assertIn("invalid-evals-json", {item.code for item in errors})

    def test_eval_manifest_requires_skill_name_and_list_assertions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_skill(
                root,
                evals={
                    "schema_version": 1,
                    "evals": [
                        {"id": "case", "kind": "outcome", "prompt": "x", "assertions": "not-a-list"},
                    ],
                },
            )

            _warnings, errors = agent_context.skill_inventory_diagnostics(agent_context.skill_inventory(root))
            messages = "\n".join(item.message for item in errors)

            self.assertIn("skill_name must match", messages)
            self.assertIn("assertions must be a list", messages)

    def test_eval_manifest_rejects_bool_schema_and_non_string_expected_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_skill(
                root,
                evals={
                    "schema_version": True,
                    "skill_name": "code-review",
                    "evals": [
                        {"id": "case", "kind": "outcome", "prompt": "x", "expected_output": 123},
                    ],
                },
            )

            _warnings, errors = agent_context.skill_inventory_diagnostics(agent_context.skill_inventory(root))
            messages = "\n".join(item.message for item in errors)

            self.assertIn("schema_version must be 1", messages)
            self.assertIn("expected_output must be a string", messages)

    def test_eval_manifest_rejects_non_string_kind_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_skill(
                root,
                evals={
                    "schema_version": 1,
                    "skill_name": "code-review",
                    "evals": [
                        {"id": "case", "kind": ["trigger"], "prompt": "x", "expected_output": "x"},
                    ],
                },
            )

            _warnings, errors = agent_context.skill_inventory_diagnostics(agent_context.skill_inventory(root))

            self.assertIn("invalid kind", "\n".join(item.message for item in errors))

    def test_symlink_skill_directory_is_warning_not_followed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skills = root / ".agents" / "skills"
            target = root / "outside-skill"
            target.mkdir()
            skills.mkdir(parents=True)
            try:
                (skills / "linked-skill").symlink_to(target)
            except OSError:
                self.skipTest("symlinks unavailable")

            inv = agent_context.skill_inventory(root)
            warnings, errors = agent_context.skill_inventory_diagnostics(inv)

            self.assertEqual(inv.skills, [])
            self.assertEqual(errors, [])
            self.assertIn("unmanaged-symlink-skill", {item.code for item in warnings})

    def test_symlink_skills_root_is_warning_not_followed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / "outside-skills"
            outside.mkdir()
            agents = root / ".agents"
            agents.mkdir()
            try:
                (agents / "skills").symlink_to(outside)
            except OSError:
                self.skipTest("symlinks unavailable")

            inv = agent_context.skill_inventory(root)
            warnings, errors = agent_context.skill_inventory_diagnostics(inv)

            self.assertEqual(inv.skills, [])
            self.assertEqual(errors, [])
            self.assertIn("unmanaged-symlink-skill", {item.code for item in warnings})

    def test_symlink_agents_parent_is_warning_not_followed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / "outside-agents"
            (outside / "skills").mkdir(parents=True)
            try:
                (root / ".agents").symlink_to(outside)
            except OSError:
                self.skipTest("symlinks unavailable")

            inv = agent_context.skill_inventory(root)
            warnings, errors = agent_context.skill_inventory_diagnostics(inv)

            self.assertEqual(inv.skills, [])
            self.assertEqual(errors, [])
            self.assertIn("unmanaged-symlink-skill", {item.code for item in warnings})

    def test_symlink_skill_md_is_not_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            external = root / "external.md"
            external.write_text(
                "---\nname: link-skill\ndescription: Review code. Use when asked to review diffs.\n---\n# Link\n",
                encoding="utf-8",
            )
            skill = root / ".agents" / "skills" / "link-skill"
            skill.mkdir(parents=True)
            try:
                (skill / "SKILL.md").symlink_to(external)
            except OSError:
                self.skipTest("symlinks unavailable")

            _warnings, errors = agent_context.skill_inventory_diagnostics(agent_context.skill_inventory(root))

            self.assertIn("unsafe-local-reference", {item.code for item in errors})

    def test_symlink_components_in_references_and_eval_inputs_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = self._write_skill(
                root,
                body="# Skill\n\nRead [guide](references/linkdir/guide.md).\n",
                evals={
                    "schema_version": 1,
                    "skill_name": "code-review",
                    "evals": [
                        {
                            "id": "case",
                            "kind": "outcome",
                            "prompt": "x",
                            "expected_output": "x",
                            "input_files": ["evals/linkdir/input.md"],
                        }
                    ],
                },
            )
            (skill / "references" / "real").mkdir()
            (skill / "references" / "real" / "guide.md").write_text("# Real\n", encoding="utf-8")
            (skill / "evals" / "real").mkdir()
            (skill / "evals" / "real" / "input.md").write_text("input\n", encoding="utf-8")
            try:
                (skill / "references" / "linkdir").symlink_to(skill / "references" / "real")
                (skill / "evals" / "linkdir").symlink_to(skill / "evals" / "real")
            except OSError:
                self.skipTest("symlinks unavailable")

            _warnings, errors = agent_context.skill_inventory_diagnostics(agent_context.skill_inventory(root))

            codes = {item.code for item in errors}
            self.assertIn("unsafe-local-reference", codes)
            self.assertIn("unsafe-eval-input-file", codes)

    def test_file_uri_reference_is_unsafe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_skill(root, body="# Skill\n\nRead [secret](file:///etc/passwd).\n")

            _warnings, errors = agent_context.skill_inventory_diagnostics(agent_context.skill_inventory(root))

            self.assertIn("unsafe-local-reference", {item.code for item in errors})

    def test_unsafe_reference_diagnostic_path_is_repo_relative(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_skill(root, body="# Skill\n\nRead [secret](/etc/passwd) and [parent](../secret.md).\n")

            _warnings, errors = agent_context.skill_inventory_diagnostics(agent_context.skill_inventory(root))
            unsafe_paths = [item.path for item in errors if item.code == "unsafe-local-reference"]

            self.assertEqual(unsafe_paths, [".agents/skills/code-review/SKILL.md", ".agents/skills/code-review/SKILL.md"])
            self.assertTrue(all(not path.startswith("/") for path in unsafe_paths))

    def test_unsafe_eval_input_diagnostic_path_is_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_skill(
                root,
                evals={
                    "schema_version": 1,
                    "skill_name": "code-review",
                    "evals": [
                        {"id": "case", "kind": "outcome", "prompt": "x", "expected_output": "x", "input_files": ["/etc/passwd", "../secret.md"]},
                    ],
                },
            )

            _warnings, errors = agent_context.skill_inventory_diagnostics(agent_context.skill_inventory(root))
            unsafe_paths = [item.path for item in errors if item.code == "unsafe-eval-input-file"]

            self.assertEqual(unsafe_paths, [".agents/skills/code-review/evals/evals.json", ".agents/skills/code-review/evals/evals.json"])

    def test_skills_inventory_json_cli_and_check_exit_one(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_skill(root, frontmatter="---\nname: code-review\n---\n")

            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "agent_context.py"), "skills", "inventory", str(root), "--json"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(payload["skill_count"], 1)

            check_result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "agent_context.py"), "skills", "check", str(root)],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            self.assertEqual(check_result.returncode, 1)
            self.assertIn("missing-description", check_result.stdout)

    def test_skills_sync_writes_registry_and_report_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_skill(root)

            agent_context.skills_sync(root, agent_context.ScaffoldOptions())
            first_registry = (root / ".agents" / "skill-registry.yaml").read_text(encoding="utf-8")
            first_report = (root / ".agents" / "skill-reports" / "skill-health.md").read_text(encoding="utf-8")
            changes = agent_context.skills_sync(root, agent_context.ScaffoldOptions())

            self.assertEqual(changes, [])
            self.assertEqual(first_registry, (root / ".agents" / "skill-registry.yaml").read_text(encoding="utf-8"))
            self.assertEqual(first_report, (root / ".agents" / "skill-reports" / "skill-health.md").read_text(encoding="utf-8"))
            self.assertIn('source_reviewed: "2026-07-04"', first_registry)

    def test_skills_sync_preserves_human_content_and_refuses_unmarked_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_skill(root)
            report = root / ".agents" / "skill-reports" / "skill-health.md"
            report.parent.mkdir(parents=True)
            report.write_text("# Human Report\n\nKeep me.\n", encoding="utf-8")

            with self.assertRaisesRegex(agent_context.AgentContextError, "no generated block marker"):
                agent_context.skills_sync(root, agent_context.ScaffoldOptions())

            agent_context.skills_sync(root, agent_context.ScaffoldOptions(append_generated_block=True))
            self.assertIn("Keep me.", report.read_text(encoding="utf-8"))

    def test_skills_eval_plan_and_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_skill(
                root,
                evals={"schema_version": 1, "skill_name": "code-review", "evals": [{"id": "case-one", "kind": "trigger", "prompt": "Review", "should_trigger": False}]},
            )

            plan = agent_context.skills_eval_plan(root, "code-review")
            changes = agent_context.init_skill_workspace(root, "code-review")
            inv = agent_context.inventory(root, explain_skips=True)

            self.assertEqual(plan["skills"][0]["eval_ids"], ["case-one"])
            self.assertTrue(any(str(path).endswith("prompt.md") for _action, path in changes))
            self.assertIn({"path": ".agents/skill-workspaces/", "reason": "tool-workspace-directory"}, inv["skipped"])

    def test_skills_eval_workspace_skips_secret_like_references(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = self._write_skill(root)
            (skill / "references" / ".env").write_text("TOKEN=secret\n", encoding="utf-8")

            agent_context.init_skill_workspace(root, "code-review")

            copied = list((root / ".agents" / "skill-workspaces").rglob(".env"))
            self.assertEqual(copied, [])

    def test_skill_overrides_and_routing_sync(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_skill(root)
            (root / ".agents").mkdir(exist_ok=True)
            (root / ".agents" / "routing.md").write_text("# Agent Routing\n", encoding="utf-8")
            (root / ".agents" / "skill-overrides.json").write_text(
                json.dumps({"code-review": {"lifecycle": "deprecated", "route_label": "Code review"}}),
                encoding="utf-8",
            )

            agent_context.sync_skill_routes(root, agent_context.ScaffoldOptions())
            text = (root / ".agents" / "routing.md").read_text(encoding="utf-8")

            self.assertNotIn(".agents/skills/code-review/SKILL.md", text)
            self.assertEqual(agent_context.check_skill_routes(root), [])

    def test_experimental_route_without_label_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_skill(root)
            routing = root / ".agents" / "routing.md"
            routing.parent.mkdir(parents=True, exist_ok=True)
            routing.write_text(
                "# Agent Routing\n\n"
                "## Skill Routes\n\n"
                "<!-- agent-context-maintainer:skills-begin -->\n"
                "- Code review: read `.agents/skills/code-review/SKILL.md`.\n"
                "<!-- agent-context-maintainer:skills-end -->\n",
                encoding="utf-8",
            )
            (root / ".agents" / "skill-overrides.json").write_text(
                json.dumps({"code-review": {"lifecycle": "experimental"}}),
                encoding="utf-8",
            )

            self.assertTrue(agent_context.check_skill_routes(root))

    def test_invalid_skill_overrides_block_route_sync(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_skill(root)
            (root / ".agents" / "skill-overrides.json").write_text("{bad json", encoding="utf-8")

            with self.assertRaisesRegex(agent_context.AgentContextError, "inventory errors"):
                agent_context.skill_routes_body(root)

    def test_invalid_lifecycle_override_values_are_errors(self) -> None:
        for lifecycle in (None, []):
            with self.subTest(lifecycle=lifecycle):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    self._write_skill(root)
                    (root / ".agents" / "skill-overrides.json").write_text(
                        json.dumps({"code-review": {"lifecycle": lifecycle}}),
                        encoding="utf-8",
                    )

                    _warnings, errors = agent_context.skill_inventory_diagnostics(agent_context.skill_inventory(root))

                    self.assertIn("invalid-skill-overrides", {item.code for item in errors})

    def test_codex_runner_command_and_danger_flag(self) -> None:
        self.assertEqual(
            agent_context.codex_eval_command("hello", "workspace-write"),
            ["codex", "exec", "--json", "--sandbox", "workspace-write", "hello"],
        )
        self.assertEqual(
            agent_context.codex_eval_command("hello", "workspace-write", full_auto=True),
            ["codex", "exec", "--json", "--full-auto", "hello"],
        )

    def test_codex_runner_constrains_trace_output_to_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prompt = root / ".agents" / "skill-workspaces" / "code-review" / "iteration-1" / "eval-case" / "with_skill" / "prompt.md"
            prompt.parent.mkdir(parents=True)
            prompt.write_text("hello", encoding="utf-8")
            outside = root / "trace.jsonl"

            with self.assertRaisesRegex(agent_context.AgentContextError, "trace output"):
                agent_context.run_codex_eval(prompt, outside, "workspace-write", False)

    def test_codex_runner_constrains_paths_to_requested_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            other = Path(tmp) / "other"
            prompt = other / ".agents" / "skill-workspaces" / "code-review" / "iteration-1" / "eval-case" / "with_skill" / "prompt.md"
            output = other / ".agents" / "skill-workspaces" / "code-review" / "iteration-1" / "eval-case" / "with_skill" / "outputs" / "trace.jsonl"
            prompt.parent.mkdir(parents=True)
            root.mkdir()
            prompt.write_text("hello", encoding="utf-8")

            with self.assertRaisesRegex(agent_context.AgentContextError, "trace output"):
                agent_context.run_codex_eval(prompt, output, "workspace-write", False, root=root)

    def test_codex_runner_warns_for_danger_full_access(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prompt = root / ".agents" / "skill-workspaces" / "code-review" / "iteration-1" / "eval-case" / "with_skill" / "prompt.md"
            output = prompt.parent / "outputs" / "trace.jsonl"
            prompt.parent.mkdir(parents=True)
            prompt.write_text("hello", encoding="utf-8")
            completed = subprocess.CompletedProcess(["codex"], 0, stdout="{}\n", stderr="")

            with mock.patch("agent_context.subprocess.run", return_value=completed), mock.patch("builtins.print") as printed:
                agent_context.run_codex_eval(prompt, output, "danger-full-access", True, root=root)

            self.assertTrue(any("danger-full-access" in str(call) for call in printed.call_args_list))


if __name__ == "__main__":
    unittest.main()
