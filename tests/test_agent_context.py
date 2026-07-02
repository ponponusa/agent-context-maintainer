from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
