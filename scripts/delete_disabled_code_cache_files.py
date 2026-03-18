#!/usr/bin/env python3
"""
Delete cached placeholder files for disabled LLM outputs.

Code-cache placeholders:
  // LLM secure example disabled by flag.
  // LLM insecure example disabled by flag.

LLM explanation placeholder (optional cleanup mode):
  LLM explanations disabled by flag.

Usage:
  python3 scripts/delete_disabled_code_cache_files.py
  python3 scripts/delete_disabled_code_cache_files.py --dry-run
  python3 scripts/delete_disabled_code_cache_files.py --report-path /absolute/path/to/output
  python3 scripts/delete_disabled_code_cache_files.py --cache-dir /custom/cache/dir
  python3 scripts/delete_disabled_code_cache_files.py --report-path /absolute/path/to/output --also-delete-disabled-explanations
"""

from __future__ import annotations

import argparse
from pathlib import Path


DEFAULT_CODE_PLACEHOLDERS = {
    "// LLM secure example disabled by flag.",
    "// LLM insecure example disabled by flag.",
}
DEFAULT_EXPLANATION_PLACEHOLDER = "LLM explanations disabled by flag."


def normalized_content(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.strip()


def resolve_code_cache_dir(report_path: str, cache_dir_override: str | None) -> Path:
    if cache_dir_override:
        return Path(cache_dir_override)
    return Path(report_path) / "resources" / "code_cache"


def resolve_llm_cache_dir(report_path: str, llm_cache_dir_override: str | None) -> Path:
    if llm_cache_dir_override:
        return Path(llm_cache_dir_override)
    return Path(report_path) / "resources" / "llm_cache"


def collect_matching_files(cache_dir: Path, placeholders: set[str]) -> list[Path]:
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
    return to_delete


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Delete placeholder-only files from LLM caches."
    )
    parser.add_argument(
        "--report-path",
        default="Output",
        help="Documentation output root used to derive default cache dir: <reportPath>/resources/code_cache.",
    )
    parser.add_argument(
        "--cache-dir",
        default=None,
        help="Optional explicit code cache directory. Overrides --report-path derived location.",
    )
    parser.add_argument(
        "--llm-cache-dir",
        default=None,
        help="Optional explicit explanation cache directory. Overrides --report-path derived location.",
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
    parser.add_argument(
        "--also-delete-disabled-explanations",
        action="store_true",
        help="Also delete explanation-cache files whose content is exactly: LLM explanations disabled by flag.",
    )
    args = parser.parse_args()

    code_cache_dir = resolve_code_cache_dir(args.report_path, args.cache_dir)
    scan_targets: list[tuple[Path, set[str]]] = []

    if not code_cache_dir.is_dir():
        if args.also_delete_disabled_explanations:
            print(f"[warn] Not a directory (skipping code cache): {code_cache_dir}")
        else:
            print(f"[error] Not a directory: {code_cache_dir}")
            return 1
    else:
        code_placeholders = set(DEFAULT_CODE_PLACEHOLDERS)
        if args.also_delete_cache_kept:
            code_placeholders.add("// cache-kept example")
        scan_targets.append((code_cache_dir, code_placeholders))

    if args.also_delete_disabled_explanations:
        llm_cache_dir = resolve_llm_cache_dir(args.report_path, args.llm_cache_dir)
        if not llm_cache_dir.is_dir():
            print(f"[warn] Not a directory (skipping llm cache): {llm_cache_dir}")
        else:
            scan_targets.append((llm_cache_dir, {DEFAULT_EXPLANATION_PLACEHOLDER}))

    if not scan_targets:
        print("[error] No valid cache directory to scan.")
        return 1

    to_delete: list[Path] = []
    for cache_dir, placeholders in scan_targets:
        to_delete.extend(collect_matching_files(cache_dir, placeholders))

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
