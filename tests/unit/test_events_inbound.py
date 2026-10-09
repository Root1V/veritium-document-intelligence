"""Commands as CloudEvents (VRT-49): both bindings' modes, the claim-check
allow-list, and what a command must say."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from idp.events.claim_check import allowed
from idp.events.inbound import AddDocumentsData, SubmitData, binary, structured


def test_structured_and_binary_modes_give_the_same_event():
    a = structured(b'{"specversion":"1.0","id":"1","source":"core","type":"pe.veritium.case.submit","data":{"x":1}}')
    b = binary({"specversion": "1.0", "id": "1", "source": "core", "type": "pe.veritium.case.submit"}, b'{"x":1}')
    assert a == b


@pytest.mark.parametrize(
    "body",
    [b"no json", b"[1]", b'{"specversion":"1.0","id":"1","type":"t"}', b'{"specversion":"0.3","id":"1","source":"s","type":"t"}'],
)
def test_what_is_not_a_cloudevent_1_0_is_refused(body):
    with pytest.raises(ValueError):
        structured(body)


def test_claim_check_reads_only_allowed_origins():
    prefixes = ["s3://inbox/core/", "https://files.bank.pe/veritium/"]
    assert allowed("s3://inbox/core/2026/boleta.pdf", prefixes)
    assert allowed("https://files.bank.pe/veritium/a.pdf?sig=x", prefixes)
    assert not allowed("s3://inbox/otro/a.pdf", prefixes)
    assert not allowed("s3://inbox/core/../secretos/a.pdf", prefixes)
    assert not allowed("file:///etc/passwd", prefixes + ["file:///"])
    assert not allowed("http://169.254.169.254/latest/meta-data", prefixes)


def test_a_command_must_bring_documents_and_name_its_case():
    with pytest.raises(ValidationError):
        SubmitData.model_validate({"profile": "convenios", "documents": []})
    with pytest.raises(ValidationError, match="case_id o external_ref"):
        AddDocumentsData.model_validate({"documents": [{"url": "s3://inbox/a.pdf"}]})
