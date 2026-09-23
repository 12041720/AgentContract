"""In-memory, version-preserving constraint ledger."""

from collections.abc import Iterable, Iterator
from datetime import datetime, timezone
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

from agentcontract.constraints.exceptions import (
    ConstraintNotFoundError,
    DuplicateConstraintError,
    InvalidConstraintTransitionError,
)
from agentcontract.constraints.models import (
    ALLOWED_TRANSITIONS,
    Constraint,
    ConstraintId,
    ConstraintStatus,
    FrozenDict,
)


class LedgerSnapshot(BaseModel):
    """Durable, structurally immutable snapshot of constraint ledger state."""

    model_config = ConfigDict(frozen=True)

    schema_version: str = Field(
        default="1.0",
        description="Schema format version for the ledger serialization format.",
    )
    constraints: tuple[Constraint, ...] = Field(
        default_factory=tuple,
        description="All recorded constraints in the ledger, preserving full history.",
    )
    metadata: FrozenDict = Field(
        default_factory=FrozenDict,
        description="Optional ledger-level metadata.",
    )


class ConstraintLedger:
    """In-memory, version-preserving ledger governing active and historical constraints.

    Enforces unique identifiers, deep immutability across transitions,
    explicit lifecycle progression (active -> revoked / superseded / conflicted),
    and reliable serialization round-tripping.
    """

    def __init__(self, constraints: Iterable[Constraint] | None = None) -> None:
        self._constraints: dict[ConstraintId, Constraint] = {}
        if constraints:
            for constraint in constraints:
                self.add(constraint)

    def add(self, constraint: Constraint) -> Constraint:
        """Add a new constraint to the ledger.

        New constraints must enter the ledger with ACTIVE status.

        Args:
            constraint: The constraint model to register.

        Returns:
            The registered Constraint.

        Raises:
            DuplicateConstraintError: If a constraint with the same ID already exists.
            InvalidConstraintTransitionError: If the constraint does not have ACTIVE status.
        """
        if constraint.id in self._constraints:
            raise DuplicateConstraintError(
                f"Constraint with id '{constraint.id}' already exists in ledger."
            )
        if constraint.status != ConstraintStatus.ACTIVE:
            raise InvalidConstraintTransitionError(
                f"New constraint '{constraint.id}' must enter ledger with status ACTIVE, "
                f"got '{constraint.status.value}'."
            )

        self._constraints[constraint.id] = constraint
        return constraint

    def get(self, constraint_id: ConstraintId) -> Constraint:
        """Retrieve a constraint by ID, regardless of lifecycle status.

        Args:
            constraint_id: Unique constraint identifier.

        Returns:
            The Constraint record.

        Raises:
            ConstraintNotFoundError: If the constraint does not exist.
        """
        if constraint_id not in self._constraints:
            raise ConstraintNotFoundError(
                f"Constraint with id '{constraint_id}' not found in ledger."
            )
        return self._constraints[constraint_id]

    def list_active(self) -> list[Constraint]:
        """Return all currently active constraints.

        Terminal (REVOKED, SUPERSEDED) and conflicted constraints are excluded.
        """
        return [c for c in self._constraints.values() if c.is_active]

    def list_all(self) -> list[Constraint]:
        """Return all recorded constraints, including revoked and superseded records."""
        return list(self._constraints.values())

    def revoke(
        self,
        constraint_id: ConstraintId,
        *,
        reason: str | None = None,
        revoked_at: datetime | None = None,
    ) -> Constraint:
        """Revoke an active or conflicted constraint.

        Revocation is permitted from ACTIVE or CONFLICTED status. Terminal constraints
        (REVOKED, SUPERSEDED) cannot be revoked again.

        Args:
            constraint_id: Identifier of the constraint to revoke.
            reason: Optional explanation for why the requirement was revoked.
            revoked_at: Optional transition timestamp (defaults to current UTC time).

        Returns:
            The updated Constraint record in REVOKED status.

        Raises:
            ConstraintNotFoundError: If the constraint does not exist.
            InvalidConstraintTransitionError: If the constraint is in a terminal or invalid state.
        """
        existing = self.get(constraint_id)
        if existing.is_terminal:
            raise InvalidConstraintTransitionError(
                f"Cannot revoke constraint '{constraint_id}' because it is already in terminal "
                f"status '{existing.status.value}'."
            )
        if existing.status not in (ConstraintStatus.ACTIVE, ConstraintStatus.CONFLICTED):
            raise InvalidConstraintTransitionError(
                f"Cannot revoke constraint '{constraint_id}' from status '{existing.status.value}'."
            )

        timestamp = revoked_at or datetime.now(timezone.utc)
        updated_relations = existing.relations.model_copy(
            update={
                "revocation_reason": reason,
                "revoked_at": timestamp,
            }
        )
        revoked = existing.model_copy(
            update={
                "status": ConstraintStatus.REVOKED,
                "relations": updated_relations,
                "updated_at": timestamp,
            }
        )
        self._constraints[constraint_id] = revoked
        return revoked

    def supersede(
        self,
        existing_id: ConstraintId,
        replacement: Constraint,
        *,
        superseded_at: datetime | None = None,
    ) -> Constraint:
        """Supersede an active or conflicted constraint with a newer replacement constraint.

        The existing constraint is marked SUPERSEDED with a reference to the replacement ID.
        The replacement must be in ACTIVE status and links back to the superseded ID.
        Full historical provenance is preserved for both records.

        Args:
            existing_id: Identifier of the active or conflicted constraint being superseded.
            replacement: New replacement Constraint (must be in ACTIVE status).
            superseded_at: Optional transition timestamp (defaults to current UTC time).

        Returns:
            The newly registered and activated replacement Constraint.
            (The old record remains retrievable via `get(existing_id)`).

        Raises:
            ConstraintNotFoundError: If `existing_id` does not exist.
            InvalidConstraintTransitionError: If the existing constraint is in a terminal state,
                or if the replacement does not have ACTIVE status, or reuses the same ID.
            DuplicateConstraintError: If replacement.id already exists in the ledger.
        """
        existing = self.get(existing_id)
        if existing.is_terminal:
            raise InvalidConstraintTransitionError(
                f"Cannot supersede constraint '{existing_id}' because it is already in terminal "
                f"status '{existing.status.value}'."
            )
        if existing.status not in (ConstraintStatus.ACTIVE, ConstraintStatus.CONFLICTED):
            raise InvalidConstraintTransitionError(
                f"Cannot supersede constraint '{existing_id}' from status '{existing.status.value}'."
            )
        if replacement.id == existing_id:
            raise InvalidConstraintTransitionError(
                f"Replacement constraint cannot reuse the existing id '{existing_id}'; "
                f"a distinct id is required to preserve history."
            )
        if replacement.id in self._constraints:
            raise DuplicateConstraintError(
                f"Replacement constraint with id '{replacement.id}' already exists in ledger."
            )
        if replacement.status != ConstraintStatus.ACTIVE:
            raise InvalidConstraintTransitionError(
                f"Replacement constraint '{replacement.id}' must have status ACTIVE, "
                f"got '{replacement.status.value}'."
            )

        timestamp = superseded_at or datetime.now(timezone.utc)

        # 1. Update existing constraint as SUPERSEDED and link to replacement
        updated_existing_relations = existing.relations.model_copy(
            update={
                "superseded_by": replacement.id,
                "superseded_at": timestamp,
            }
        )
        superseded_existing = existing.model_copy(
            update={
                "status": ConstraintStatus.SUPERSEDED,
                "relations": updated_existing_relations,
                "updated_at": timestamp,
            }
        )

        # 2. Update replacement constraint to link back to existing
        updated_replacement_relations = replacement.relations.model_copy(
            update={
                "supersedes": existing_id,
            }
        )
        active_replacement = replacement.model_copy(
            update={
                "status": ConstraintStatus.ACTIVE,
                "relations": updated_replacement_relations,
                "updated_at": timestamp,
            }
        )

        self._constraints[existing_id] = superseded_existing
        self._constraints[replacement.id] = active_replacement
        return active_replacement

    def mark_conflicted(
        self,
        constraint_id: ConstraintId,
        conflicting_id: ConstraintId,
        *,
        reason: str | None = None,
    ) -> Constraint:
        """Mark an active constraint as conflicted with another constraint.

        Args:
            constraint_id: Identifier of the active constraint experiencing a conflict.
            conflicting_id: Identifier of the conflicting constraint.
            reason: Optional description of the conflict.

        Returns:
            The updated Constraint record in CONFLICTED status.

        Raises:
            ConstraintNotFoundError: If either constraint does not exist.
            InvalidConstraintTransitionError: If either constraint is in a terminal status.
        """
        existing = self.get(constraint_id)
        conflicting = self.get(conflicting_id)

        if existing.is_terminal:
            raise InvalidConstraintTransitionError(
                f"Cannot mark terminal constraint '{constraint_id}' as conflicted."
            )
        if conflicting.is_terminal:
            raise InvalidConstraintTransitionError(
                f"Cannot mark constraint as conflicted with terminal constraint '{conflicting_id}'."
            )

        conflicts = list(existing.relations.conflicts_with)
        if conflicting_id not in conflicts:
            conflicts.append(conflicting_id)

        updated_metadata = dict(existing.relations.metadata)
        if reason:
            updated_metadata[f"conflict_reason_{conflicting_id}"] = reason

        now = datetime.now(timezone.utc)
        updated_relations = existing.relations.model_copy(
            update={
                "conflicts_with": tuple(conflicts),
                "metadata": FrozenDict(updated_metadata),
            }
        )
        conflicted = existing.model_copy(
            update={
                "status": ConstraintStatus.CONFLICTED,
                "relations": updated_relations,
                "updated_at": now,
            }
        )
        self._constraints[constraint_id] = conflicted
        return conflicted

    def resolve_conflict(
        self,
        constraint_id: ConstraintId,
        *,
        reason: str | None = None,
    ) -> Constraint:
        """Resolve a conflict on a conflicted constraint, returning it to ACTIVE status.

        Args:
            constraint_id: Identifier of the conflicted constraint to reactivate.
            reason: Optional description of how the conflict was resolved.

        Returns:
            The updated Constraint record in ACTIVE status.

        Raises:
            ConstraintNotFoundError: If constraint does not exist.
            InvalidConstraintTransitionError: If constraint status is not CONFLICTED.
        """
        existing = self.get(constraint_id)
        if existing.status != ConstraintStatus.CONFLICTED:
            raise InvalidConstraintTransitionError(
                f"Cannot resolve conflict on constraint '{constraint_id}' with status '{existing.status.value}'; "
                f"status must be CONFLICTED."
            )

        updated_metadata = dict(existing.relations.metadata)
        if reason:
            updated_metadata["conflict_resolution"] = reason

        now = datetime.now(timezone.utc)
        updated_relations = existing.relations.model_copy(
            update={
                "conflicts_with": (),
                "metadata": FrozenDict(updated_metadata),
            }
        )
        reactivated = existing.model_copy(
            update={
                "status": ConstraintStatus.ACTIVE,
                "relations": updated_relations,
                "updated_at": now,
            }
        )
        self._constraints[constraint_id] = reactivated
        return reactivated

    def get_history(self, constraint_id: ConstraintId) -> list[Constraint]:
        """Return the full lineage chain of supersessions for a constraint.

        Traverses backwards to find the root constraint, then follows forward
        supersessions to produce an ordered sequence from root to current replacement.

        Args:
            constraint_id: Identifier of any constraint in the supersession lineage.

        Returns:
            Ordered list of Constraint instances representing the history.

        Raises:
            ConstraintNotFoundError: If constraint_id does not exist.
        """
        current = self.get(constraint_id)

        # Traverse backward to root
        root = current
        seen_backward: set[str] = {root.id}
        while root.relations.supersedes:
            prior_id = root.relations.supersedes
            if prior_id in seen_backward:
                break
            seen_backward.add(prior_id)
            root = self.get(prior_id)

        # Traverse forward from root
        chain: list[Constraint] = [root]
        seen_forward: set[str] = {root.id}
        node = root
        while node.relations.superseded_by:
            next_id = node.relations.superseded_by
            if next_id in seen_forward:
                break
            seen_forward.add(next_id)
            node = self.get(next_id)
            chain.append(node)

        return chain

    def snapshot(self, metadata: dict[str, Any] | None = None) -> LedgerSnapshot:
        """Create a durable, serializable, immutable snapshot of the ledger."""
        return LedgerSnapshot(
            constraints=tuple(self._constraints.values()),
            metadata=FrozenDict(metadata or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the ledger to a dictionary representation."""
        return self.snapshot().model_dump(mode="json")

    def to_json(self, *, indent: int | None = None) -> str:
        """Serialize the ledger to a JSON string."""
        return self.snapshot().model_dump_json(indent=indent)

    @classmethod
    def from_snapshot(cls, snapshot: LedgerSnapshot) -> "ConstraintLedger":
        """Reconstruct a ConstraintLedger from a LedgerSnapshot.

        Args:
            snapshot: A LedgerSnapshot instance.

        Returns:
            A new ConstraintLedger instance.

        Raises:
            DuplicateConstraintError: If snapshot contains duplicate constraint IDs.
        """
        ledger = cls()
        for constraint in snapshot.constraints:
            if constraint.id in ledger._constraints:
                raise DuplicateConstraintError(
                    f"Corrupted snapshot: duplicate constraint id '{constraint.id}'."
                )
            ledger._constraints[constraint.id] = constraint
        return ledger

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConstraintLedger":
        """Reconstruct a ConstraintLedger from a dictionary.

        Args:
            data: Dictionary representation matching LedgerSnapshot schema.

        Returns:
            A new ConstraintLedger instance.
        """
        snapshot = LedgerSnapshot.model_validate(data)
        return cls.from_snapshot(snapshot)

    @classmethod
    def from_json(cls, json_str: str) -> "ConstraintLedger":
        """Reconstruct a ConstraintLedger from a JSON string.

        Args:
            json_str: JSON string matching LedgerSnapshot schema.

        Returns:
            A new ConstraintLedger instance.
        """
        snapshot = LedgerSnapshot.model_validate_json(json_str)
        return cls.from_snapshot(snapshot)

    def __len__(self) -> int:
        return len(self._constraints)

    def __contains__(self, constraint_id: object) -> bool:
        return constraint_id in self._constraints

    def __iter__(self) -> Iterator[Constraint]:
        return iter(self._constraints.values())

    def __getitem__(self, constraint_id: ConstraintId) -> Constraint:
        return self.get(constraint_id)

    def __repr__(self) -> str:
        return (
            f"ConstraintLedger(total={len(self._constraints)}, "
            f"active={len(self.list_active())})"
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ConstraintLedger):
            return False
        return self._constraints == other._constraints
