from __future__ import annotations

from pathlib import Path

import tomllib


def test_dev_extra_is_installable_and_has_modern_test_tools() -> None:
    config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dev = config["project"]["optional-dependencies"]["dev"]

    assert not any(dep.startswith("types-python-whois") for dep in dev)
    assert any(dep.startswith("hypothesis") for dep in dev)
    assert any(dep.startswith("pytest-benchmark") for dep in dev)
    assert any(dep.startswith("bandit") for dep in dev)
    assert any(dep.startswith("pip-audit") for dep in dev)


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
