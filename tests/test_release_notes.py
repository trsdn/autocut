"""Release-notes extraction for the release workflow.

The workflow feeds this script's output to `gh release create --notes-file`, and
gates the PyPI publish on it succeeding. A silent failure here would either
publish empty release notes or block a legitimate release, so the failure paths
matter as much as the happy path.

The script lives in `.github/scripts/` rather than `src/`, so that release
tooling never ships in the wheel. It is loaded by path.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / ".github" / "scripts" / "release_notes.py"


def load_script():
    spec = importlib.util.spec_from_file_location("release_notes", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


release_notes = load_script()
extract = release_notes.extract
ReleaseNotesError = release_notes.ReleaseNotesError


CHANGELOG = """\
# Changelog

Some preamble that belongs to no release.

## [Unreleased]

### Added
- Something not yet shipped.

## [0.2.3] - 2026-08-24

### Added
- PyPI version badge in the README.

### Fixed
- A thing that was broken.

## [0.2.2] - 2026-08-24

### Fixed
- An earlier thing.

## [0.1.0] - 2026-04-23

### Added
- Initial release.

[Unreleased]: https://github.com/trsdn/autocut/compare/v0.2.3...HEAD
[0.2.3]: https://github.com/trsdn/autocut/releases/tag/v0.2.3
[0.1.0]: https://github.com/trsdn/autocut/releases/tag/v0.1.0
"""


# --------------------------------------------------------------------------
# Happy path
# --------------------------------------------------------------------------
def test_the_section_body_is_returned_without_its_heading():
    notes = extract(CHANGELOG, "0.2.3")

    assert notes.startswith("### Added")
    assert "PyPI version badge in the README." in notes
    assert "0.2.3" not in notes.splitlines()[0]


def test_every_subsection_of_the_release_is_included():
    notes = extract(CHANGELOG, "0.2.3")

    assert "### Added" in notes
    assert "### Fixed" in notes
    assert "A thing that was broken." in notes


def test_the_next_version_heading_ends_the_section():
    notes = extract(CHANGELOG, "0.2.3")

    assert "An earlier thing." not in notes
    assert "0.2.2" not in notes


def test_the_unreleased_section_does_not_bleed_into_the_release_below_it():
    notes = extract(CHANGELOG, "0.2.3")

    assert "Something not yet shipped." not in notes


def test_the_unreleased_heading_ends_the_section_above_it():
    """`## [Unreleased]` is not a version, but it still terminates a section."""
    changelog = "## [Unreleased]\n\n- pending\n\n## [1.0.0]\n\n- shipped\n"

    assert extract(changelog, "1.0.0") == "- shipped"


@pytest.mark.parametrize(
    "tag", ["0.2.3", "v0.2.3", "V0.2.3", " v0.2.3 ", "refs/tags/v0.2.3".rsplit("/", 1)[-1]]
)
def test_a_tag_or_a_bare_version_are_both_accepted(tag):
    assert "PyPI version badge" in extract(CHANGELOG, tag)


@pytest.mark.parametrize(
    "heading",
    [
        "## [1.2.3] - 2026-01-01",
        "## [1.2.3]",
        "## 1.2.3",
        "## v1.2.3",
        "## [1.2.3](https://example.com/releases/1.2.3)",
        "##   [1.2.3]",
    ],
)
def test_the_common_changelog_heading_styles_are_recognised(heading):
    assert extract(f"{heading}\n\n- a change\n", "1.2.3") == "- a change"


def test_a_prerelease_version_is_recognised():
    assert extract("## [1.0.0-rc.1]\n\n- candidate\n", "1.0.0-rc.1") == "- candidate"


def test_a_version_that_is_a_prefix_of_another_is_not_confused():
    """`0.2.1` must not match the `0.2.10` heading that appears first."""
    changelog = "## [0.2.10]\n\n- ten\n\n## [0.2.1]\n\n- one\n"

    assert extract(changelog, "0.2.1") == "- one"


# --------------------------------------------------------------------------
# Link definitions
# --------------------------------------------------------------------------
def test_trailing_link_definitions_are_not_part_of_the_notes():
    """The final section would otherwise swallow the whole link block."""
    notes = extract(CHANGELOG, "0.1.0")

    assert notes == "### Added\n- Initial release."
    assert "https://github.com" not in notes


def test_a_section_containing_only_link_definitions_counts_as_empty():
    changelog = "## [1.0.0]\n\n[1.0.0]: https://example.com/1.0.0\n"

    with pytest.raises(ReleaseNotesError, match="empty"):
        extract(changelog, "1.0.0")


def test_inline_links_inside_the_notes_are_preserved():
    """Only whole-line reference definitions are stripped, not real content."""
    changelog = "## [1.0.0]\n\n- see [the docs](https://example.com) for details\n"

    assert "[the docs](https://example.com)" in extract(changelog, "1.0.0")


# --------------------------------------------------------------------------
# Failure paths
# --------------------------------------------------------------------------
def test_a_missing_version_raises_with_an_actionable_message():
    with pytest.raises(ReleaseNotesError) as excinfo:
        extract(CHANGELOG, "9.9.9")

    message = str(excinfo.value)
    assert "no CHANGELOG section for version 9.9.9" in message
    assert '"## [9.9.9]"' in message


def test_an_empty_section_raises_rather_than_publishing_blank_notes():
    changelog = "## [1.0.0] - 2026-01-01\n\n## [0.9.0]\n\n- older\n"

    with pytest.raises(ReleaseNotesError, match="empty"):
        extract(changelog, "1.0.0")


def test_a_whitespace_only_section_raises():
    changelog = "## [1.0.0]\n\n   \n\t\n\n## [0.9.0]\n\n- older\n"

    with pytest.raises(ReleaseNotesError, match="empty"):
        extract(changelog, "1.0.0")


def test_a_section_at_the_end_of_the_file_with_no_body_raises():
    with pytest.raises(ReleaseNotesError, match="empty"):
        extract("## [1.0.0]\n", "1.0.0")


@pytest.mark.parametrize("version", ["", "   ", "v"])
def test_an_empty_version_argument_raises(version):
    with pytest.raises(ReleaseNotesError, match="version argument is required"):
        extract(CHANGELOG, version)


# --------------------------------------------------------------------------
# Command line behaviour, which is what the workflow actually invokes
# --------------------------------------------------------------------------
def run_cli(*args, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
    )


@pytest.fixture
def changelog_file(tmp_path) -> Path:
    path = tmp_path / "CHANGELOG.md"
    path.write_text(CHANGELOG, encoding="utf-8")
    return path


def test_the_cli_prints_the_notes_and_exits_zero(changelog_file):
    result = run_cli("v0.2.3", "--changelog", str(changelog_file))

    assert result.returncode == 0
    assert "PyPI version badge in the README." in result.stdout


def test_the_cli_exits_non_zero_for_a_missing_version(changelog_file):
    result = run_cli("9.9.9", "--changelog", str(changelog_file))

    assert result.returncode == 1
    assert result.stdout.strip() == ""
    assert "no CHANGELOG section" in result.stderr


def test_the_cli_exits_non_zero_for_an_empty_section(tmp_path):
    path = tmp_path / "CHANGELOG.md"
    path.write_text("## [1.0.0]\n\n## [0.9.0]\n\n- older\n", encoding="utf-8")

    result = run_cli("1.0.0", "--changelog", str(path))

    assert result.returncode == 1
    assert "empty" in result.stderr


def test_the_cli_reports_a_missing_changelog_file(tmp_path):
    result = run_cli("1.0.0", "--changelog", str(tmp_path / "nope.md"))

    assert result.returncode == 1
    assert "cannot read" in result.stderr


def test_the_cli_defaults_to_the_changelog_in_the_working_directory(tmp_path):
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")

    result = run_cli("0.2.3", cwd=tmp_path)

    assert result.returncode == 0
    assert "PyPI version badge" in result.stdout


def test_errors_follow_the_repository_convention_of_an_error_prefix(changelog_file):
    result = run_cli("9.9.9", "--changelog", str(changelog_file))

    assert result.stderr.startswith("error: ")


# --------------------------------------------------------------------------
# Against the real CHANGELOG, which is what a release will actually read
# --------------------------------------------------------------------------
def real_changelog_versions(changelog: str) -> list[str]:
    """Every version heading in document order (the regex is applied per line)."""
    found = []
    for line in changelog.splitlines():
        match = release_notes.VERSION_HEADING.match(line)
        if match:
            found.append(match.group("version"))
    return found


def test_every_released_version_in_the_real_changelog_yields_notes():
    """Guards the whole published history, not just the newest entry."""
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    versions = real_changelog_versions(changelog)
    assert versions, "no version headings found in CHANGELOG.md"

    for version in versions:
        notes = extract(changelog, version)
        assert notes.strip(), f"version {version} produced empty notes"


def test_every_published_git_tag_has_notes_in_the_real_changelog():
    """A tag without notes would fail the release; catch it at test time."""
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    versions = set(real_changelog_versions(changelog))

    tags = subprocess.run(
        ["git", "tag", "--list", "v*"],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    if tags.returncode != 0 or not tags.stdout.strip():
        pytest.skip("no git tags available")

    missing = [
        tag for tag in tags.stdout.split()
        if release_notes.normalise(tag) not in versions
    ]
    assert missing == [], f"tagged versions with no CHANGELOG section: {missing}"


def test_the_version_being_released_next_already_has_usable_notes():
    """Pairs with test_packaging's changelog check: same rule, release time."""
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10
        import tomli as tomllib  # type: ignore[no-redef]

    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = pyproject["project"]["version"]

    assert extract((REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), version).strip()
