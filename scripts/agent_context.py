#!/usr/bin/env python3
"""Scaffold and validate repository-local AI agent context files."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from textwrap import dedent


BEGIN = "<!-- agent-context-maintainer:begin -->"
END = "<!-- agent-context-maintainer:end -->"

# Single source of truth for provider knowledge: profile wording, bridge files,
# registry sources, and runtime-detection environment variables. Key order is
# fixed (it defines PROFILES). Only variables confirmed in
# reports/provider-review-*.md may be listed in detect_env.
PROVIDERS: dict[str, dict[str, object]] = {
    "codex": {
        "title": "Codex",
        "profile_bullets": [
            "Read the repository before editing.",
            "Use scoped patches and preserve unrelated user changes.",
            "Run focused validation and report exact commands.",
            "Create durable repo-local artifacts for long-running work.",
        ],
        "bridge_files": ["AGENTS.md"],
        "source_urls": ["https://agents.md/"],
        # Only set while Codex sandboxing is active; unsandboxed Codex
        # sessions fall back to generic and should pass --agent codex.
        "detect_env": ["CODEX_SANDBOX", "CODEX_SANDBOX_NETWORK_DISABLED"],
    },
    "claude": {
        "title": "Claude",
        "profile_bullets": [
            "Use strengths in long-form design review and cross-document reconciliation.",
            "State assumptions and open questions explicitly.",
            "Convert analysis into concrete edits when implementation is requested.",
        ],
        "bridge_files": ["CLAUDE.md", "AGENTS.md"],
        "source_urls": ["https://code.claude.com/docs/en/memory"],
        "detect_env": ["CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"],
    },
    "gemini": {
        "title": "Gemini",
        "profile_bullets": [
            "Use broad-context synthesis across docs and manifests.",
            "Attribute repository facts to checked local files.",
            "Verify current local state before treating recalled context as fact.",
        ],
        "bridge_files": ["GEMINI.md", ".gemini/settings.json", "AGENTS.md"],
        "source_urls": [
            "https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/configuration.md"
        ],
        "detect_env": ["GEMINI_CLI"],
    },
    "cursor": {
        "title": "Cursor",
        "profile_bullets": [
            "Prefer local symbol-aware edits and small reviewable diffs.",
            "Avoid unrelated formatting churn.",
            "Keep instructions practical for IDE-driven iteration.",
        ],
        "bridge_files": ["AGENTS.md"],
        "source_urls": ["https://docs.cursor.com/context/rules"],
        "detect_env": [],
    },
    "copilot": {
        "title": "Copilot",
        "profile_bullets": [
            "Prefer concise repository-wide guidance that reduces cloud-agent exploration.",
            "Keep task-specific instructions out of `.github/copilot-instructions.md`.",
            "Use `AGENTS.md` and the nearest applicable routed skill for deeper workflow details.",
        ],
        "bridge_files": [".github/copilot-instructions.md", "AGENTS.md"],
        "source_urls": [
            "https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/add-custom-instructions/add-repository-instructions"
        ],
        "detect_env": [],
    },
    "antigravity": {
        "title": "Antigravity",
        "profile_bullets": [
            "Prefer verifiable artifacts: plans, command results, screenshots, or review notes when useful.",
            "Be explicit about autonomous steps before broad edits or risky commands.",
            "Use shared `AGENTS.md` policy plus Gemini-compatible bridge files when available.",
        ],
        "bridge_files": ["AGENTS.md", "GEMINI.md"],
        "source_urls": ["https://antigravity.google/"],
        "detect_env": [],
    },
    "generic": {
        "title": "Generic",
        "profile_bullets": [
            "Follow `.agents/core.md` and `.agents/routing.md`.",
            "Identify available tools before choosing a workflow.",
            "Ask only when a missing decision would create meaningful risk.",
        ],
        "bridge_files": ["AGENTS.md"],
        "source_urls": ["https://agents.md/"],
        "detect_env": [],
    },
}
PROFILES = tuple(PROVIDERS)

# Detection precedence when multiple providers' variables are present. This is
# independent of the PROVIDERS key order and preserves the historical
# multi-hit behavior of detect_agent().
DETECT_PRIORITY = ("claude", "gemini", "cursor", "copilot", "antigravity", "codex")
EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".venv",
    "venv",
    "vendor",
    "dist",
    "build",
    "target",
    ".next",
    ".cache",
    "DerivedData",
}
SENSITIVE_DIR_COMPONENTS = {
    ".aws",
    ".azure",
    ".docker",
    ".gnupg",
    ".kube",
    ".ssh",
    ".terraform",
    "credentials",
    "secrets",
}
SECRET_NAMES = {
    ".env",
    ".envrc",
    ".env.local",
    ".env.production",
    ".npmrc",
    ".pypirc",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
}
EXCLUDED_SUFFIXES = {
    ".bak",
    ".cer",
    ".crt",
    ".db",
    ".der",
    ".key",
    ".log",
    ".p12",
    ".pem",
    ".pfx",
    ".sqlite",
    ".sqlite3",
}
ARCHIVE_SUFFIXES = {
    ".7z",
    ".bz2",
    ".dmg",
    ".gz",
    ".ipa",
    ".jar",
    ".rar",
    ".tar",
    ".tgz",
    ".war",
    ".xz",
    ".zip",
}
BINARY_SUFFIXES = {
    ".a",
    ".bin",
    ".class",
    ".dll",
    ".dylib",
    ".exe",
    ".gif",
    ".heic",
    ".ico",
    ".jpeg",
    ".jpg",
    ".lockb",
    ".o",
    ".pdf",
    ".png",
    ".pyc",
    ".so",
    ".webp",
}
MAX_INVENTORY_FILE_BYTES = 1_000_000
MAX_REPORTED_SKIPS = 200
MANIFESTS = {
    "package.json": "Node/JavaScript",
    "Cargo.toml": "Rust",
    "pyproject.toml": "Python",
    "requirements.txt": "Python",
    "go.mod": "Go",
    "pom.xml": "Java/Maven",
    "build.gradle": "Java/Gradle",
    "Package.swift": "Swift",
    "Gemfile": "Ruby",
}
LANG_EXTS = {
    ".ts": "TypeScript",
    ".tsx": "TypeScript React",
    ".js": "JavaScript",
    ".jsx": "JavaScript React",
    ".py": "Python",
    ".rs": "Rust",
    ".go": "Go",
    ".swift": "Swift",
    ".kt": "Kotlin",
    ".java": "Java",
    ".rb": "Ruby",
    ".md": "Markdown",
}
AGENTS_REF_RE = re.compile(r"`(\.agents/[^`\s)]+)`")
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
PROVIDER_REGISTRY_REVIEWED = "2026-07-02"  # update together with reports/provider-review-*.md


class AgentContextError(RuntimeError):
    """Raised when updating would be ambiguous or unsafe."""


@dataclass(frozen=True)
class MarkerStyle:
    begin: str
    end: str


@dataclass(frozen=True)
class MarkerSpan:
    begin_start: int
    end_end: int


MARKDOWN_MARKERS = MarkerStyle(BEGIN, END)
YAML_MARKERS = MarkerStyle(
    "# agent-context-maintainer:begin",
    "# agent-context-maintainer:end",
)


@dataclass(frozen=True)
class ScaffoldOptions:
    dry_run: bool = False
    force_recreate: bool = False
    append_generated_block: bool = False


@dataclass
class PlannedWrite:
    path: Path
    content: str
    action: str
    snapshot: bool
    write: bool = True


@dataclass(frozen=True)
class SkippedPath:
    path: str
    reason: str


@dataclass(frozen=True)
class InventoryScan:
    files: list[Path]
    skipped: list[SkippedPath]


def is_secret(path: Path) -> bool:
    name = path.name.lower()
    suffix = path.suffix.lower()
    return (
        name in SECRET_NAMES
        or name.startswith(".env.")
        or suffix in EXCLUDED_SUFFIXES
        or "credential" in name
        or "password" in name
        or "secret" in name
        or "token" in name
    )


def has_sensitive_component(path: Path) -> bool:
    for part in path.parts:
        normalized = part.lower()
        if normalized in SENSITIVE_DIR_COMPONENTS:
            return True
        if normalized in {"secret", "credential"}:
            return True
        if normalized.endswith(("-secrets", "_secrets", ".secrets")):
            return True
        if normalized.endswith(("-credentials", "_credentials", ".credentials")):
            return True
    return False


def is_binary_file(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            chunk = handle.read(4096)
    except OSError:
        return True
    return b"\0" in chunk


def git_ignored_paths(root: Path, paths: list[Path]) -> set[str]:
    if not paths:
        return set()
    top = git_top(root)
    if top is None:
        return set()
    path_map: dict[str, str] = {}
    for path in paths:
        try:
            top_rel = str((root / path).resolve().relative_to(top))
        except ValueError:
            continue
        path_map[top_rel] = str(path)
    if not path_map:
        return set()
    result = subprocess.run(
        ["git", "-C", str(top), "check-ignore", "--stdin"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        input="\n".join(path_map) + "\n",
        text=True,
    )
    if result.returncode not in (0, 1):
        return set()
    ignored: set[str] = set()
    for line in result.stdout.splitlines():
        root_rel = path_map.get(line)
        if root_rel is not None:
            ignored.add(root_rel)
    return ignored


def skip_directory_reason(path: Path, rel: Path) -> str | None:
    if path.name in EXCLUDED_DIRS:
        return "excluded-directory"
    if path.is_symlink():
        return "symlink-directory"
    if has_sensitive_component(rel):
        return "sensitive-directory"
    if rel.parts[:2] == (".agents", "snapshots"):
        # This tool's own pre-overwrite snapshots. Counting them would make
        # scaffold non-convergent: each update writes a snapshot, which would
        # change the inventory, which would change core.md again.
        return "tool-snapshot-directory"
    return None


def skip_file_reason(path: Path, rel: Path) -> str | None:
    suffix = path.suffix.lower()
    if path.is_symlink():
        return "symlink-file"
    if has_sensitive_component(rel.parent) or is_secret(path):
        return "sensitive-file"
    if suffix in ARCHIVE_SUFFIXES:
        return "archive-file"
    if suffix in BINARY_SUFFIXES:
        return "binary-file"
    try:
        stat = path.stat()
    except OSError:
        return "unreadable-file"
    if not path.is_file():
        return "non-regular-file"
    if stat.st_size > MAX_INVENTORY_FILE_BYTES:
        return "large-file"
    if is_binary_file(path):
        return "binary-file"
    return None


def scan_inventory(root: Path) -> InventoryScan:
    candidate_files: list[Path] = []
    candidate_dirs: list[Path] = []
    skipped: list[SkippedPath] = []

    for current, dirs, file_names in os.walk(root):
        current_path = Path(current)
        kept_dirs: list[str] = []
        for dir_name in dirs:
            path = current_path / dir_name
            try:
                rel = path.relative_to(root)
            except ValueError:
                continue
            reason = skip_directory_reason(path, rel)
            if reason:
                if len(skipped) < MAX_REPORTED_SKIPS:
                    skipped.append(SkippedPath(str(rel) + "/", reason))
                continue
            kept_dirs.append(dir_name)
            candidate_dirs.append(rel)
        # os.walk yields entries in filesystem order, which differs across
        # platforms; sort so generated lists are deterministic everywhere.
        dirs[:] = sorted(kept_dirs)
        for file_name in sorted(file_names):
            path = current_path / file_name
            try:
                rel = path.relative_to(root)
            except ValueError:
                continue
            reason = skip_file_reason(path, rel)
            if reason:
                if len(skipped) < MAX_REPORTED_SKIPS:
                    skipped.append(SkippedPath(str(rel), reason))
                continue
            candidate_files.append(rel)

    ignored = git_ignored_paths(root, candidate_dirs + candidate_files)
    ignored_dirs = {path for path in candidate_dirs if str(path) in ignored}
    for rel in sorted(ignored_dirs, key=str):
        if len(skipped) < MAX_REPORTED_SKIPS:
            skipped.append(SkippedPath(str(rel) + "/", "ignored-directory"))
    included_files: list[Path] = []
    for rel in candidate_files:
        ignored_by_parent = any(rel.is_relative_to(parent) for parent in ignored_dirs)
        if str(rel) in ignored or ignored_by_parent:
            if len(skipped) < MAX_REPORTED_SKIPS:
                skipped.append(SkippedPath(str(rel), "ignored-file"))
            continue
        included_files.append(rel)
    return InventoryScan(included_files, skipped)


def iter_files(root: Path):
    yield from scan_inventory(root).files


def inventory(root: Path, explain_skips: bool = False) -> dict[str, object]:
    scan = scan_inventory(root)
    files = scan.files
    manifests = [str(p) for p in files if p.name in MANIFESTS]
    docs = [
        str(p)
        for p in files
        if p.name.lower().startswith(("readme", "design", "contributing", "security"))
        or str(p).startswith(("docs/", ".docs/"))
        or p.name in {"AGENTS.md", "CLAUDE.md", "GEMINI.md", "copilot-instructions.md"}
    ]
    tests = [
        str(p)
        for p in files
        if "test" in p.parts or "tests" in p.parts or p.name.startswith("test_") or p.name.endswith("_test.go")
    ]
    lang_counts: dict[str, int] = {}
    for p in files:
        lang = LANG_EXTS.get(p.suffix.lower())
        if lang:
            lang_counts[lang] = lang_counts.get(lang, 0) + 1
    languages = [name for name, _ in sorted(lang_counts.items(), key=lambda item: (-item[1], item[0]))[:6]]
    result: dict[str, object] = {
        "root_name": root.name,
        "file_count": len(files),
        "languages": languages,
        "manifests": manifests[:20],
        "docs": docs[:30],
        "tests": tests[:30],
    }
    if explain_skips:
        result["skipped"] = [{"path": item.path, "reason": item.reason} for item in scan.skipped]
    return result


def detect_agent() -> tuple[str, str | None]:
    """Detect the active agent runtime from exact-match environment variables.

    Returns (agent, matched_variable). Falls back to ("generic", None) when no
    confirmed variable is present; substring matching is deliberately avoided
    because unrelated variables (for example COPILOT_OTEL_FILE_EXPORTER_PATH in
    non-Copilot sessions) make prefixes unreliable signals.
    """
    for key in DETECT_PRIORITY:
        for var in PROVIDERS[key]["detect_env"]:
            if var in os.environ:
                return key, var
    return "generic", None


def bullet_list(items: list[str], fallback: str) -> str:
    if not items:
        return f"- {fallback}"
    # Continuation lines carry the 4-space indent of the template f-strings so
    # that dedent() still finds a uniform prefix; otherwise the interpolated
    # lines would disable dedenting and leak indentation into the output,
    # which Markdown renders as code blocks.
    return "\n    ".join(f"- `{item}`" for item in items)


def generated_block(body: str, markers: MarkerStyle = MARKDOWN_MARKERS) -> str:
    return f"{markers.begin}\n{body.strip()}\n{markers.end}\n"


def generated_file_content(
    body: str,
    heading: str | None = None,
    markers: MarkerStyle = MARKDOWN_MARKERS,
) -> str:
    prefix = f"# {heading}\n\n" if heading else ""
    return prefix + generated_block(body, markers)


def marker_events(text: str, markers: MarkerStyle = MARKDOWN_MARKERS) -> list[tuple[str, int, int]]:
    events: list[tuple[str, int, int]] = []
    in_fence = False
    fence_prefix = ""
    offset = 0
    ignore_fences = markers == MARKDOWN_MARKERS

    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        lstripped = line.lstrip()
        if ignore_fences and (lstripped.startswith("```") or lstripped.startswith("~~~")):
            prefix = lstripped[:3]
            if not in_fence:
                in_fence = True
                fence_prefix = prefix
            elif prefix == fence_prefix:
                in_fence = False
                fence_prefix = ""
            offset += len(line)
            continue
        if not in_fence:
            if stripped == markers.begin:
                events.append(("begin", offset, offset + len(line)))
            elif stripped == markers.end:
                events.append(("end", offset, offset + len(line)))
        offset += len(line)
    return events


def generated_block_span(text: str, markers: MarkerStyle = MARKDOWN_MARKERS) -> MarkerSpan | None:
    events = marker_events(text, markers)
    if len(events) != 2 or events[0][0] != "begin" or events[1][0] != "end":
        return None
    return MarkerSpan(events[0][1], events[1][2])


def marker_error(path: Path, text: str, markers: MarkerStyle = MARKDOWN_MARKERS) -> str | None:
    events = marker_events(text, markers)
    begin_count = sum(1 for kind, _, _ in events if kind == "begin")
    end_count = sum(1 for kind, _, _ in events if kind == "end")
    rel = str(path)
    if begin_count != end_count:
        return f"{rel} has mismatched generated block markers ({begin_count} begin, {end_count} end)"
    if begin_count > 1:
        return f"{rel} has multiple generated blocks; refusing ambiguous update"
    if begin_count == 1 and events[0][0] != "begin":
        return f"{rel} has generated block markers in the wrong order"
    return None


def markdown_without_code_fences(text: str) -> str:
    lines = []
    in_fence = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            lines.append(line)
    return "\n".join(lines)


def has_claude_agents_import(text: str) -> bool:
    visible = HTML_COMMENT_RE.sub("", markdown_without_code_fences(text))
    return any(line.strip() == "@AGENTS.md" for line in visible.splitlines())


def without_generated_block(text: str, markers: MarkerStyle = MARKDOWN_MARKERS) -> str:
    span = generated_block_span(text, markers)
    if span is None:
        return text
    return text[: span.begin_start] + text[span.end_end :]


def generated_block_from_content(text: str, markers: MarkerStyle = MARKDOWN_MARKERS) -> str:
    span = generated_block_span(text, markers)
    if span is None:
        raise AgentContextError("generated content has no valid generated block")
    block = text[span.begin_start : span.end_end]
    return block if block.endswith("\n") else block + "\n"


def replace_generated_block(
    current: str,
    generated_content: str,
    markers: MarkerStyle = MARKDOWN_MARKERS,
) -> str:
    span = generated_block_span(current, markers)
    if span is None:
        raise AgentContextError("current content has no valid generated block")
    replacement = generated_block_from_content(generated_content, markers).rstrip()
    return current[: span.begin_start] + replacement + current[span.end_end :]


def append_generated_block(
    current: str,
    generated_content: str,
    markers: MarkerStyle = MARKDOWN_MARKERS,
) -> str:
    separator = "\n\n" if current.endswith("\n") else "\n\n"
    return current + separator + generated_block_from_content(generated_content, markers)


def generated_block_changed(
    root: Path,
    path: Path,
    current: str,
    markers: MarkerStyle = MARKDOWN_MARKERS,
) -> bool:
    head = git_head_text(root, path)
    if head is None:
        return False
    if marker_error(path, current, markers) or marker_error(path, head, markers):
        return False
    if generated_block_span(current, markers) is None or generated_block_span(head, markers) is None:
        return False
    return generated_block_from_content(current, markers) != generated_block_from_content(head, markers)


def is_generated_only(
    path: Path,
    text: str,
    heading: str | None,
    markers: MarkerStyle = MARKDOWN_MARKERS,
) -> bool:
    error = marker_error(path, text, markers)
    if error:
        return False
    if generated_block_span(text, markers) is None:
        return False
    outside = without_generated_block(text, markers).strip()
    return outside == (f"# {heading}" if heading else "")


def git_run(root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def in_git_repo(root: Path) -> bool:
    return git_run(root, ["rev-parse", "--is-inside-work-tree"]).returncode == 0


def git_top(root: Path) -> Path | None:
    result = git_run(root, ["rev-parse", "--show-toplevel"])
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip()).resolve()


def git_rel(root: Path, path: Path) -> str:
    top = git_top(root)
    if top is None:
        return str(path.relative_to(root))
    return str(path.resolve().relative_to(top))


def git_tracked(root: Path, path: Path) -> bool:
    return git_run(root, ["ls-files", "--error-unmatch", "--", git_rel(root, path)]).returncode == 0


def git_clean(root: Path, path: Path) -> bool:
    result = git_run(root, ["status", "--porcelain", "--", git_rel(root, path)])
    return result.returncode == 0 and result.stdout.strip() == ""


def git_head_text(root: Path, path: Path) -> str | None:
    result = git_run(root, ["show", f"HEAD:{git_rel(root, path)}"])
    if result.returncode != 0:
        return None
    return result.stdout


def only_generated_changed(
    root: Path,
    path: Path,
    current: str,
    markers: MarkerStyle = MARKDOWN_MARKERS,
) -> bool:
    head = git_head_text(root, path)
    if head is None:
        return False
    if marker_error(path, current, markers) or marker_error(path, head, markers):
        return False
    return without_generated_block(current, markers) == without_generated_block(head, markers)


def should_snapshot_generated_update(
    root: Path,
    path: Path,
    current: str,
    markers: MarkerStyle = MARKDOWN_MARKERS,
) -> bool:
    if not in_git_repo(root) or not git_tracked(root, path):
        return True
    return generated_block_changed(root, path, current, markers)


def merge_gemini_settings(current: str | None = None) -> str:
    if current is None:
        data: dict[str, object] = {}
    else:
        loaded = json.loads(current)
        if not isinstance(loaded, dict):
            raise AgentContextError(".gemini/settings.json must contain a JSON object")
        data = dict(loaded)

    context_names = data.get("contextFileName")
    if isinstance(context_names, str):
        names = [context_names]
    elif isinstance(context_names, list):
        names = [item for item in context_names if isinstance(item, str)]
    else:
        names = []
    for expected in ("GEMINI.md", "AGENTS.md"):
        if expected not in names:
            names.append(expected)
    data["contextFileName"] = names

    file_filtering = data.get("fileFiltering")
    if not isinstance(file_filtering, dict):
        file_filtering = {}
    file_filtering.setdefault("respectGitIgnore", True)
    data["fileFiltering"] = file_filtering

    return json.dumps(data, indent=2) + "\n"


def classify_gemini_settings(root: Path, path: Path, options: ScaffoldOptions) -> PlannedWrite:
    if path.is_symlink():
        raise AgentContextError(f"{path} is a symlink; refusing to update scaffold target")
    if not path.exists():
        return PlannedWrite(path, merge_gemini_settings(), "created", False)
    if not path.is_file():
        raise AgentContextError(f"{path} is not a regular file; refusing to update scaffold target")
    current = path.read_text(encoding="utf-8")
    if options.force_recreate:
        content = merge_gemini_settings()
        return PlannedWrite(path, content, "force-recreated", True)
    try:
        content = merge_gemini_settings(current)
    except json.JSONDecodeError as error:
        raise AgentContextError(
            f".gemini/settings.json is not valid JSON ({error}); pass --force-recreate to replace it"
        ) from error
    if current == content:
        return PlannedWrite(path, content, "unchanged", False, False)
    return PlannedWrite(path, content, "updated-json-settings", True)


def classify_recreate(
    root: Path,
    path: Path,
    content: str,
    heading: str | None,
    options: ScaffoldOptions,
    markers: MarkerStyle | None = MARKDOWN_MARKERS,
) -> PlannedWrite:
    if path.is_symlink():
        raise AgentContextError(f"{path} is a symlink; refusing to update scaffold target")
    if not path.exists():
        return PlannedWrite(path, content, "created", False)
    if not path.is_file():
        raise AgentContextError(f"{path} is not a regular file; refusing to update scaffold target")
    current = path.read_text(encoding="utf-8")
    if current == content:
        return PlannedWrite(path, content, "unchanged", False, False)
    if options.force_recreate:
        return PlannedWrite(path, content, "force-recreated", True)
    if markers is None:
        raise AgentContextError(
            f"{path} has no safe generated block marker; pass --force-recreate to replace it"
        )
    error = marker_error(path, current, markers)
    if error:
        raise AgentContextError(error)
    if generated_block_span(current, markers) is not None:
        updated = replace_generated_block(current, content, markers)
        if updated == current:
            return PlannedWrite(path, updated, "unchanged", False, False)
        snapshot = should_snapshot_generated_update(root, path, current, markers)
        return PlannedWrite(path, updated, "updated-generated-block", snapshot)
    if options.append_generated_block:
        if markers != MARKDOWN_MARKERS or path.suffix.lower() != ".md":
            raise AgentContextError(f"{path} cannot safely append a generated block; use --force-recreate")
        appended = append_generated_block(current, content, markers)
        return PlannedWrite(path, appended, "appended-generated-block", False)
    raise AgentContextError(
        f"{path} has no generated block marker; pass --append-generated-block to preserve it "
        "and add a managed block, or --force-recreate to replace it"
    )


def snapshot_before_recreate(root: Path, planned: list[PlannedWrite]) -> None:
    dirty = [item for item in planned if item.write and item.snapshot and item.path.exists()]
    if not dirty:
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    snapshot_root = root / ".agents" / "snapshots" / "agent-context-maintainer" / stamp
    snapshot_root.mkdir(parents=True, exist_ok=True)
    manifest = []
    for item in dirty:
        rel = git_rel(root, item.path)
        safe_name = rel.replace("/", "__")
        manifest.append(f"{rel}: {item.action}")
        if in_git_repo(root) and git_tracked(root, item.path):
            diff = git_run(root, ["diff", "--", rel]).stdout
            staged = git_run(root, ["diff", "--cached", "--", rel]).stdout
            (snapshot_root / f"{safe_name}.diff").write_text(diff + staged, encoding="utf-8")
        else:
            (snapshot_root / f"{safe_name}.before").write_text(item.path.read_text(encoding="utf-8"), encoding="utf-8")
    (snapshot_root / "manifest.txt").write_text("\n".join(manifest) + "\n", encoding="utf-8")


def apply_planned_writes(root: Path, planned: list[PlannedWrite]) -> list[tuple[str, Path]]:
    snapshot_before_recreate(root, planned)
    changes: list[tuple[str, Path]] = []
    for item in planned:
        if not item.write:
            continue
        item.path.parent.mkdir(parents=True, exist_ok=True)
        item.path.write_text(item.content, encoding="utf-8")
        changes.append((item.action, item.path))
    return changes


def agents_body(inv: dict[str, object]) -> str:
    return """
    ## Agent Context Entry

    Always read these files before making repository changes:

    1. `.agents/core.md`
    2. `.agents/routing.md`
    3. The matching provider profile in `.agents/profiles/`; if unsure, read `.agents/profiles/generic.md`

    If `.agents/routing.md` routes the task to a skill, read that `SKILL.md` before editing.
    """


def claude_body(inv: dict[str, object]) -> str:
    return """
    @AGENTS.md

    ## Claude Code

    Use `AGENTS.md` as the shared source of truth for repository instructions. For Claude-specific behavior, also follow `.agents/profiles/claude.md` when present.
    """


def gemini_body(inv: dict[str, object]) -> str:
    return """
    ## Gemini CLI Bridge

    Use `AGENTS.md` as the shared source of truth for repository instructions. If Gemini CLI has not already loaded it, read it before editing.

    Also follow `.agents/profiles/gemini.md` for Gemini-specific behavior. Project settings in `.gemini/settings.json` may list both `GEMINI.md` and `AGENTS.md` as accepted context files.
    """


def copilot_instructions_body(inv: dict[str, object]) -> str:
    return """
    ## GitHub Copilot Bridge

    Use `AGENTS.md` as the shared source of truth for repository instructions. For GitHub Copilot-specific behavior, also follow `.agents/profiles/copilot.md` when present.

    Keep repository-wide Copilot guidance concise, durable, and not task-specific. Put path-specific or workflow-specific details in routed `.agents/skills/*/SKILL.md` files instead of duplicating them here.
    """


def gemini_settings_content() -> str:
    return merge_gemini_settings()


def provider_registry_body() -> str:
    lines = [
        "schema_version: 1",
        f'reviewed: "{PROVIDER_REGISTRY_REVIEWED}"',
        "providers:",
    ]
    for key, spec in PROVIDERS.items():
        bridge_files = ", ".join(f'"{item}"' for item in spec["bridge_files"])
        lines.append(f"  {key}:")
        lines.append(f'    profile: ".agents/profiles/{key}.md"')
        lines.append(f"    bridge_files: [{bridge_files}]")
        lines.append("    source_urls:")
        for url in spec["source_urls"]:
            lines.append(f'      - "{url}"')
    lines.extend(
        [
            "notes:",
            '  - "Provider bridge files should point back to AGENTS.md instead of duplicating shared policy."',
            '  - "When a provider changes its loading contract, update this registry, the bridge file, and the matching profile together."',
        ]
    )
    return "\n".join(lines)


def core_body(inv: dict[str, object]) -> str:
    languages = ", ".join(inv["languages"]) if inv["languages"] else "needs confirmation"
    return f"""
    ## Repository Snapshot

    - Root: `{inv["root_name"]}`
    - Detected languages: {languages}
    - Approximate tracked context files scanned: {inv["file_count"]}

    ## Detected Manifests

    {bullet_list(inv["manifests"], "No common manifest detected. Confirm project type manually.")}

    ## Detected Documentation

    {bullet_list(inv["docs"], "No root documentation detected. Create or identify the source of truth before broad edits.")}

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
    """


def routing_body(inv: dict[str, object]) -> str:
    return f"""
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

    {bullet_list(inv["tests"], "No obvious tests detected. Identify the narrowest available validation manually.")}

    ## Missing Context Rule

    If required context is absent, state the gap clearly, make the safest local assumption, and avoid broad rewrites.
    """


def profile_body(profile: str, active_agent: str) -> str:
    active = "yes" if profile == active_agent else "no"
    spec = PROVIDERS[profile]
    # See bullet_list() for why continuation lines carry the template indent.
    bullets = "\n    ".join(f"- {item}" for item in spec["profile_bullets"])
    title = spec["title"]
    return f"""
    ## {title} Profile

    - Active detected profile: {active}

    ## Behavior

    {bullets}
    """


def scaffold(root: Path, agent: str, options: ScaffoldOptions | None = None) -> list[tuple[str, Path]]:
    options = options or ScaffoldOptions()
    inv = inventory(root)
    active = detect_agent()[0] if agent == "auto" else agent
    if active not in PROFILES:
        active = "generic"
    targets = [
        (
            root / "AGENTS.md",
            generated_file_content(dedent(agents_body(inv)), "Agent Instructions"),
            "Agent Instructions",
            MARKDOWN_MARKERS,
        ),
        (
            root / "CLAUDE.md",
            generated_file_content(dedent(claude_body(inv)), "Claude Code Instructions"),
            "Claude Code Instructions",
            MARKDOWN_MARKERS,
        ),
        (
            root / "GEMINI.md",
            generated_file_content(dedent(gemini_body(inv)), "Gemini CLI Instructions"),
            "Gemini CLI Instructions",
            MARKDOWN_MARKERS,
        ),
        (
            root / ".github" / "copilot-instructions.md",
            generated_file_content(dedent(copilot_instructions_body(inv)), "GitHub Copilot Instructions"),
            "GitHub Copilot Instructions",
            MARKDOWN_MARKERS,
        ),
        (
            root / ".agents" / "core.md",
            generated_file_content(dedent(core_body(inv)), "Core Agent Context"),
            "Core Agent Context",
            MARKDOWN_MARKERS,
        ),
        (
            root / ".agents" / "routing.md",
            generated_file_content(dedent(routing_body(inv)), "Agent Routing"),
            "Agent Routing",
            MARKDOWN_MARKERS,
        ),
        (
            root / ".agents" / "provider-registry.yaml",
            generated_file_content(dedent(provider_registry_body()), None, YAML_MARKERS),
            None,
            YAML_MARKERS,
        ),
    ]
    planned: list[PlannedWrite] = []
    for path, content, heading, markers in targets:
        planned.append(classify_recreate(root, path, content, heading, options, markers))
    planned.append(classify_gemini_settings(root, root / ".gemini" / "settings.json", options))
    for profile in PROFILES:
        path = root / ".agents" / "profiles" / f"{profile}.md"
        heading = f"{PROVIDERS[profile]['title']} Agent Profile"
        content = generated_file_content(dedent(profile_body(profile, active)), heading)
        planned.append(classify_recreate(root, path, content, heading, options, MARKDOWN_MARKERS))
    if options.dry_run:
        return [(f"would-{item.action}", item.path) for item in planned if item.write]
    changes = apply_planned_writes(root, planned)
    skills_dir = root / ".agents" / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    return changes


def check(root: Path) -> list[str]:
    errors: list[str] = []
    required = [
        root / "AGENTS.md",
        root / "CLAUDE.md",
        root / "GEMINI.md",
        root / ".github" / "copilot-instructions.md",
        root / ".agents" / "core.md",
        root / ".agents" / "routing.md",
        root / ".agents" / "provider-registry.yaml",
        root / ".gemini" / "settings.json",
        root / ".agents" / "skills",
    ]
    required.extend(root / ".agents" / "profiles" / f"{profile}.md" for profile in PROFILES)
    for path in required:
        if not path.exists():
            errors.append(f"missing: {path.relative_to(root)}")
    if (root / "AGENTS.md").exists():
        text = (root / "AGENTS.md").read_text(encoding="utf-8")
        for ref in (".agents/core.md", ".agents/routing.md", ".agents/profiles/"):
            if ref not in text:
                errors.append(f"AGENTS.md does not reference {ref}")
    if (root / "CLAUDE.md").exists():
        text = (root / "CLAUDE.md").read_text(encoding="utf-8")
        if not has_claude_agents_import(text):
            errors.append("CLAUDE.md does not import @AGENTS.md")
    if (root / "GEMINI.md").exists():
        text = (root / "GEMINI.md").read_text(encoding="utf-8")
        for ref in ("AGENTS.md", ".agents/profiles/gemini.md"):
            if ref not in text:
                errors.append(f"GEMINI.md does not reference {ref}")
    if (root / ".github" / "copilot-instructions.md").exists():
        text = (root / ".github" / "copilot-instructions.md").read_text(encoding="utf-8")
        for ref in ("AGENTS.md", ".agents/profiles/copilot.md"):
            if ref not in text:
                errors.append(f".github/copilot-instructions.md does not reference {ref}")
    settings_path = root / ".gemini" / "settings.json"
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            errors.append(f".gemini/settings.json is not valid JSON: {error}")
        else:
            context_names = settings.get("contextFileName")
            if isinstance(context_names, str):
                context_names = [context_names]
            if not isinstance(context_names, list):
                errors.append(".gemini/settings.json must set contextFileName")
            else:
                for expected in ("GEMINI.md", "AGENTS.md"):
                    if expected not in context_names:
                        errors.append(f".gemini/settings.json contextFileName does not include {expected}")
    context_files = [
        (root / "AGENTS.md", MARKDOWN_MARKERS),
        (root / "CLAUDE.md", MARKDOWN_MARKERS),
        (root / "GEMINI.md", MARKDOWN_MARKERS),
        (root / ".github" / "copilot-instructions.md", MARKDOWN_MARKERS),
        (root / ".agents" / "core.md", MARKDOWN_MARKERS),
        (root / ".agents" / "routing.md", MARKDOWN_MARKERS),
        (root / ".agents" / "provider-registry.yaml", YAML_MARKERS),
        *((root / ".agents" / "profiles" / f"{profile}.md", MARKDOWN_MARKERS) for profile in PROFILES),
    ]
    for path, markers in context_files:
        if not path.exists() or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        error = marker_error(path.relative_to(root), text, markers)
        if error:
            errors.append(error)
        for ref in sorted(set(AGENTS_REF_RE.findall(text))):
            if "*" in ref or "<" in ref or ">" in ref:
                continue
            target = root / ref
            if ref.endswith("/"):
                if not target.is_dir():
                    errors.append(f"{path.relative_to(root)} references missing directory: {ref}")
            elif not target.exists():
                errors.append(f"{path.relative_to(root)} references missing path: {ref}")
    return errors


def print_providers(json_output: bool = False) -> None:
    if json_output:
        payload = {
            key: {
                "profile": f".agents/profiles/{key}.md",
                "bridge_files": spec["bridge_files"],
                "detect_env": spec["detect_env"],
                "source_urls": spec["source_urls"],
            }
            for key, spec in PROVIDERS.items()
        }
        print(json.dumps(payload, indent=2))
        return
    for key, spec in PROVIDERS.items():
        detect = ", ".join(f"${var}" for var in spec["detect_env"]) or "manual only (--agent)"
        print(f"{key}:")
        print(f"  profile: .agents/profiles/{key}.md")
        print(f"  bridges: {', '.join(spec['bridge_files'])}")
        print(f"  auto-detect: {detect}")


def print_inventory(root: Path, json_output: bool = False, explain_skips: bool = False) -> None:
    inv = inventory(root, explain_skips=explain_skips)
    if json_output:
        print(json.dumps(inv, indent=2, sort_keys=True))
        return
    print(f"root: {inv['root_name']}")
    print(f"file_count: {inv['file_count']}")
    print("languages:")
    for item in inv["languages"]:
        print(f"  - {item}")
    print("manifests:")
    for item in inv["manifests"]:
        print(f"  - {item}")
    print("docs:")
    for item in inv["docs"]:
        print(f"  - {item}")
    print("tests:")
    for item in inv["tests"]:
        print(f"  - {item}")
    if explain_skips:
        print("skipped:")
        for item in inv.get("skipped", []):
            print(f"  - {item['path']}: {item['reason']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    providers_parser = subparsers.add_parser("providers", help="list supported providers and bridges")
    providers_parser.add_argument("--json", action="store_true", help="print providers as JSON")

    for name in ("inventory", "check", "scaffold"):
        sub = subparsers.add_parser(name)
        sub.add_argument("root", nargs="?", default=".")
        if name == "inventory":
            sub.add_argument("--json", action="store_true", help="print inventory as JSON")
            sub.add_argument("--explain-skips", action="store_true", help="include skipped paths and reasons")
        if name == "scaffold":
            sub.add_argument("--agent", default="auto", choices=("auto",) + PROFILES)
            sub.add_argument("--dry-run", action="store_true", help="show planned writes without changing files")
            sub.add_argument(
                "--force-recreate",
                action="store_true",
                help="replace existing scaffold targets even when they have no generated marker",
            )
            sub.add_argument(
                "--append-generated-block",
                action="store_true",
                help="append a generated block to existing unmarked Markdown targets",
            )

    args = parser.parse_args()
    if args.command == "providers":
        print_providers(json_output=args.json)
        return 0
    root = Path(args.root).resolve()
    if not root.exists() or not root.is_dir():
        parser.error(f"root is not a directory: {root}")

    if args.command == "inventory":
        print_inventory(root, json_output=args.json, explain_skips=args.explain_skips)
        return 0
    if args.command == "check":
        errors = check(root)
        if errors:
            for error in errors:
                print(error)
            return 1
        print("agent context check passed")
        return 0
    if args.command == "scaffold":
        agent = args.agent
        if agent == "auto":
            agent, source = detect_agent()
            if source is not None:
                print(f"detected: {agent} (from ${source})")
            else:
                print("detected: generic (no known agent environment variables; pass --agent to override)")
        try:
            options = ScaffoldOptions(
                dry_run=args.dry_run,
                force_recreate=args.force_recreate,
                append_generated_block=args.append_generated_block,
            )
            changes = scaffold(root, agent, options)
        except AgentContextError as error:
            print(f"refusing scaffold: {error}")
            return 1
        if not changes:
            print("no changes")
        for action, path in changes:
            print(f"{action}: {path.relative_to(root)}")
        if args.dry_run:
            return 0
        errors = check(root)
        if errors:
            for error in errors:
                print(error)
            return 1
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
