#!/usr/bin/env python3
"""Rename old numeric character folders to the new <safe_name>_<chat_id> format.

Scans the output directory for folders whose name is just a chat_id number and
that contain raw/meta.json. Reads the character name from meta.json, computes
the same safe folder name used by pipeline.py, and renames the folder.

Usage:
    cd /Users/akb/.qoderwork/tipsy-crawler
    source venv/bin/activate
    python -m tools.rename_old_folders \
        /Users/akb/Documents/AKB_file/内容/character_asset/Tipsy角色卡洗卡测试
"""

import json
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple


def safe_filename(name: str, max_len: int = 40) -> str:
    """Sanitize a string for use in folder/file names.

    Mirrors CrawlPipeline._safe_filename.
    """
    safe = re.sub(r"[^\w\s-]", "", name, flags=re.UNICODE)
    safe = re.sub(r"[\s_]+", "_", safe.strip())
    safe = safe.strip("_-")
    safe = safe[:max_len].strip("_-")
    return safe or "unknown"


def new_folder_name(meta_path: Path) -> Optional[str]:
    """Return the new folder name for a numeric folder, or None if not applicable."""
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    name = data.get("name", "").strip()
    chat_id = data.get("chat_id", "").strip()
    if not chat_id:
        return None
    slug = safe_filename(name)
    return f"{slug}_{chat_id}"


def _unique_dir(old_dir: Path, new_name: str) -> Path:
    new_dir = old_dir.with_name(new_name)
    counter = 1
    original_new_dir = new_dir
    while new_dir.exists():
        new_dir = original_new_dir.with_name(f"{original_new_dir.name}_{counter}")
        counter += 1
    return new_dir


def rename_character_folders(output_dir: Path, dry_run: bool = False) -> List[Tuple[Path, Path]]:
    """Find and rename numeric character folders."""
    output_dir = output_dir.resolve()
    moves: List[Tuple[Path, Path]] = []

    for meta_path in output_dir.rglob("raw/meta.json"):
        old_dir = meta_path.parent.parent
        # Only rename folders that are purely numeric chat ids
        if not old_dir.name.isdigit():
            continue

        new_name = new_folder_name(meta_path)
        if not new_name or new_name == old_dir.name:
            continue

        new_dir = _unique_dir(old_dir, new_name)
        moves.append((old_dir, new_dir))

    for old_dir, new_dir in moves:
        if dry_run:
            print(f"[dry-run char] {old_dir.name} -> {new_dir.name}")
        else:
            old_dir.rename(new_dir)
            print(f"[renamed char] {old_dir} -> {new_dir}")

    return moves


def rename_author_folders(output_dir: Path, dry_run: bool = False) -> List[Tuple[Path, Path]]:
    """Rename numeric author folders using names from authors.json."""
    output_dir = output_dir.resolve()
    moves: List[Tuple[Path, Path]] = []

    authors_path = output_dir / "authors.json"
    if not authors_path.exists():
        print("[authors] authors.json not found, skipping author folder rename")
        return moves

    try:
        authors = json.loads(authors_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[authors] failed to read authors.json: {exc}", file=sys.stderr)
        return moves

    for entry in authors:
        uid = str(entry.get("uid", "")).strip()
        name = str(entry.get("name", "")).strip()
        if not uid or not name or name == uid:
            continue
        old_dir = output_dir / uid
        if not old_dir.is_dir():
            continue
        new_name = f"{safe_filename(name)}_{uid}"
        if new_name == uid:
            continue
        new_dir = _unique_dir(old_dir, new_name)
        moves.append((old_dir, new_dir))

    for old_dir, new_dir in moves:
        if dry_run:
            print(f"[dry-run author] {old_dir.name} -> {new_dir.name}")
        else:
            old_dir.rename(new_dir)
            print(f"[renamed author] {old_dir} -> {new_dir}")

    return moves


def main() -> int:
    if len(sys.argv) < 2:
        print(
            "Usage: python -m tools.rename_old_folders <output_dir> [--dry-run]",
            file=sys.stderr,
        )
        return 1

    output_dir = Path(sys.argv[1])
    dry_run = "--dry-run" in sys.argv

    if not output_dir.is_dir():
        print(f"Output directory does not exist: {output_dir}", file=sys.stderr)
        return 1

    char_moves = rename_character_folders(output_dir, dry_run=dry_run)
    author_moves = rename_author_folders(output_dir, dry_run=dry_run)
    action = "would rename" if dry_run else "renamed"
    print(f"\n{action} {len(char_moves)} character folder(s)")
    print(f"{action} {len(author_moves)} author folder(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
