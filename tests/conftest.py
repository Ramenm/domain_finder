"""Pytest configuration and fixtures."""

from __future__ import annotations

import pytest
from typing import Any
from unittest.mock import Mock


@pytest.fixture
def mock_http_client() -> Mock:
    """Mock HTTP client for testing."""
    return Mock()


@pytest.fixture
def mock_llm_provider() -> Mock:
    """Mock LLM provider for testing."""
    return Mock()


@pytest.fixture
def mock_domain_checker() -> Mock:
    """Mock domain checker for testing."""
    return Mock()

