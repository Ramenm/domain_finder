from __future__ import annotations

from domain_finder.domain.models import DomainSearchParams
from domain_finder.domain.services import DomainGeneratorService


class StaticProvider:
    def __init__(self, text: str) -> None:
        self.text = text

    def generate_domains(self, params: DomainSearchParams) -> str:
        return self.text


def parse(text: str, tlds: list[str], limit: int = 20) -> list[str]:
    service = DomainGeneratorService(StaticProvider(text))
    return [
        item.name
        for item in service._parse_domains_from_text(
            text, allowed_tlds=tlds, min_len=4, max_len=15, limit=limit
        )
    ]


def test_bare_label_expands_tlds_in_user_order() -> None:
    assert parse("brandname", ["com", "io", "ai"]) == [
        "brandname.com",
        "brandname.io",
        "brandname.ai",
    ]


def test_json_array_response_is_parsed() -> None:
    assert parse('["alpha.com", "beta.io", "gamma.ai"]', ["com", "io", "ai"]) == [
        "alpha.com",
        "beta.io",
        "gamma.ai",
    ]


def test_json_object_domains_response_is_parsed() -> None:
    assert parse('{"domains": ["alpha.com", "beta.com"]}', ["com"]) == [
        "alpha.com",
        "beta.com",
    ]


def test_duplicate_tokens_and_tlds_are_deduplicated_stably() -> None:
    assert parse("alpha, alpha, alpha.com", ["com", "io"]) == [
        "alpha.com",
        "alpha.io",
    ]


def test_explicit_disallowed_tld_is_rejected() -> None:
    assert parse("alpha.net, beta.com", ["com", "io"]) == ["beta.com"]


def test_generation_strategy_is_part_of_search_params() -> None:
    params = DomainSearchParams(
        topic="analytics",
        tlds=["com"],
        count=10,
        min_len=4,
        max_len=15,
        strategy="brandable",
    )
    assert params.strategy == "brandable"


def test_quality_scorer_prefers_clean_memorable_label() -> None:
    from domain_finder.domain.models import DomainCandidate
    from domain_finder.domain.scoring import DomainQualityScorer

    scorer = DomainQualityScorer()
    clean = DomainCandidate.from_string("metricly.com")
    noisy = DomainCandidate.from_string("m3tric---x.com")
    assert scorer.score(clean, "analytics metrics") > scorer.score(noisy, "analytics metrics")


def test_multilabel_registration_suffix_is_supported() -> None:
    assert parse("brand", ["co.uk", "com.au"]) == ["brand.co.uk", "brand.com.au"]


def test_explicit_multilabel_suffix_is_validated_exactly() -> None:
    assert parse("brand.co.uk, brand.com", ["co.uk"]) == ["brand.co.uk"]


def test_candidate_preserves_multilabel_suffix() -> None:
    from domain_finder.domain.models import DomainCandidate

    candidate = DomainCandidate.from_string("brand.co.uk", suffix="co.uk")
    assert candidate.label == "brand"
    assert candidate.tld == "co.uk"


def test_unicode_suffix_is_normalized_to_punycode() -> None:
    assert parse("brand", ["рф"]) == ["brand.xn--p1ai"]


def test_unicode_domain_from_llm_is_normalized_to_punycode() -> None:
    assert parse("пример.рф", ["рф"]) == ["xn--e1afmkfd.xn--p1ai"]


def test_punycode_domain_matches_unicode_configured_suffix() -> None:
    assert parse("brand.xn--p1ai", ["рф"]) == ["brand.xn--p1ai"]
