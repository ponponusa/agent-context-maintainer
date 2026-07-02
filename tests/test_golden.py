"""Golden-file test pinning scaffold output byte-for-byte.

The files under tests/golden/ were captured by running
`scaffold <tmp>/golden-fixture --agent generic` on an empty fixture directory
named `golden-fixture` (the name is embedded in generated content). Regenerate
them the same way after any intentional template change.
"""

from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
sys.path.insert(0, str(ROOT / "scripts"))

import agent_context  # noqa: E402


REVIEWED_RE = re.compile(r'reviewed: "\d{4}-\d{2}-\d{2}"')


def normalize(text: str) -> str:
    return REVIEWED_RE.sub('reviewed: "<date>"', text)


def file_set(root: Path) -> set[str]:
    return {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()}


class GoldenTests(unittest.TestCase):
    def test_scaffold_generic_matches_golden(self) -> None:
        golden_files = file_set(GOLDEN_DIR)
        self.assertEqual(len(golden_files), 15)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "golden-fixture"
            root.mkdir()

            agent_context.scaffold(root, "generic")

            self.assertEqual(file_set(root), golden_files)
            for rel in sorted(golden_files):
                actual = (root / rel).read_text(encoding="utf-8")
                expected = (GOLDEN_DIR / rel).read_text(encoding="utf-8")
                self.assertEqual(normalize(actual), normalize(expected), rel)


if __name__ == "__main__":
    unittest.main()
