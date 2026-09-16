from __future__ import annotations

import pytest
from pydantic import ValidationError

from domain_finder.application.dto import DomainSearchRequest


@pytest.mark.parametrize(
    "overrides",
    [
        {"tlds": ["."]},
        {"iterations": 0},
        {"per_request": 0},
        {"llm_workers": 0},
        {"max_workers": 0},
        {"temperature": 2.1},
        {"timeout": 0.0},
        {"min_len": 12, "max_len": 4},
    ],
)
def test_request_rejects_invalid_user_values(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        DomainSearchRequest(topic="developer tools", **overrides)


def test_request_normalizes_tlds() -> None:
    request = DomainSearchRequest(topic="developer tools", tlds=[".COM", " io "])
    assert request.tlds == ["com", "io"]


def test_request_rejects_invalid_tld_syntax() -> None:
    from pydantic import ValidationError

    invalid_tlds = [["co m"], ["-com"], ["com-"], ["com/evil"], [".."]]
    for tlds in invalid_tlds:
        with pytest.raises(ValidationError):
            DomainSearchRequest(topic="developer tools", tlds=tlds)


def test_request_normalizes_idna_and_compound_tlds() -> None:
    request = DomainSearchRequest(topic="developer tools", tlds=[".РФ", "co.uk"])
    assert request.tlds == ["xn--p1ai", "co.uk"]
