"""OpenAI-compatible structured extraction client adapter."""

from collections.abc import Callable, Mapping, Sequence
import json
import os
import urllib.error
import urllib.request
from typing import Any

from agentcontract.adapters.exceptions import AdapterConfigurationError
from agentcontract.extraction.client import StructuredExtractionClient
from agentcontract.extraction.exceptions import ClientExtractionError


class OpenAICompatibleExtractionClient(StructuredExtractionClient):
    """Structured extraction client connecting to OpenAI-compatible chat completion APIs.

    Principles:
    - Works with OpenAI, local vLLM, Ollama, LiteLLM, or any OpenAI-compatible HTTP endpoint.
    - Requires zero extra third-party SDK dependencies (uses standard library urllib).
    - Exactly one model request per extraction call (no hidden retries that could duplicate side effects).
    - Model output is treated as completely untrusted raw JSON.
    - Caller provenance and scope authority cannot be bypassed or overridden by model response.
    - Secrets are never logged or exposed in __repr__.
    """

    def __init__(
        self,
        *,
        model: str = "gpt-4o-mini",
        api_key: str | None = None,
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 30.0,
        temperature: float = 0.0,
        transport: Callable[[urllib.request.Request], Any] | None = None,
    ) -> None:
        """Initialize the extraction client.

        Args:
            model: Model name/identifier (e.g. 'gpt-4o-mini', 'llama3', 'mistral').
            api_key: Optional API key. If omitted, reads from OPENAI_API_KEY environment variable.
            base_url: Base API URL (defaults to 'https://api.openai.com/v1').
            timeout: Network request timeout in seconds.
            temperature: Sampling temperature (defaults to 0.0 for deterministic extraction).
            transport: Optional custom transport callable for tests or custom HTTP handling.
        """
        self._model = model.strip()
        self._api_key = api_key.strip() if api_key else os.environ.get("OPENAI_API_KEY")
        self._base_url = base_url.rstrip("/")
        self._timeout = float(timeout)
        self._temperature = float(temperature)
        self._transport = transport
        self._call_count: int = 0

    @property
    def model(self) -> str:
        """Model identifier."""
        return self._model

    @property
    def base_url(self) -> str:
        """Base API URL."""
        return self._base_url

    @property
    def call_count(self) -> int:
        """Total number of HTTP requests issued by this client."""
        return self._call_count

    def _get_masked_key(self) -> str:
        if not self._api_key:
            return "<none>"
        k = self._api_key
        if len(k) > 8:
            return f"{k[:3]}...{k[-4:]}"
        return "***"

    def __repr__(self) -> str:
        return (
            f"OpenAICompatibleExtractionClient(model='{self._model}', "
            f"base_url='{self._base_url}', api_key='{self._get_masked_key()}')"
        )

    def extract(
        self,
        *,
        task: str,
        text: str,
        schema: Mapping[str, Any],
        context: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        """Execute a single structured extraction request against the OpenAI-compatible endpoint.

        Args:
            task: Name of the extraction task (e.g. 'extract_requirements', 'extract_claims').
            text: Input natural language text to analyze.
            schema: Target JSON schema specification for output.
            context: Optional contextual metadata.

        Returns:
            Raw untrusted structured mapping returned by the model.

        Raises:
            AdapterConfigurationError: If no API key is provided and default transport is used.
            ClientExtractionError: If network request fails, or model output is missing, malformed,
                or cannot be decoded into a JSON mapping.
        """
        if self._transport is None and not self._api_key:
            raise AdapterConfigurationError(
                "No API key provided. Pass 'api_key' to OpenAICompatibleExtractionClient "
                "or set the 'OPENAI_API_KEY' environment variable."
            )

        # Build endpoint URL
        endpoint = f"{self._base_url}/chat/completions"

        # Build prompt
        system_content = (
            "You are a structured extraction engine for AgentContract.\n"
            "Extract the requested structured information from the input text conforming strictly to the provided JSON Schema.\n"
            "Return ONLY a valid JSON object matching the schema."
        )
        user_content = (
            f"Task: {task}\n\n"
            f"Input Text:\n{text}\n\n"
            f"Target JSON Schema:\n{json.dumps(dict(schema), indent=2)}"
        )

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content},
            ],
            "response_format": {"type": "json_object"},
            "temperature": self._temperature,
        }

        body_bytes = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        req = urllib.request.Request(
            url=endpoint,
            data=body_bytes,
            headers=headers,
            method="POST",
        )

        # Issue request exactly once (no hidden retries)
        self._call_count += 1

        try:
            if self._transport is not None:
                resp_data = self._transport(req)
                if isinstance(resp_data, bytes):
                    response_text = resp_data.decode("utf-8")
                elif isinstance(resp_data, str):
                    response_text = resp_data
                elif isinstance(resp_data, tuple) and len(resp_data) >= 2:
                    # e.g. (status, body) or (status, headers, body)
                    raw_body = resp_data[-1]
                    response_text = raw_body.decode("utf-8") if isinstance(raw_body, bytes) else str(raw_body)
                elif hasattr(resp_data, "read"):
                    raw_read = resp_data.read()
                    response_text = raw_read.decode("utf-8") if isinstance(raw_read, bytes) else str(raw_read)
                elif isinstance(resp_data, Mapping):
                    # Direct mapping returned by transport
                    return self._parse_completion_response(resp_data)
                else:
                    response_text = str(resp_data)
            else:
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    response_text = resp.read().decode("utf-8")

        except urllib.error.HTTPError as err:
            err_body = ""
            try:
                err_body = err.read().decode("utf-8")
            except Exception:
                pass
            raise ClientExtractionError(
                f"HTTP request to extraction provider failed with status {err.code}: {err.reason}. Response: {err_body}"
            ) from err
        except urllib.error.URLError as err:
            raise ClientExtractionError(
                f"Network connection to extraction provider failed: {err.reason}"
            ) from err
        except TimeoutError as err:
            raise ClientExtractionError(
                f"Network request to extraction provider timed out after {self._timeout}s: {err}"
            ) from err
        except Exception as err:
            if isinstance(err, ClientExtractionError):
                raise
            raise ClientExtractionError(
                f"Failed to communicate with extraction provider: {err}"
            ) from err

        # Parse HTTP response JSON
        try:
            parsed_resp = json.loads(response_text)
        except Exception as err:
            raise ClientExtractionError(
                f"Extraction provider response was not valid JSON: {err}. Raw response: {response_text[:200]}"
            ) from err

        if not isinstance(parsed_resp, Mapping):
            raise ClientExtractionError(
                f"Expected JSON object from provider response, got {type(parsed_resp).__name__}."
            )

        return self._parse_completion_response(parsed_resp)

    def _parse_completion_response(self, response_dict: Mapping[str, Any]) -> Mapping[str, Any]:
        """Extract and parse structured JSON message content from chat completion payload."""
        choices = response_dict.get("choices")
        if not choices or not isinstance(choices, Sequence):
            raise ClientExtractionError(
                f"Malformed model response: 'choices' list missing or empty in {list(response_dict.keys())}."
            )

        first_choice = choices[0]
        if not isinstance(first_choice, Mapping):
            raise ClientExtractionError("Malformed model response: choice item must be an object.")

        message = first_choice.get("message")
        if not isinstance(message, Mapping):
            raise ClientExtractionError("Malformed model response: 'message' object missing.")

        content = message.get("content")
        if content is None or not isinstance(content, str):
            raise ClientExtractionError("Malformed model response: 'content' string missing or null.")

        stripped_content = content.strip()
        if not stripped_content:
            raise ClientExtractionError("Model returned empty content string.")

        try:
            parsed_content = json.loads(stripped_content)
        except Exception as err:
            raise ClientExtractionError(
                f"Model response content is not valid JSON: {err}. Content snippet: {stripped_content[:200]}"
            ) from err

        if not isinstance(parsed_content, Mapping):
            raise ClientExtractionError(
                f"Model structured output must decode to a JSON object (mapping), got {type(parsed_content).__name__}."
            )

        return parsed_content
