#!/usr/bin/env python3
# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0
"""Validate marketplace catalogs, plugin manifests, and skills.

Checks (stdlib only, run from anywhere):
  - Every marketplace catalog (Claude, Codex, Cursor) parses as JSON.
  - Every plugin directory under plugins/ is listed in every catalog, and
    every catalog entry points to an existing plugin directory.
  - Each plugin has a Claude, Codex, and Cursor plugin.json whose name
    matches the directory and whose versions agree with each other and
    with the Claude catalog entry.
  - Each plugin has at least one skill, and every SKILL.md has YAML
    frontmatter with a `name` matching its directory and a `description`.

Exit code 0 on success, 1 if any check fails.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGINS_DIR = ROOT / "plugins"

CATALOGS = {
    "claude": ROOT / ".claude-plugin" / "marketplace.json",
    "codex": ROOT / ".agents" / "plugins" / "marketplace.json",
    "cursor": ROOT / ".cursor-plugin" / "marketplace.json",
}
MANIFESTS = {
    "claude": Path(".claude-plugin") / "plugin.json",
    "codex": Path(".codex-plugin") / "plugin.json",
    "cursor": Path(".cursor-plugin") / "plugin.json",
}
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

errors: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        err(f"missing file: {path.relative_to(ROOT)}")
    except json.JSONDecodeError as e:
        err(f"invalid JSON in {path.relative_to(ROOT)}: {e}")
    return None


def catalog_source_path(tool: str, entry: dict) -> str | None:
    """Return the plugin path a catalog entry points to."""
    src = entry.get("source")
    if tool == "codex":
        return src.get("path") if isinstance(src, dict) else None
    return src if isinstance(src, str) else None


def parse_frontmatter(text: str) -> dict[str, str] | None:
    """Minimal YAML frontmatter reader: top-level keys, incl. folded (>) values."""
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    fields: dict[str, str] = {}
    key = None
    for line in text[4:end].splitlines():
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if m:
            key, value = m.group(1), m.group(2).strip()
            fields[key] = "" if value in (">", "|", ">-", "|-") else value
        elif key and line.startswith((" ", "\t")):
            fields[key] = (fields[key] + " " + line.strip()).strip()
    return fields


def check_skills(plugin_dir: Path) -> None:
    skill_files = sorted((plugin_dir / "skills").glob("*/SKILL.md"))
    rel = plugin_dir.relative_to(ROOT)
    if not skill_files:
        err(f"{rel}: no skills found (expected skills/<name>/SKILL.md)")
    for skill_md in skill_files:
        srel = skill_md.relative_to(ROOT)
        fm = parse_frontmatter(skill_md.read_text(encoding="utf-8"))
        if fm is None:
            err(f"{srel}: missing or malformed YAML frontmatter")
            continue
        if fm.get("name") != skill_md.parent.name:
            err(f"{srel}: frontmatter name {fm.get('name')!r} must equal directory name {skill_md.parent.name!r}")
        if not fm.get("description"):
            err(f"{srel}: frontmatter description is required")


def main() -> int:
    catalogs = {tool: load_json(path) for tool, path in CATALOGS.items()}
    plugin_dirs = sorted(p for p in PLUGINS_DIR.iterdir() if p.is_dir()) if PLUGINS_DIR.is_dir() else []
    plugin_names = {p.name for p in plugin_dirs}

    # Catalog <-> plugin directory consistency
    claude_versions: dict[str, str] = {}
    for tool, catalog in catalogs.items():
        if catalog is None:
            continue
        listed = set()
        for entry in catalog.get("plugins", []):
            name = entry.get("name")
            listed.add(name)
            path = catalog_source_path(tool, entry)
            if path != f"./plugins/{name}":
                err(f"{tool} catalog: plugin {name!r} source should be './plugins/{name}', got {path!r}")
            if name not in plugin_names:
                err(f"{tool} catalog: plugin {name!r} has no directory under plugins/")
            if tool == "claude" and "version" in entry:
                claude_versions[name] = entry["version"]
        for missing in sorted(plugin_names - listed):
            err(f"{tool} catalog: plugin directory plugins/{missing} is not listed")

    # Per-plugin manifests and skills
    for plugin_dir in plugin_dirs:
        name = plugin_dir.name
        if not NAME_RE.match(name):
            err(f"plugins/{name}: name must be lowercase kebab-case")
        versions = {}
        for tool, rel_manifest in MANIFESTS.items():
            manifest = load_json(plugin_dir / rel_manifest)
            if manifest is None:
                continue
            if manifest.get("name") != name:
                err(f"plugins/{name}/{rel_manifest}: name {manifest.get('name')!r} must equal {name!r}")
            if "version" in manifest:
                versions[tool] = manifest["version"]
        if name in claude_versions:
            versions["claude catalog"] = claude_versions[name]
        if len(set(versions.values())) > 1:
            err(f"plugins/{name}: version mismatch {versions}")
        check_skills(plugin_dir)

    if errors:
        print("Validation FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"Validation passed: {len(plugin_dirs)} plugin(s), {len(CATALOGS)} catalogs.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
