from __future__ import annotations

import string

from hypothesis import given
from hypothesis import strategies as st

from domain_finder.domain.models import DomainSearchParams
from domain_finder.domain.services import DomainGeneratorService


class EchoProvider:
    def generate_domains(self, params: DomainSearchParams) -> str:
        return ""


service = DomainGeneratorService(EchoProvider())
valid_labels = st.text(alphabet=string.ascii_lowercase + string.digits, min_size=4, max_size=15)


@given(valid_labels)
def test_bare_ascii_label_expands_deterministically(label: str) -> None:
    values = service._parse_domains_from_text(
        label,
        allowed_tlds=["com", "io", "ai"],
        min_len=4,
        max_len=15,
        limit=10,
    )
    assert [item.name for item in values] == [f"{label}.com", f"{label}.io", f"{label}.ai"]
