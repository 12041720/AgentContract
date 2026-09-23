"""Core domain models for constraints, provenance, and execution scopes."""

from collections.abc import Mapping
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, TypeAlias
from pydantic import BaseModel, ConfigDict, Field, GetCoreSchemaHandler, field_validator, model_validator
from pydantic_core import core_schema
from typing_extensions import Self

from agentcontract.constraints.exceptions import ConstraintValidationError

# Stable identifier type alias for constraints (Python 3.11+ compatible)
ConstraintId: TypeAlias = str


def _freeze_value(val: Any) -> Any:
    """Recursively convert nested mutable collections into immutable equivalents."""
    if isinstance(val, dict):
        return FrozenDict({str(k): _freeze_value(v) for k, v in val.items()})
    if isinstance(val, (list, tuple)):
        return tuple(_freeze_value(v) for v in val)
    if isinstance(val, (set, frozenset)):
        return frozenset(_freeze_value(v) for v in val)
    return val


class FrozenDict(dict[str, Any]):
    """An immutable, deeply frozen dictionary for domain metadata and selectors."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raw: dict[str, Any] = dict(*args, **kwargs)
        frozen_data = {str(k): _freeze_value(v) for k, v in raw.items()}
        super().__init__(frozen_data)

    def __setitem__(self, key: str, value: Any) -> None:
        raise TypeError("FrozenDict is immutable; item assignment is prohibited.")

    def __delitem__(self, key: str) -> None:
        raise TypeError("FrozenDict is immutable; item deletion is prohibited.")

    def pop(self, *args: Any, **kwargs: Any) -> Any:
        raise TypeError("FrozenDict is immutable; pop operation is prohibited.")

    def popitem(self) -> tuple[str, Any]:
        raise TypeError("FrozenDict is immutable; popitem operation is prohibited.")

    def clear(self) -> None:
        raise TypeError("FrozenDict is immutable; clear operation is prohibited.")

    def update(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("FrozenDict is immutable; update operation is prohibited.")

    def setdefault(self, *args: Any, **kwargs: Any) -> Any:
        raise TypeError("FrozenDict is immutable; setdefault operation is prohibited.")

    @classmethod
    def __get_pydantic_core_schema__(
        cls, source_type: Any, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        dict_schema = handler(dict[str, Any])
        return core_schema.no_info_after_validator_function(
            cls,
            dict_schema,
            serialization=core_schema.plain_serializer_function_ser_schema(
                lambda v: dict(v),
                return_schema=core_schema.dict_schema(),
            ),
        )


class ConstraintSource(StrEnum):
    """Origin authority of a constraint."""

    USER = "USER"
    POLICY = "POLICY"
    REPOSITORY = "REPOSITORY"
    TOOL = "TOOL"
    AGENT_INFERENCE = "AGENT_INFERENCE"


class ConstraintStrength(StrEnum):
    """Authority and enforcement level of a constraint."""

    HARD = "HARD"
    SOFT = "SOFT"
    ASSUMPTION = "ASSUMPTION"


class ConstraintStatus(StrEnum):
    """Lifecycle status of a constraint record."""

    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"
    CONFLICTED = "CONFLICTED"


# Explicit state transition table governing lifecycle progression
ALLOWED_TRANSITIONS: dict[ConstraintStatus, frozenset[ConstraintStatus]] = {
    ConstraintStatus.ACTIVE: frozenset({
        ConstraintStatus.REVOKED,
        ConstraintStatus.SUPERSEDED,
        ConstraintStatus.CONFLICTED,
    }),
    ConstraintStatus.CONFLICTED: frozenset({
        ConstraintStatus.ACTIVE,      # Conflict resolved / cleared
        ConstraintStatus.REVOKED,     # Conflict resolved by cancellation
        ConstraintStatus.SUPERSEDED,  # Conflict resolved by replacing with a harmonized rule
    }),
    ConstraintStatus.REVOKED: frozenset(),     # Terminal state
    ConstraintStatus.SUPERSEDED: frozenset(),  # Terminal state
}


class ConstraintProvenance(BaseModel):
    """Durable origin and authority evidence for a constraint."""

    model_config = ConfigDict(frozen=True)

    source: ConstraintSource = Field(
        ...,
        description="The authoritative source category for this requirement.",
    )
    source_location: str | None = Field(
        default=None,
        description="Reference location (e.g., prompt turn index, file path, policy rule ID).",
    )
    source_text: str | None = Field(
        default=None,
        description="Raw natural language text or instruction from which this requirement was extracted.",
    )
    author: str | None = Field(
        default=None,
        description="Author or agent role that introduced the constraint.",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when provenance was recorded.",
    )
    metadata: FrozenDict = Field(
        default_factory=FrozenDict,
        description="Arbitrary structured provenance attributes.",
    )


class ConstraintScope(BaseModel):
    """Generic structured selector defining execution boundaries for a constraint."""

    model_config = ConfigDict(frozen=True)

    target_type: str | None = Field(
        default=None,
        description="Category of target (e.g., 'filesystem', 'database', 'tool', 'network', 'generic').",
    )
    paths: tuple[str, ...] = Field(
        default_factory=tuple,
        description="File or resource paths governed by this constraint.",
    )
    tools: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Tool or API identifiers governed by this constraint.",
    )
    actions: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Action types governed by this constraint (e.g., 'write', 'execute', 'delete').",
    )
    selectors: FrozenDict = Field(
        default_factory=FrozenDict,
        description="Extensible structured criteria for domain-specific matching.",
    )
    description: str | None = Field(
        default=None,
        description="Human-readable summary of the constraint scope.",
    )


class ConstraintRelation(BaseModel):
    """Lineage, supersession, revocation, and conflict tracking metadata."""

    model_config = ConfigDict(frozen=True)

    supersedes: str | None = Field(
        default=None,
        description="ID of the previous constraint this record replaces.",
    )
    superseded_by: str | None = Field(
        default=None,
        description="ID of the newer constraint that replaced this record.",
    )
    revocation_reason: str | None = Field(
        default=None,
        description="Explanation for why the constraint was revoked.",
    )
    revoked_at: datetime | None = Field(
        default=None,
        description="UTC timestamp when the constraint was revoked.",
    )
    superseded_at: datetime | None = Field(
        default=None,
        description="UTC timestamp when the constraint was superseded.",
    )
    conflicts_with: tuple[str, ...] = Field(
        default_factory=tuple,
        description="IDs of other constraints currently in conflict with this one.",
    )
    metadata: FrozenDict = Field(
        default_factory=FrozenDict,
        description="Additional relation or transition metadata.",
    )


class Constraint(BaseModel):
    """A durable, version-preserving constraint record governing agent execution."""

    model_config = ConfigDict(frozen=True)

    id: ConstraintId = Field(
        ...,
        description="Unique stable identifier for the constraint.",
    )
    name: str = Field(
        ...,
        description="Machine- or human-readable identifier (e.g., 'no_db_schema_modifications').",
    )
    description: str = Field(
        ...,
        description="Detailed requirement description or rule specification.",
    )
    strength: ConstraintStrength = Field(
        ...,
        description="Authority level: HARD (blocking), SOFT (preference), ASSUMPTION (inferred).",
    )
    status: ConstraintStatus = Field(
        default=ConstraintStatus.ACTIVE,
        description="Current lifecycle status.",
    )
    provenance: ConstraintProvenance = Field(
        ...,
        description="Provenance and authority origin.",
    )
    scope: ConstraintScope = Field(
        default_factory=ConstraintScope,
        description="Target selectors and execution boundaries.",
    )
    relations: ConstraintRelation = Field(
        default_factory=ConstraintRelation,
        description="Lifecycle relations and transition history.",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when this constraint record was created.",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when this record was last modified or transitioned.",
    )

    @field_validator("id", "name")
    @classmethod
    def _validate_non_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ConstraintValidationError("Identifier and name must not be empty or blank.")
        return stripped

    @model_validator(mode="after")
    def _validate_invariants(self) -> Self:
        # Invariant 8: AGENT_INFERENCE cannot masquerade as an explicit user hard constraint
        if self.provenance.source == ConstraintSource.AGENT_INFERENCE and self.strength == ConstraintStrength.HARD:
            raise ConstraintValidationError(
                "AGENT_INFERENCE cannot be declared with HARD strength; inferences must be SOFT or ASSUMPTION."
            )
        return self

    @property
    def is_active(self) -> bool:
        """Return True if this constraint is actively enforced."""
        return self.status == ConstraintStatus.ACTIVE

    @property
    def is_terminal(self) -> bool:
        """Return True if this constraint is in a terminal lifecycle state (REVOKED or SUPERSEDED)."""
        return self.status in (ConstraintStatus.REVOKED, ConstraintStatus.SUPERSEDED)

    @property
    def is_hard(self) -> bool:
        """Return True if this constraint is a hard requirement/prohibition."""
        return self.strength == ConstraintStrength.HARD

    @property
    def is_assumption(self) -> bool:
        """Return True if this constraint is an assumption."""
        return self.strength == ConstraintStrength.ASSUMPTION

    @property
    def source(self) -> ConstraintSource:
        """Convenience accessor for provenance source."""
        return self.provenance.source
