#!/usr/bin/env python3
"""
Build a Homebrew-ready tarball for Moovent Stack.

This ships ONLY the launcher code + docs (no secrets).
Homebrew formula should point at the GitHub release asset built by this script.
"""

from __future__ import annotations

import argparse
import hashlib
import tarfile
from pathlib import Path


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _version(repo_root: Path) -> str:
    return (repo_root / "VERSION").read_text(encoding="utf-8").strip()


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    version = _version(repo_root)
    name = f"moovent-stack-{version}"

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path, default=repo_root / "dist" / f"{name}.tar.gz"
    )
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)

    include = [
        "VERSION",
        "README.md",
        "pyproject.toml",
        "moovent_stack",
        "tests",
    ]

    with tarfile.open(args.output, "w:gz") as tar:
        for rel in include:
            tar.add(repo_root / rel, arcname=f"{name}/{rel}")

    print(f"[release] Wrote: {args.output}")
    print(f"[release] sha256: {_sha256(args.output)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
