"""The version in pyproject.toml, the installed package and CHANGELOG.md agree."""

import importlib.util
import tomllib
from pathlib import Path

import ifdispatcher

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release_notes", ROOT / "scripts/release_notes.py")
release_notes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_notes)


def test_package_reports_the_project_version():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert ifdispatcher.__version__ == project["version"]


def test_every_release_has_changelog_notes_and_a_compare_link():
    text = (ROOT / "CHANGELOG.md").read_text()
    version = ifdispatcher.__version__
    assert release_notes.notes(version, text), f"CHANGELOG.md needs a [{version}] section"
    assert f"\n[{version}]: https://github.com/IntelIP/InfiniteFlightAgent/" in text
    assert release_notes.notes("0.0.0", text) is None
