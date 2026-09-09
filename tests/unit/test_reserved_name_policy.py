from __future__ import annotations

import httpx
import pytest
from defusedxml.common import DefusedXmlException

from domain_finder.infrastructure.whois.reserved_policy import ReservedNamePolicy


def test_com_contract_reserved_labels_are_detected_without_network(tmp_path) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise AssertionError("contract labels should not require XML fetch")

    http = httpx.Client(transport=httpx.MockTransport(handler))
    policy = ReservedNamePolicy(cache_path=tmp_path / "reserved.xml", http_client=http)

    assert policy.match("gnso.com") is not None
    assert policy.match("iesg.com") is not None
    assert calls == 0


def test_global_icann_reserved_xml_detects_imso_for_com(tmp_path) -> None:
    xml = b"""<?xml version='1.0'?><reserved><record><name>imso</name><label1>imso</label1><label2></label2></record></reserved>"""
    http = httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, content=xml))
    )
    policy = ReservedNamePolicy(cache_path=tmp_path / "reserved.xml", http_client=http)

    match = policy.match("imso.com")
    assert match is not None
    assert match.source == "icann-global-reserved-names"


def test_unrelated_unregistered_com_is_not_marked_reserved(tmp_path) -> None:
    xml = b"<?xml version='1.0'?><reserved></reserved>"
    http = httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, content=xml))
    )
    policy = ReservedNamePolicy(cache_path=tmp_path / "reserved.xml", http_client=http)
    assert policy.match("randombrand.com") is None


def test_real_icann_xml_namespace_is_supported(tmp_path) -> None:
    xml = b"""<?xml version='1.0'?>
    <registry xmlns='http://www.iana.org/assignments'>
      <record><name>imso</name><label1>imso</label1><label2></label2></record>
    </registry>"""
    http = httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, content=xml))
    )
    policy = ReservedNamePolicy(cache_path=tmp_path / "reserved.xml", http_client=http)
    match = policy.match("imso.com")
    assert match is not None
    assert match.source == "icann-global-reserved-names"


def test_reserved_xml_entities_are_rejected() -> None:
    payload = b"""<?xml version='1.0'?>
    <!DOCTYPE reserved [<!ENTITY candidate 'imso'>]>
    <reserved><record><label1>&candidate;</label1></record></reserved>"""

    with pytest.raises(DefusedXmlException):
        ReservedNamePolicy._parse_labels(payload)
