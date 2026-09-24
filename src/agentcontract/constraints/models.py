"""Core domain models for constraints, provenance, and execution scopes."""

from datetime import datetime, timezone
from enum import StrEnum
from types import MappingProxyType
from typing import Any, TypeAlias
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing_extensions import Self

from agentcontract.common.immutable import FrozenDict, _freeze_value
from agentcontract.constraints.exceptions import (
    ConstraintValidationError,
    InvalidConstraintTransitionError,
)

# Stable identifier type alias for constraints (Python 3.11+ compatible)
ConstraintId: TypeAlias = str


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


class RuleEffect(StrEnum):
    """Explicit enforcement effect of a constraint rule."""

    DENY = "DENY"       # Action matching scope is prohibited (prohibition rule)
    REQUIRE = "REQUIRE" # Action matching scope requires compliance (requirement rule)
    PREFER = "PREFER"   # Advisory guidance / preference (non-blocking warning)


# Explicit state transition table governing lifecycle progression (read-only)
ALLOWED_TRANSITIONS: MappingProxyType[ConstraintStatus, frozenset[ConstraintStatus]] = MappingProxyType({
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
})


def validate_transition(
    current_status: ConstraintStatus,
    target_status: ConstraintStatus,
    constraint_id: ConstraintId | None = None,
) -> None:
    """Validate that a lifecycle state transition is allowed by the domain state machine.

    Args:
        current_status: The current lifecycle status of the constraint.
        target_status: The attempted target lifecycle status.
        constraint_id: Optional constraint ID for context in error messages.

    Raises:
        InvalidConstraintTransitionError: If the transition is not in ALLOWED_TRANSITIONS.
    """
    allowed = ALLOWED_TRANSITIONS.get(current_status, frozenset())
    if target_status not in allowed:
        cid_context = f" for constraint '{constraint_id}'" if constraint_id else ""
        raise InvalidConstraintTransitionError(
            f"Illegal lifecycle transition{cid_context}: cannot transition from "
            f"'{current_status.value}' to '{target_status.value}'."
        )


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
    rule_effect: RuleEffect = Field(
        default=RuleEffect.DENY,
        description="Explicit rule enforcement effect: DENY, REQUIRE, or PREFER.",
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
        description="Target selectors and execution boundaries defining when this constraint applies.",
    )
    compliance_scope: ConstraintScope | None = Field(
        default=None,
        description="Required or preferred target selectors defining compliance condition for REQUIRE and PREFER rules.",
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
        # REQUIRE and PREFER rules require an explicit compliance_scope
        if self.rule_effect in (RuleEffect.REQUIRE, RuleEffect.PREFER) and self.compliance_scope is None:
            raise ConstraintValidationError(
                f"Constraint '{self.id}' with rule_effect={self.rule_effect.value} requires a non-None compliance_scope."
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

    @property
    def effective_rule_effect(self) -> RuleEffect:
        """Return the authoritative rule effect."""
        return self.rule_effect

    @property
    def effect(self) -> RuleEffect:
        """Convenience alias for effective_rule_effect."""
        return self.effective_rule_effect
