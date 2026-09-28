"""Tests for StructuredExtractionClient protocol and FakeStructuredExtractionClient."""

import pytest

from agentcontract.extraction.client import (
    ExtractionRequest,
    FakeStructuredExtractionClient,
    StructuredExtractionClient,
)
from agentcontract.extraction.exceptions import ClientExtractionError


def test_structured_extraction_client_protocol_conformance() -> None:
    fake = FakeStructuredExtractionClient({"constraints": []})
    assert isinstance(fake, StructuredExtractionClient)


def test_fake_client_records_requests_and_call_count() -> None:
    fake = FakeStructuredExtractionClient(
        [
            {"step": 1},
            {"step": 2},
        ]
    )
    assert fake.call_count == 0
    assert len(fake.requests) == 0
    assert fake.last_request is None

    # First call
    resp1 = fake.extract(
        task="extract_requirements",
        text="Do not edit auth.py",
        schema={"type": "object"},
        context={"user_id": "alice"},
    )
    assert resp1 == {"step": 1}
    assert fake.call_count == 1
    assert len(fake.requests) == 1
    assert fake.last_request is not None
    assert fake.last_request.task == "extract_requirements"
    assert fake.last_request.text == "Do not edit auth.py"
    assert fake.last_request.context["user_id"] == "alice"

    # Second call
    resp2 = fake.extract(
        task="extract_claims",
        text="Finished auth logic",
        schema={"type": "object"},
    )
    assert resp2 == {"step": 2}
    assert fake.call_count == 2
    assert len(fake.requests) == 2
    assert fake.last_request.task == "extract_claims"


def test_fake_client_repeats_single_response() -> None:
    fake = FakeStructuredExtractionClient({"status": "ok"})
    for i in range(5):
        resp = fake.extract(task="test", text=f"text {i}", schema={})
        assert resp == {"status": "ok"}
    assert fake.call_count == 5


def test_fake_client_custom_handler() -> None:
    def handler(req: ExtractionRequest) -> dict[str, str]:
        return {"echo": req.text.upper()}

    fake = FakeStructuredExtractionClient(handler)
    resp = fake.extract(task="echo", text="hello", schema={})
    assert resp == {"echo": "HELLO"}
    assert fake.call_count == 1


def test_fake_client_error_conditions() -> None:
    # Handler returns non-mapping
    fake = FakeStructuredExtractionClient(lambda req: "not_a_map")  # type: ignore[return-value]
    with pytest.raises(ClientExtractionError, match="expected a Mapping"):
        fake.extract(task="test", text="foo", schema={})

    # Empty queue error
    empty_fake = FakeStructuredExtractionClient([{"a": 1}])
    empty_fake.extract(task="t", text="1", schema={})
    # Cannot pop empty if multiple were provided
    empty_fake._responses = []
    with pytest.raises(ClientExtractionError, match="No canned responses left"):
        empty_fake.extract(task="t", text="2", schema={})

    # Invalid responses init type
    with pytest.raises(ClientExtractionError, match="Invalid responses parameter type"):
        FakeStructuredExtractionClient(12345)  # type: ignore[arg-type]
