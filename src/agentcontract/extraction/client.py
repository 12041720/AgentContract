"""Provider-neutral structured extraction client protocol and test fakes."""

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol, runtime_checkable
from pydantic import BaseModel, ConfigDict, Field

from agentcontract.common.immutable import FrozenDict
from agentcontract.extraction.exceptions import ClientExtractionError


class ExtractionRequest(BaseModel):
    """Encapsulates the input parameters sent to a structured extraction client."""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    task: str = Field(
        ...,
        description="Extraction task identifier (e.g. 'extract_requirements', 'extract_claims').",
    )
    text: str = Field(
        ...,
        description="Input natural language text to be analyzed.",
    )
    schema_definition: Mapping[str, Any] = Field(
        ...,
        description="Target JSON schema or structural specification.",
        alias="schema",
    )
    context: FrozenDict = Field(
        default_factory=FrozenDict,
        description="Optional contextual metadata.",
    )


@runtime_checkable
class StructuredExtractionClient(Protocol):
    """Vendor-neutral protocol for structured extraction clients."""

    def extract(
        self,
        *,
        task: str,
        text: str,
        schema: Mapping[str, Any],
        context: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        """Perform structured extraction against the provided text.

        Args:
            task: Specific extraction task name.
            text: Input natural language text to analyze.
            schema: Expected JSON Schema for the structured output.
            context: Optional caller context.

        Returns:
            Raw untrusted structured mapping returned by the underlying provider.

        Raises:
            ClientExtractionError: If extraction fails or client returns invalid output.
        """
        ...


class FakeStructuredExtractionClient:
    """Deterministic in-memory structured extraction client for tests and offline usage."""

    def __init__(
        self,
        responses: Mapping[str, Any] | Sequence[Mapping[str, Any]] | Callable[[ExtractionRequest], Mapping[str, Any]] | None = None,
    ) -> None:
        self._requests: list[ExtractionRequest] = []
        self._call_count: int = 0
        if responses is None:
            self._responses: list[Mapping[str, Any]] = [{}]
            self._handler: Callable[[ExtractionRequest], Mapping[str, Any]] | None = None
        elif callable(responses):
            self._responses = []
            self._handler = responses
        elif isinstance(responses, Mapping):
            self._responses = [dict(responses)]
            self._handler = None
        elif isinstance(responses, Sequence):
            self._responses = [dict(r) for r in responses]
            self._handler = None
        else:
            raise ClientExtractionError(f"Invalid responses parameter type: {type(responses).__name__}")

    @property
    def call_count(self) -> int:
        """Total number of times extract() was invoked."""
        return self._call_count

    @property
    def requests(self) -> tuple[ExtractionRequest, ...]:
        """Chronological history of extraction requests received."""
        return tuple(self._requests)

    @property
    def last_request(self) -> ExtractionRequest | None:
        """Most recently received extraction request."""
        return self._requests[-1] if self._requests else None

    def extract(
        self,
        *,
        task: str,
        text: str,
        schema: Mapping[str, Any],
        context: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        """Execute a simulated extraction request deterministically."""
        req = ExtractionRequest(
            task=task,
            text=text,
            schema=schema,
            context=FrozenDict(context or {}),
        )
        self._requests.append(req)
        self._call_count += 1

        if self._handler is not None:
            resp = self._handler(req)
            if not isinstance(resp, Mapping):
                raise ClientExtractionError(
                    f"Fake handler returned {type(resp).__name__}, expected a Mapping."
                )
            return resp

        if not self._responses:
            raise ClientExtractionError("No canned responses left in FakeStructuredExtractionClient queue.")

        # If multiple responses queued, pop FIFO; if only one response, keep returning it
        if len(self._responses) > 1:
            resp = self._responses.pop(0)
        else:
            resp = self._responses[0]

        if not isinstance(resp, Mapping):
            raise ClientExtractionError(
                f"Fake response must be a Mapping, got {type(resp).__name__}."
            )
        return resp
