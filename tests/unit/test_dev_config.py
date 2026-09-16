from __future__ import annotations

from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib


def test_dev_extra_is_installable_and_has_modern_test_tools() -> None:
    config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dev = config["project"]["optional-dependencies"]["dev"]

    assert not any(dep.startswith("types-python-whois") for dep in dev)
    assert any(dep.startswith("hypothesis") for dep in dev)
    assert any(dep.startswith("pytest-benchmark") for dep in dev)
    assert any(dep.startswith("bandit") for dep in dev)
    assert any(dep.startswith("pip-audit") for dep in dev)
    assert any(dep.startswith("types-defusedxml") for dep in dev)


def test_network_tests_are_explicitly_marked() -> None:
    config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    markers = config["tool"]["pytest"]["ini_options"]["markers"]
    assert any(marker.startswith("network:") for marker in markers)
    assert any(marker.startswith("benchmark:") for marker in markers)


def test_default_pytest_excludes_live_network_suite() -> None:
    config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    addopts = config["tool"]["pytest"]["ini_options"]["addopts"]
    joined = " ".join(addopts)
    assert "not network" in joined
    assert "not slow" in joined


def test_ci_runs_offline_tests_quality_and_keeps_live_network_separate() -> None:
    workflow = Path(".github/workflows/ci.yml")
    assert workflow.exists()
    text = workflow.read_text(encoding="utf-8")
    assert "pytest" in text
    assert "pre-commit run --all-files" in text
    assert "pip-audit" in text
    assert 'python-version: ["3.10", "3.12", "3.14"]' in text
    assert 'python-version: "3.14"' in text
    assert 'pytest -m "network and slow"' in text
    assert "github.event_name == 'schedule'" in text
