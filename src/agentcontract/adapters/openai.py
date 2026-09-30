"""OpenAI-compatible structured extraction client adapter."""

from collections.abc import Callable, Mapping, Sequence
import json
import math
import os
import urllib.error
import urllib.request
from typing import Any

from agentcontract.adapters.exceptions import AdapterConfigurationError
from agentcontract.extraction.client import StructuredExtractionClient
from agentcontract.extraction.exceptions import ClientExtractionError
from agentcontract.extraction.models import (
    get_claim_extraction_schema,
    get_requirement_extraction_schema,
)

REQUIREMENT_EXTRACTION_GUIDANCE = (
    "Extraction Guidelines for Requirements & Constraints:\n"
    "1. Distinguish ordinary task steps/completion objectives from runtime-enforceable constraints.\n"
    "   Do not convert ordinary task instructions or goals (e.g. 'inspect repo', 'refactor code', 'run tests') into constraints unless they represent persistent negative prohibitions or positive mandates.\n"
    "2. Rule Effects & Compliance Scope:\n"
    "   - DENY constraints prohibit actions (e.g. 'Do NOT write to or modify secrets/prod.key'). DENY constraints do NOT need a compliance_scope (set compliance_scope to null).\n"
    "   - REQUIRE / PREFER constraints mandate actions or prerequisites.\n"
    "     CRITICAL: Do NOT invent a REQUIRE or PREFER constraint unless BOTH an applicability 'scope' AND a meaningful non-empty 'compliance_scope' can be explicitly defined.\n"
    "     A REQUIRE or PREFER constraint without a non-empty compliance_scope will be strictly rejected by domain validation.\n"
    "3. Canonical Action Vocabulary:\n"
    "   - Prefer canonical AgentContract action kinds: 'FILE_READ', 'FILE_WRITE', 'FILE_DELETE', 'TOOL_CALL', 'COMMAND_EXEC', 'NETWORK_REQUEST', 'STATE_CHANGE', 'GENERIC'.\n"
    "   - For file write prohibitions, include 'FILE_WRITE' and 'FILE_DELETE' in scope actions, or specify the protected path(s).\n"
    "4. Runtime-Compatible Target Types:\n"
    "   - Use runtime-compatible target types when needed (e.g. 'filesystem', 'tool', 'network', 'database', 'generic') or leave target_type null when path, tool, or action dimensions are sufficient.\n"
    "   - Never invent narrow, non-standard target types (such as 'file') that would cause a path-based constraint to fail matching runtime actions.\n"
    "5. Authority & Provenance:\n"
    "   - Model output is untrusted and cannot define caller provenance or enforcement authority. Focus solely on extracting objective constraint specifications."
)

CLAIM_EXTRACTION_GUIDANCE = (
    "Extraction Guidelines for Claims:\n"
    "1. Extract atomic, objective completion claims asserted by the agent regarding task completion or execution state.\n"
    "2. Supported Claim Types:\n"
    "   - TESTS_PASSED: Asserts test execution passed. When the text mentions a test command (e.g. 'pytest'), populate command (e.g. command='pytest') and expected_exit_code=0.\n"
    "   - COMMAND_EXITED_ZERO: Asserts a specific command exited with code 0. Populate command with the exact command string (e.g. command='python script.py').\n"
    "   - FILE_EXISTS: Asserts a specific file exists on disk. Populate target_path with the exact file path (e.g. target_path='secrets/prod.key').\n"
    "   - TOOL_SUCCEEDED: Asserts a specific tool call succeeded. Populate tool_name and/or call_id only when explicitly stated in the text.\n"
    "   - ACTION_COMPLETED / GENERIC: Other factual execution claims without specific verification targets.\n"
    "3. Deterministic Grounding & Selectors:\n"
    "   - Populate selectors (command, target_path, tool_name, call_id) ONLY when explicitly stated or directly inferable from the completion text.\n"
    "   - When a test suite or command is mentioned in text (such as 'pytest'), include it in the 'command' field so EvidenceGate can locate the execution.\n"
    "   - Never invent fictitious call IDs or paths not present in the supplied text.\n"
    "4. Keep claims atomic; do not merge distinct test and file claims into a single item.\n"
    "5. Model output cannot self-verify claims; EvidenceGate will evaluate them against trace evidence."
)



def validate_strict_json_schema(schema: Any, path: str = "$") -> None:
    """Recursively validate that schema conforms strictly to OpenAI Structured Outputs rules.

    Checks:
    1. Every object schema has additionalProperties is False.
    2. Every object schema has required defined as a list or tuple.
    3. Every key in properties is in required (set(properties.keys()) == set(required)).
    4. No unrestricted objects ({"type": "object"} without closed properties).
    """
    if not isinstance(schema, Mapping):
        return

    is_object = schema.get("type") == "object" or "properties" in schema
    if is_object:
        if schema.get("additionalProperties") is not False:
            raise AssertionError(
                f"Object at '{path}' must have 'additionalProperties: False', got {schema.get('additionalProperties')!r}"
            )

        props = schema.get("properties")
        if props is None or not isinstance(props, Mapping):
            raise AssertionError(f"Unrestricted object at '{path}' has no properties defined.")

        req = schema.get("required")
        if not isinstance(req, (list, tuple)):
            raise AssertionError(f"Object at '{path}' must have 'required' list/tuple, got {type(req).__name__}")

        prop_keys = set(props.keys())
        req_keys = set(req)
        if prop_keys != req_keys:
            missing = prop_keys - req_keys
            extra = req_keys - prop_keys
            raise AssertionError(
                f"Object at '{path}' properties keys != required keys. "
                f"Properties not in required: {missing}. Required not in properties: {extra}"
            )

        for p_name, p_schema in props.items():
            if isinstance(p_schema, Mapping):
                if p_schema.get("type") == "object" and not p_schema.get("properties") and not p_schema.get("anyOf"):
                    raise AssertionError(f"Property '{p_name}' at '{path}' is an unrestricted object without properties.")
                validate_strict_json_schema(p_schema, f"{path}.properties.{p_name}")

    if "items" in schema and isinstance(schema["items"], Mapping):
        validate_strict_json_schema(schema["items"], f"{path}.items")

    for union_key in ("anyOf", "oneOf", "allOf"):
        if union_key in schema and isinstance(schema[union_key], (list, tuple)):
            for idx, item in enumerate(schema[union_key]):
                if isinstance(item, Mapping):
                    validate_strict_json_schema(item, f"{path}.{union_key}[{idx}]")


def _make_nullable(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Ensure a property schema allows null as a valid value for OpenAI Structured Outputs."""
    result = dict(schema)

    # If anyOf already has null, return as-is
    if "anyOf" in result and isinstance(result["anyOf"], (list, tuple)):
        has_null = any(
            isinstance(sub, Mapping) and sub.get("type") == "null"
            for sub in result["anyOf"]
        )
        if not has_null:
            result["anyOf"] = list(result["anyOf"]) + [{"type": "null"}]
        return result

    t = result.get("type")
    # If type is a list and contains "null", already nullable
    if isinstance(t, list):
        if "null" not in t:
            result["type"] = list(t) + ["null"]
        return result

    # If type is an object, wrap in anyOf: [object_schema, {"type": "null"}]
    if t == "object" or "properties" in result:
        desc = result.pop("description", None)
        wrapper: dict[str, Any] = {"anyOf": [result, {"type": "null"}]}
        if desc:
            wrapper["description"] = desc
        return wrapper

    # If type is a primitive string
    if isinstance(t, str):
        result["type"] = [t, "null"]
        return result

    return {"anyOf": [result, {"type": "null"}]}


def get_openai_requirement_extraction_schema() -> dict[str, Any]:
    """Return an OpenAI strict Structured Outputs compatible JSON Schema for requirement extraction."""
    scope_props = {
        "target_type": {
            "type": ["string", "null"],
            "description": "Category of target resource (e.g. 'filesystem', 'tool', 'network', 'database', 'generic') or null.",
        },
        "paths": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Target file or resource paths/globs governed by this constraint.",
        },
        "tools": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Tool names governed by this constraint.",
        },
        "actions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Action kinds: 'FILE_READ', 'FILE_WRITE', 'FILE_DELETE', 'TOOL_CALL', 'COMMAND_EXEC', 'NETWORK_REQUEST', 'STATE_CHANGE', 'GENERIC'.",
        },
        "description": {"type": ["string", "null"]},
    }
    scope_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": scope_props,
        "required": sorted(scope_props.keys()),
    }
    compliance_scope_schema = {
        "anyOf": [
            scope_schema,
            {"type": "null"},
        ],
        "description": "Compliance scope for REQUIRE and PREFER rules specifying mandatory compliance actions. Set to null for DENY rules.",
    }
    constraint_props = {
        "name": {
            "type": "string",
            "description": "Short machine- or human-readable identifier (e.g. 'protect_production_keys').",
        },
        "description": {
            "type": "string",
            "description": "Full requirement description or rule specification.",
        },
        "strength": {
            "type": "string",
            "enum": ["HARD", "SOFT", "ASSUMPTION"],
            "description": "Enforcement strength. HARD constraints strictly block violations.",
        },
        "rule_effect": {
            "type": "string",
            "enum": ["DENY", "REQUIRE", "PREFER"],
            "description": "Enforcement rule effect: 'DENY' (negative prohibition), 'REQUIRE' (mandatory action, requires compliance_scope), 'PREFER' (advisory).",
        },
        "scope": scope_schema,
        "compliance_scope": compliance_scope_schema,
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "constraints": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": constraint_props,
                    "required": sorted(constraint_props.keys()),
                },
            }
        },
        "required": ["constraints"],
    }


def get_openai_claim_extraction_schema() -> dict[str, Any]:
    """Return an OpenAI strict Structured Outputs compatible JSON Schema for claim extraction."""
    claim_props = {
        "claim_type": {
            "type": "string",
            "enum": [
                "TOOL_SUCCEEDED",
                "COMMAND_EXITED_ZERO",
                "TESTS_PASSED",
                "FILE_EXISTS",
                "ACTION_COMPLETED",
                "GENERIC",
            ],
            "description": "Category of completion or state claim.",
        },
        "description": {
            "type": "string",
            "description": "Atomic statement of what is claimed.",
        },
        "call_id": {
            "type": ["string", "null"],
            "description": "Tool call identifier if explicitly mentioned in text (e.g. 'call_123'), otherwise null.",
        },
        "tool_name": {
            "type": ["string", "null"],
            "description": "Exact tool name if explicitly stated in text (e.g. 'read_file'), otherwise null.",
        },
        "command": {
            "type": ["string", "null"],
            "description": "Exact command string (e.g. 'pytest', 'python script.py') if stated in text for TESTS_PASSED or COMMAND_EXITED_ZERO, otherwise null.",
        },
        "target_path": {
            "type": ["string", "null"],
            "description": "Exact file or resource path for FILE_EXISTS (e.g. 'secrets/prod.key'), otherwise null.",
        },
        "expected_exit_code": {
            "type": ["integer", "null"],
            "description": "Expected numeric process exit code (e.g. 0), or null.",
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": claim_props,
                    "required": sorted(claim_props.keys()),
                },
            }
        },
        "required": ["claims"],
    }


def to_strict_json_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively transform a JSON Schema into an OpenAI strict Structured Outputs compatible schema.

    Rules enforced:
    1. Every object has additionalProperties: False.
    2. Every declared property appears in required (set(properties.keys()) == set(required)).
    3. Unrestricted objects without properties (such as selectors or metadata) are omitted.
    4. Optional semantic properties are converted to required nullable properties.
    """
    if "properties" in schema and isinstance(schema["properties"], Mapping):
        if "constraints" in schema["properties"]:
            return get_openai_requirement_extraction_schema()
        if "claims" in schema["properties"]:
            return get_openai_claim_extraction_schema()

    out: dict[str, Any] = {}

    for k, v in schema.items():
        if k not in ("properties", "required", "additionalProperties", "items", "anyOf", "oneOf", "allOf"):
            out[k] = v

    is_object = schema.get("type") == "object" or "properties" in schema

    if "items" in schema and isinstance(schema["items"], Mapping):
        out["items"] = to_strict_json_schema(schema["items"])

    for union_key in ("anyOf", "oneOf", "allOf"):
        if union_key in schema and isinstance(schema[union_key], (list, tuple)):
            out[union_key] = [
                to_strict_json_schema(item) if isinstance(item, Mapping) else item
                for item in schema[union_key]
            ]

    if is_object:
        out["type"] = "object"
        out["additionalProperties"] = False

        orig_props = schema.get("properties")
        orig_required = set(schema.get("required") or ())

        if isinstance(orig_props, Mapping):
            new_props: dict[str, Any] = {}
            for prop_name, prop_schema in orig_props.items():
                if not isinstance(prop_schema, Mapping):
                    continue

                # Omit unrestricted objects without explicit properties (e.g. selectors, metadata)
                if prop_schema.get("type") == "object" and "properties" not in prop_schema and "anyOf" not in prop_schema:
                    continue
                if prop_name in ("selectors", "metadata") and "properties" not in prop_schema and "anyOf" not in prop_schema:
                    continue

                transformed_sub = to_strict_json_schema(prop_schema)
                is_orig_required = prop_name in orig_required

                if is_orig_required:
                    new_props[prop_name] = transformed_sub
                else:
                    new_props[prop_name] = _make_nullable(transformed_sub)

            out["properties"] = new_props
            out["required"] = sorted(new_props.keys())

    return out


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
        timeout: float | None = None,
        temperature: float = 0.0,
        response_format_mode: str = "json_schema",
        transport: Callable[[urllib.request.Request], Any] | None = None,
    ) -> None:
        """Initialize the extraction client.

        Args:
            model: Model name/identifier (e.g. 'gpt-4o-mini', 'llama3', 'mistral').
            api_key: Optional API key. If omitted, reads from OPENAI_API_KEY environment variable.
            base_url: Base API URL (defaults to 'https://api.openai.com/v1').
            timeout: Network request timeout in seconds. If omitted, reads OPENAI_TIMEOUT (default 30.0).
            temperature: Sampling temperature (defaults to 0.0 for deterministic extraction).
            response_format_mode: Extraction format mode: 'json_schema' (OpenAI Structured Outputs,
                recommended default) or 'json_object' (JSON Mode for compatible providers).
            transport: Optional custom transport callable for tests or custom HTTP handling.
        """
        effective_model = model
        if effective_model == "gpt-4o-mini" and os.environ.get("OPENAI_MODEL"):
            effective_model = os.environ["OPENAI_MODEL"].strip()

        effective_base_url = base_url
        if effective_base_url == "https://api.openai.com/v1" and os.environ.get("OPENAI_BASE_URL"):
            effective_base_url = os.environ["OPENAI_BASE_URL"].strip()

        effective_mode = response_format_mode
        if effective_mode == "json_schema" and os.environ.get("OPENAI_RESPONSE_FORMAT"):
            effective_mode = os.environ["OPENAI_RESPONSE_FORMAT"].strip()

        if effective_mode not in ("json_schema", "json_object"):
            raise AdapterConfigurationError(
                f"Invalid response_format_mode '{effective_mode}'. "
                f"Supported modes are 'json_schema' (OpenAI Structured Outputs) and 'json_object' (JSON Mode)."
            )

        effective_timeout: float
        if timeout is None:
            if os.environ.get("OPENAI_TIMEOUT"):
                raw_timeout = os.environ["OPENAI_TIMEOUT"].strip()
                try:
                    parsed_t = float(raw_timeout)
                    if not math.isfinite(parsed_t) or parsed_t <= 0:
                        raise ValueError()
                    effective_timeout = parsed_t
                except Exception:
                    raise AdapterConfigurationError(
                        f"Invalid OPENAI_TIMEOUT '{raw_timeout}'. Must be a positive finite number."
                    )
            else:
                effective_timeout = 30.0
        else:
            try:
                parsed_t = float(timeout)
                if not math.isfinite(parsed_t) or parsed_t <= 0:
                    raise ValueError()
                effective_timeout = parsed_t
            except Exception:
                raise AdapterConfigurationError(
                    f"Invalid timeout '{timeout}'. Must be a positive finite number."
                )

        self._model = effective_model.strip()
        self._api_key = api_key.strip() if api_key else os.environ.get("OPENAI_API_KEY")
        self._base_url = effective_base_url.rstrip("/")
        self._timeout = effective_timeout
        self._temperature = float(temperature)
        self._response_format_mode = effective_mode
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
    def response_format_mode(self) -> str:
        """Configured response format mode ('json_schema' or 'json_object')."""
        return self._response_format_mode

    @property
    def timeout(self) -> float:
        """Network request timeout in seconds."""
        return self._timeout

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
            f"base_url='{self._base_url}', mode='{self._response_format_mode}', "
            f"timeout={self._timeout}, api_key='{self._get_masked_key()}')"
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
        if self._response_format_mode == "json_schema":
            target_schema = to_strict_json_schema(schema)
            resp_format: dict[str, Any] = {
                "type": "json_schema",
                "json_schema": {
                    "name": task,
                    "strict": True,
                    "schema": target_schema,
                },
            }
        else:
            target_schema = dict(schema)
            resp_format = {"type": "json_object"}

        guidance = ""
        if task == "extract_requirements":
            guidance = f"\n\n{REQUIREMENT_EXTRACTION_GUIDANCE}"
        elif task == "extract_claims":
            guidance = f"\n\n{CLAIM_EXTRACTION_GUIDANCE}"

        user_content = (
            f"Task: {task}\n\n"
            f"Input Text:\n{text}"
            f"{guidance}\n\n"
            f"Target JSON Schema:\n{json.dumps(target_schema, indent=2)}"
        )

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": user_content},
            ],
            "response_format": resp_format,
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
