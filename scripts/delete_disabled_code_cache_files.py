#!/usr/bin/env python3
"""
Delete code-cache files whose full content is a disabled-placeholder line.

Default placeholders:
  // LLM secure example disabled by flag.
  // LLM insecure example disabled by flag.

Usage:
  python3 scripts/delete_disabled_code_cache_files.py
  python3 scripts/delete_disabled_code_cache_files.py --dry-run
  python3 scripts/delete_disabled_code_cache_files.py --cache-dir Output/resources/code_cache
"""

from __future__ import annotations

import argparse
from pathlib import Path


DEFAULT_PLACEHOLDERS = {
    "// LLM secure example disabled by flag.",
    "// LLM insecure example disabled by flag.",
}


def normalized_content(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.strip()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Delete placeholder-only files from code cache."
    )
    parser.add_argument(
        "--cache-dir",
        default="Output/resources/code_cache",
        help="Path to code cache directory (default: Output/resources/code_cache).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print files that would be deleted, but do not delete them.",
    )
    parser.add_argument(
        "--also-delete-cache-kept",
        action="store_true",
        help="Also delete files whose content is exactly: // cache-kept example",
    )
    args = parser.parse_args()

    cache_dir = Path(args.cache_dir)
    if not cache_dir.is_dir():
        print(f"[error] Not a directory: {cache_dir}")
        return 1

    placeholders = set(DEFAULT_PLACEHOLDERS)
    if args.also_delete_cache_kept:
        placeholders.add("// cache-kept example")

    to_delete: list[Path] = []
    for path in sorted(cache_dir.rglob("*.txt")):
        if not path.is_file():
            continue
        try:
            content = normalized_content(path)
        except Exception as exc:
            print(f"[warn] Failed to read {path}: {exc}")
            continue

        if content in placeholders:
            to_delete.append(path)

    if not to_delete:
        print("[info] No matching files found.")
        return 0

    for path in to_delete:
        if args.dry_run:
            print(f"[dry-run] {path}")
        else:
            path.unlink()
            print(f"[deleted] {path}")

    action = "Would delete" if args.dry_run else "Deleted"
    print(f"[done] {action} {len(to_delete)} file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
