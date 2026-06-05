"""Fail CI when the git tag does not match app.__version__ (e.g. v1.2.3)."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path


def main() -> int:
    tag = os.environ.get("GITHUB_REF_NAME", "").strip()
    if not tag:
        ref = os.environ.get("GITHUB_REF", "").strip()
        if ref.startswith("refs/tags/"):
            tag = ref.removeprefix("refs/tags/")

    version_line = Path("app/__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', version_line, re.MULTILINE)
    if not match:
        print("Could not read __version__ from app/__init__.py", file=sys.stderr)
        return 1

    version = match.group(1)
    expected = f"v{version}"
    print(f"Tag: {tag or '(none)'}  App: {version}  Expected tag: {expected}")
    if tag != expected:
        print(
            f"Tag '{tag}' does not match __version__ '{version}'. Use tag '{expected}'.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
