#!/usr/bin/env python3
"""Extract one version's notes from CHANGELOG.md for the release workflow.

    python .github/scripts/release_notes.py v0.2.3 [--changelog CHANGELOG.md]

Exits non-zero when the version has no section, or when that section is empty,
so a release fails loudly rather than publishing blank or invented notes.

Stdlib only, matching the rest of this repository — see AGENTS.md. This is
release tooling and is deliberately outside `src/`, so it never ships in the
wheel or the sdist.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Heading styles Keep a Changelog allows, and the one this file uses:
#   "## [0.2.3] - 2026-08-24", "## [0.2.3]", "## 0.2.3", "## v0.2.3",
#   "## [0.2.3](https://github.com/...)"
VERSION_HEADING = re.compile(
    r"^##\s+\[?v?(?P<version>\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)\]?"
)
# Any level-2 heading ends a section, so "## [Unreleased]" terminates it too.
ANY_HEADING = re.compile(r"^##\s")
# Reference-style link definitions collected at the foot of the file:
#   "[0.2.3]: https://github.com/trsdn/autocut/releases/tag/v0.2.3"
# They belong to the document, not to the release, and the final section would
# otherwise swallow the whole block.
LINK_DEFINITION = re.compile(r"^\[[^\]]+\]:\s*\S+\s*$")


class ReleaseNotesError(Exception):
    """A version cannot be turned into release notes."""


def normalise(version: str) -> str:
    """Accept a tag (`v0.2.3`) or a bare version (`0.2.3`)."""
    wanted = version.strip()
    if wanted[:1] in ("v", "V"):
        wanted = wanted[1:]
    return wanted


def extract(changelog: str, version: str) -> str:
    """Return the notes for `version`, or raise ReleaseNotesError."""
    wanted = normalise(version)
    if not wanted:
        raise ReleaseNotesError(
            "a version argument is required, e.g. `release_notes.py v0.2.3`"
        )

    lines = changelog.splitlines()
    start = None
    for i, line in enumerate(lines):
        match = VERSION_HEADING.match(line)
        if match and match.group("version") == wanted:
            start = i
            break

    if start is None:
        raise ReleaseNotesError(
            f"no CHANGELOG section for version {wanted}. "
            f'Add a "## [{wanted}]" heading before tagging the release.'
        )

    body: list[str] = []
    for line in lines[start + 1:]:
        if ANY_HEADING.match(line):
            break
        if LINK_DEFINITION.match(line):
            continue
        body.append(line)

    notes = "\n".join(body).strip()
    if not notes:
        raise ReleaseNotesError(
            f"the CHANGELOG section for version {wanted} is empty. "
            "Write the release notes before tagging."
        )
    return notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract one version's notes from CHANGELOG.md."
    )
    parser.add_argument("version", help="Version or tag to extract, e.g. 0.2.3 or v0.2.3")
    parser.add_argument("--changelog", type=Path, default=Path("CHANGELOG.md"))
    args = parser.parse_args(argv)

    try:
        changelog = args.changelog.read_text(encoding="utf-8")
    except OSError as e:
        print(f"error: cannot read {args.changelog}: {e}", file=sys.stderr)
        return 1

    try:
        print(extract(changelog, args.version))
    except ReleaseNotesError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
