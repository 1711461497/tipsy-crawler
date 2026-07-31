#!/usr/bin/env python3
"""Fetch missing author display names and rename numeric author folders.

Scans the output directory for author folders that are just numeric UIDs,
loads each profile page to get the author's display name, updates
authors.json, and renames the folder to <safe_name>_<uid>.

Usage:
    cd /Users/akb/.qoderwork/tipsy-crawler
    source venv/bin/activate
    python -m tools.populate_author_names \
        /Users/akb/Documents/AKB_file/内容/character_asset/Tipsy角色卡洗卡测试
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import List, Tuple


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tipsy_crawler.scraper import TipsyScraper  # noqa: E402
from tipsy_crawler.pipeline import CrawlPipeline  # noqa: E402


def _safe_name(name: str) -> str:
    return CrawlPipeline._safe_filename(name)


def _unique_dir(old_dir: Path, new_name: str) -> Path:
    new_dir = old_dir.with_name(new_name)
    counter = 1
    original_new_dir = new_dir
    while new_dir.exists():
        new_dir = original_new_dir.with_name(f"{original_new_dir.name}_{counter}")
        counter += 1
    return new_dir


def load_authors(output_dir: Path) -> List[dict]:
    path = output_dir / "authors.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[warn] failed to read authors.json: {exc}", file=sys.stderr)
        return []


def save_authors(output_dir: Path, authors: List[dict]) -> None:
    path = output_dir / "authors.json"
    path.write_text(json.dumps(authors, indent=2, ensure_ascii=False), encoding="utf-8")


async def populate_and_rename(output_dir: Path, dry_run: bool = False) -> None:
    output_dir = output_dir.resolve()
    authors = load_authors(output_dir)
    authors_by_uid = {str(a.get("uid", "")): a for a in authors}

    # Numeric folders at the output root are candidate author folders
    candidate_dirs = [d for d in output_dir.iterdir() if d.is_dir() and d.name.isdigit()]

    async with TipsyScraper(headless=True, use_stealth=True) as scraper:
        for old_dir in candidate_dirs:
            uid = old_dir.name
            url = f"https://tipsy.chat/profile/{uid}?tab=Characters"
            try:
                fetched_uid, name = await scraper.fetch_author_name(url)
            except Exception as exc:
                print(f"[error] {uid}: {exc}")
                continue

            if not name or name == uid:
                print(f"[skip] {uid}: no display name found")
                continue

            # Update authors.json entry
            entry = authors_by_uid.get(uid)
            if entry is None:
                entry = {"uid": uid, "url": url, "character_count": 0}
                authors.append(entry)
                authors_by_uid[uid] = entry
            entry["name"] = name

            new_name = f"{_safe_name(name)}_{uid}"
            if new_name == uid:
                print(f"[skip] {uid}: sanitized name is empty")
                continue

            new_dir = _unique_dir(old_dir, new_name)
            if dry_run:
                print(f"[dry-run] {old_dir.name} -> {new_dir.name}")
            else:
                old_dir.rename(new_dir)
                print(f"[renamed] {old_dir} -> {new_dir}")

    if not dry_run:
        save_authors(output_dir, authors)
        print(f"[saved] authors.json updated")


def main() -> int:
    if len(sys.argv) < 2:
        print(
            "Usage: python -m tools.populate_author_names <output_dir> [--dry-run]",
            file=sys.stderr,
        )
        return 1

    output_dir = Path(sys.argv[1])
    dry_run = "--dry-run" in sys.argv

    if not output_dir.is_dir():
        print(f"Output directory does not exist: {output_dir}", file=sys.stderr)
        return 1

    asyncio.run(populate_and_rename(output_dir, dry_run=dry_run))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
