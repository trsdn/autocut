"""Guards for the packaging invariants this project depends on.

These encode rules that are easy to break silently: the deliberate stdlib-only
runtime, and keeping `pyproject.toml`, the installed metadata and `CHANGELOG.md`
telling the same story about what version this is.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src" / "autocut"


@pytest.fixture(scope="module")
def pyproject() -> dict:
    return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def changelog() -> str:
    return (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# The stdlib-only rule
# --------------------------------------------------------------------------
def test_the_runtime_has_no_third_party_dependencies(pyproject):
    """Deliberate design constraint: `pip install trsdn-autocut` pulls nothing."""
    assert pyproject["project"]["dependencies"] == []


def module_level_imports(tree: ast.Module) -> list[str]:
    """Top-level import roots only; imports inside functions are lazy by design."""
    roots: list[str] = []
    pending: list[ast.stmt] = list(tree.body)
    while pending:
        node = pending.pop()
        if isinstance(node, ast.Import):
            roots += [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                roots.append(node.module.split(".")[0])
        elif isinstance(node, (ast.Try, ast.If)):
            pending += node.body + node.orelse + getattr(node, "finalbody", [])
            for handler in getattr(node, "handlers", []):
                pending += handler.body
    return roots


@pytest.mark.parametrize("path", sorted(SRC.glob("*.py")), ids=lambda p: p.name)
def test_modules_import_only_the_standard_library_at_import_time(path):
    """Heavy optional backends must stay behind function-local imports."""
    tree = ast.parse(path.read_text(encoding="utf-8"))

    third_party = [
        name
        for name in module_level_imports(tree)
        if name not in sys.stdlib_module_names and name != "autocut"
    ]

    assert third_party == [], f"{path.name} imports {third_party} at module level"


def test_the_optional_nemo_backend_is_the_only_place_heavy_deps_appear(pyproject):
    extras = pyproject["project"]["optional-dependencies"]
    assert "nemo" in extras
    assert any("nemo_toolkit" in spec for spec in extras["nemo"])


def test_importing_autocut_does_not_require_any_extra(pyproject):
    import autocut  # noqa: F401  - the import itself is the assertion

    assert autocut.__version__


# --------------------------------------------------------------------------
# Version consistency
# --------------------------------------------------------------------------
def test_the_installed_version_matches_pyproject(pyproject):
    """Catches the drift class where a release ships a stale __version__."""
    import autocut

    if autocut.__version__ == "0.0.0+unknown":
        pytest.skip("package is not installed; run `pip install -e .` first")

    assert autocut.__version__ == pyproject["project"]["version"]


def test_the_current_version_has_a_changelog_entry(pyproject, changelog):
    """Tagging a version whose changes were never written up is a release bug."""
    version = pyproject["project"]["version"]

    assert re.search(rf"^##\s+\[{re.escape(version)}\]", changelog, re.MULTILINE), (
        f"CHANGELOG.md has no '## [{version}]' section"
    )


def test_the_changelog_starts_with_an_unreleased_section(changelog):
    headings = re.findall(r"^##\s+\[([^\]]+)\]", changelog, re.MULTILINE)

    assert headings[0] == "Unreleased"


def test_the_declared_python_floor_matches_the_lowest_classifier(pyproject):
    project = pyproject["project"]
    versions = sorted(
        tuple(int(part) for part in line.rsplit(" ", 1)[-1].split("."))
        for line in project["classifiers"]
        if line.startswith("Programming Language :: Python :: 3.")
    )

    floor = tuple(int(p) for p in project["requires-python"].lstrip(">=").split("."))
    assert versions[0] == floor


# --------------------------------------------------------------------------
# CI covers what the project claims to support
# --------------------------------------------------------------------------
def test_ci_tests_every_python_version_the_package_advertises(pyproject):
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    matrix = re.search(r"python-version:\s*\[([^\]]+)\]", workflow)
    assert matrix, "ci.yml does not declare a python-version matrix"

    tested = {v.strip().strip("\"'") for v in matrix.group(1).split(",")}
    advertised = {
        line.rsplit(" ", 1)[-1]
        for line in pyproject["project"]["classifiers"]
        if line.startswith("Programming Language :: Python :: 3.")
    }

    assert tested == advertised


def test_the_console_script_points_at_a_real_entry_point(pyproject):
    target = pyproject["project"]["scripts"]["autocut"]
    module_path, _, func = target.partition(":")

    module = __import__(module_path, fromlist=[func])
    assert callable(getattr(module, func))
