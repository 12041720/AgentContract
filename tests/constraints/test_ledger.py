"""Tests for in-memory ConstraintLedger lifecycle, invariants, and serialization."""

from datetime import datetime, timezone
import itertools
import pytest

from agentcontract.constraints.exceptions import (
    ConstraintNotFoundError,
    DuplicateConstraintError,
    InvalidConstraintTransitionError,
)
from agentcontract.constraints.ledger import ConstraintLedger, LedgerSnapshot
from agentcontract.constraints.models import (
    ALLOWED_TRANSITIONS,
    Constraint,
    ConstraintProvenance,
    ConstraintScope,
    ConstraintSource,
    ConstraintStatus,
    ConstraintStrength,
    FrozenDict,
    validate_transition,
)


@pytest.fixture
def empty_ledger() -> ConstraintLedger:
    return ConstraintLedger()


@pytest.fixture
def sample_user_constraint() -> Constraint:
    return Constraint(
        id="c-db-schema",
        name="no_schema_modifications",
        description="Do not modify DB schema",
        strength=ConstraintStrength.HARD,
        provenance=ConstraintProvenance(
            source=ConstraintSource.USER,
            source_location="turn:1",
            source_text="Do not touch the database schema.",
            author="lead_dev",
            metadata={"priority": "P0"},
        ),
        scope=ConstraintScope(
            target_type="database",
            paths=["migrations/", "schema.sql"],
        ),
    )


def test_add_and_retrieve_constraint(empty_ledger: ConstraintLedger, sample_user_constraint: Constraint):
    """Scenario 1: Add explicit hard user constraint: 'do not modify DB schema'."""
    ledger = empty_ledger
    added = ledger.add(sample_user_constraint)

    assert added.id == "c-db-schema"
    assert len(ledger) == 1
    assert "c-db-schema" in ledger

    retrieved = ledger.get("c-db-schema")
    assert retrieved == sample_user_constraint
    assert retrieved.is_active is True
    assert retrieved.is_hard is True
    assert retrieved.source == ConstraintSource.USER


def test_agent_assumption_in_ledger(empty_ledger: ConstraintLedger, sample_user_constraint: Constraint):
    """Scenario 2: Add agent assumption and demonstrate it remains distinguishable from user authority in ledger."""
    ledger = empty_ledger
    ledger.add(sample_user_constraint)

    assumption = Constraint(
        id="c-agent-assumption",
        name="assume_node_20",
        description="Assume Node.js 20 based on package.json engine field",
        strength=ConstraintStrength.ASSUMPTION,
        provenance=ConstraintProvenance(
            source=ConstraintSource.AGENT_INFERENCE,
            source_text="Found 'node >=20' in package.json",
        ),
    )
    ledger.add(assumption)

    active_constraints = ledger.list_active()
    assert len(active_constraints) == 2

    # Verification: user authority vs agent assumption are distinguishable in the ledger
    c_user = ledger.get("c-db-schema")
    c_assump = ledger.get("c-agent-assumption")

    assert c_user.strength == ConstraintStrength.HARD
    assert c_user.is_hard is True
    assert c_user.is_assumption is False

    assert c_assump.strength == ConstraintStrength.ASSUMPTION
    assert c_assump.is_hard is False
    assert c_assump.is_assumption is True
    assert c_assump.provenance.source == ConstraintSource.AGENT_INFERENCE


def test_revoke_active_constraint(empty_ledger: ConstraintLedger, sample_user_constraint: Constraint):
    """Scenario 3: Revoke an active constraint.

    Checks:
    - Status transitions to REVOKED.
    - Provenance and scope are strictly preserved.
    - Excluded from list_active().
    - Retrievable via get().
    """
    ledger = empty_ledger
    ledger.add(sample_user_constraint)

    revocation_time = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
    revoked = ledger.revoke(
        "c-db-schema",
        reason="Schema migration approved in follow-up task",
        revoked_at=revocation_time,
    )

    assert revoked.status == ConstraintStatus.REVOKED
    assert revoked.is_active is False
    assert revoked.is_terminal is True
    assert revoked.relations.revocation_reason == "Schema migration approved in follow-up task"
    assert revoked.relations.revoked_at == revocation_time

    # Provenance and scope preserved
    assert revoked.provenance == sample_user_constraint.provenance
    assert revoked.scope == sample_user_constraint.scope

    # Excluded from active constraints
    active = ledger.list_active()
    assert len(active) == 0

    # Retrievable from ledger
    fetched = ledger.get("c-db-schema")
    assert fetched.status == ConstraintStatus.REVOKED
    assert fetched == revoked


def test_supersede_constraint(empty_ledger: ConstraintLedger):
    """Scenario 4: Supersede 'must use Redis' with 'PostgreSQL allowed'; old record remains queryable."""
    ledger = empty_ledger

    old_constraint = Constraint(
        id="c-cache-redis",
        name="must_use_redis",
        description="Must use Redis for shared cache",
        strength=ConstraintStrength.HARD,
        provenance=ConstraintProvenance(
            source=ConstraintSource.USER,
            source_text="Use Redis only for caching",
            author="lead_dev",
        ),
    )
    ledger.add(old_constraint)

    new_constraint = Constraint(
        id="c-cache-postgres",
        name="postgres_caching_allowed",
        description="PostgreSQL allowed as an alternate cache store",
        strength=ConstraintStrength.HARD,
        provenance=ConstraintProvenance(
            source=ConstraintSource.USER,
            source_text="PostgreSQL unlogged tables are acceptable for cache",
            author="lead_dev",
        ),
    )

    supersede_time = datetime(2026, 9, 23, 13, 0, tzinfo=timezone.utc)
    active_replacement = ledger.supersede(
        "c-cache-redis",
        new_constraint,
        superseded_at=supersede_time,
    )

    # 1. New constraint is active and records what it supersedes
    assert active_replacement.id == "c-cache-postgres"
    assert active_replacement.status == ConstraintStatus.ACTIVE
    assert active_replacement.relations.supersedes == "c-cache-redis"

    # 2. Old constraint is marked SUPERSEDED and points to replacement
    old_record = ledger.get("c-cache-redis")
    assert old_record.status == ConstraintStatus.SUPERSEDED
    assert old_record.is_active is False
    assert old_record.is_terminal is True
    assert old_record.relations.superseded_by == "c-cache-postgres"
    assert old_record.relations.superseded_at == supersede_time

    # 3. Old record's original provenance is intact
    assert old_record.provenance.source_text == "Use Redis only for caching"

    # 4. Active listing only contains the replacement
    active = ledger.list_active()
    assert len(active) == 1
    assert active[0].id == "c-cache-postgres"

    # 5. Full history traversal
    history = ledger.get_history("c-cache-postgres")
    assert [c.id for c in history] == ["c-cache-redis", "c-cache-postgres"]


def test_cannot_revoke_or_supersede_terminal_constraint(empty_ledger: ConstraintLedger, sample_user_constraint: Constraint):
    """Scenario 5: Attempt to revoke/supersede an already terminal constraint and assert explicit failure."""
    ledger = empty_ledger
    ledger.add(sample_user_constraint)

    # Revoke it
    ledger.revoke("c-db-schema", reason="First revocation")

    # Attempt to revoke an already revoked constraint
    with pytest.raises(InvalidConstraintTransitionError) as exc_info:
        ledger.revoke("c-db-schema", reason="Second revocation attempt")
    assert "cannot transition from 'REVOKED' to 'REVOKED'" in str(exc_info.value)

    # Attempt to supersede an already revoked constraint
    replacement = Constraint(
        id="c-replacement-1",
        name="replacement_name",
        description="Replacement",
        strength=ConstraintStrength.SOFT,
        provenance=ConstraintProvenance(source=ConstraintSource.USER),
    )
    with pytest.raises(InvalidConstraintTransitionError) as exc_info:
        ledger.supersede("c-db-schema", replacement)
    assert "cannot transition from 'REVOKED' to 'SUPERSEDED'" in str(exc_info.value)

    # Now test a superseded constraint
    c2 = Constraint(
        id="c-active-2",
        name="test_active",
        description="Description",
        strength=ConstraintStrength.HARD,
        provenance=ConstraintProvenance(source=ConstraintSource.USER),
    )
    ledger.add(c2)
    ledger.supersede("c-active-2", replacement)

    # Attempt to revoke the superseded constraint
    with pytest.raises(InvalidConstraintTransitionError) as exc_info:
        ledger.revoke("c-active-2")
    assert "cannot transition from 'SUPERSEDED' to 'REVOKED'" in str(exc_info.value)

    # Attempt to supersede the already superseded constraint
    replacement_2 = Constraint(
        id="c-replacement-2",
        name="replacement_2",
        description="Replacement 2",
        strength=ConstraintStrength.SOFT,
        provenance=ConstraintProvenance(source=ConstraintSource.USER),
    )
    with pytest.raises(InvalidConstraintTransitionError) as exc_info:
        ledger.supersede("c-active-2", replacement_2)
    assert "cannot transition from 'SUPERSEDED' to 'SUPERSEDED'" in str(exc_info.value)


def test_duplicate_id_rejection(empty_ledger: ConstraintLedger, sample_user_constraint: Constraint):
    """Scenario 6: Duplicate ID rejection."""
    ledger = empty_ledger
    ledger.add(sample_user_constraint)

    # Attempt to add constraint with duplicate ID
    duplicate = Constraint(
        id="c-db-schema",
        name="different_name",
        description="Different description",
        strength=ConstraintStrength.SOFT,
        provenance=ConstraintProvenance(source=ConstraintSource.POLICY),
    )
    with pytest.raises(DuplicateConstraintError) as exc_info:
        ledger.add(duplicate)
    assert "already exists in ledger" in str(exc_info.value)

    # Attempt to supersede with a replacement that reuses the existing ID
    same_id_replacement = Constraint(
        id="c-db-schema",
        name="same_id_name",
        description="Same id description",
        strength=ConstraintStrength.SOFT,
        provenance=ConstraintProvenance(source=ConstraintSource.POLICY),
    )
    with pytest.raises(InvalidConstraintTransitionError):
        ledger.supersede("c-db-schema", same_id_replacement)

    # Attempt to supersede with a replacement ID that already belongs to another constraint
    another = Constraint(
        id="c-another",
        name="another_c",
        description="Another active constraint",
        strength=ConstraintStrength.SOFT,
        provenance=ConstraintProvenance(source=ConstraintSource.POLICY),
    )
    ledger.add(another)

    conflicting_replacement = Constraint(
        id="c-another",  # ID already taken
        name="conflicting",
        description="Conflicting replacement",
        strength=ConstraintStrength.SOFT,
        provenance=ConstraintProvenance(source=ConstraintSource.POLICY),
    )
    with pytest.raises(DuplicateConstraintError):
        ledger.supersede("c-db-schema", conflicting_replacement)


def test_serialization_and_deserialization_round_trip(empty_ledger: ConstraintLedger, sample_user_constraint: Constraint):
    """Scenario 7: Serialize ledger → reconstruct → compare semantic state."""
    ledger = empty_ledger
    ledger.add(sample_user_constraint)

    # Add agent assumption
    assumption = Constraint(
        id="c-assumption",
        name="assume_linux",
        description="Assume Linux environment",
        strength=ConstraintStrength.ASSUMPTION,
        provenance=ConstraintProvenance(
            source=ConstraintSource.AGENT_INFERENCE,
            source_text="Found POSIX paths",
            metadata={"inferred_from": "Dockerfile"},
        ),
    )
    ledger.add(assumption)

    # Add and revoke a constraint
    to_revoke = Constraint(
        id="c-revokable",
        name="temp_check",
        description="Temporary constraint",
        strength=ConstraintStrength.SOFT,
        provenance=ConstraintProvenance(source=ConstraintSource.POLICY),
    )
    ledger.add(to_revoke)
    ledger.revoke("c-revokable", reason="Expired policy")

    # Add and supersede a constraint
    to_supersede = Constraint(
        id="c-to-supersede",
        name="old_tool_policy",
        description="Use curl only",
        strength=ConstraintStrength.HARD,
        provenance=ConstraintProvenance(source=ConstraintSource.POLICY),
    )
    replacement = Constraint(
        id="c-superseder",
        name="new_tool_policy",
        description="Use httpx or curl",
        strength=ConstraintStrength.HARD,
        provenance=ConstraintProvenance(source=ConstraintSource.POLICY),
    )
    ledger.add(to_supersede)
    ledger.supersede("c-to-supersede", replacement)

    # 1. JSON string serialization round-trip
    json_repr = ledger.to_json(indent=2)
    reconstructed_from_json = ConstraintLedger.from_json(json_repr)

    assert reconstructed_from_json == ledger
    assert len(reconstructed_from_json) == len(ledger)
    assert len(reconstructed_from_json.list_active()) == len(ledger.list_active())
    assert [c.id for c in reconstructed_from_json.list_active()] == [c.id for c in ledger.list_active()]

    # Verify superseded history matches exactly
    orig_history = ledger.get_history("c-superseder")
    reconstructed_history = reconstructed_from_json.get_history("c-superseder")
    assert [c.id for c in reconstructed_history] == [c.id for c in orig_history]

    # 2. Dictionary serialization round-trip
    dict_repr = ledger.to_dict()
    reconstructed_from_dict = ConstraintLedger.from_dict(dict_repr)
    assert reconstructed_from_dict == ledger


def test_active_listing_excludes_revoked_and_superseded(empty_ledger: ConstraintLedger):
    """Scenario 8: Active listing excludes revoked/superseded entries."""
    ledger = empty_ledger

    c1 = Constraint(
        id="c-active-1",
        name="active_1",
        description="Active 1",
        strength=ConstraintStrength.HARD,
        provenance=ConstraintProvenance(source=ConstraintSource.USER),
    )
    c2 = Constraint(
        id="c-will-revoke",
        name="will_revoke",
        description="Will revoke",
        strength=ConstraintStrength.SOFT,
        provenance=ConstraintProvenance(source=ConstraintSource.POLICY),
    )
    c3 = Constraint(
        id="c-will-supersede",
        name="will_supersede",
        description="Will supersede",
        strength=ConstraintStrength.HARD,
        provenance=ConstraintProvenance(source=ConstraintSource.REPOSITORY),
    )
    c4 = Constraint(
        id="c-replacement",
        name="replacement",
        description="Replacement for c3",
        strength=ConstraintStrength.HARD,
        provenance=ConstraintProvenance(source=ConstraintSource.REPOSITORY),
    )

    ledger.add(c1)
    ledger.add(c2)
    ledger.add(c3)

    assert len(ledger.list_active()) == 3

    ledger.revoke("c-will-revoke")
    assert len(ledger.list_active()) == 2

    ledger.supersede("c-will-supersede", c4)
    active = ledger.list_active()
    assert len(active) == 2
    assert {c.id for c in active} == {"c-active-1", "c-replacement"}

    # list_all returns all 4 recorded entries
    assert len(ledger.list_all()) == 4
    assert {c.id for c in ledger.list_all()} == {"c-active-1", "c-will-revoke", "c-will-supersede", "c-replacement"}


def test_chain_of_supersessions_lineage(empty_ledger: ConstraintLedger):
    """Lineage correctly traces multi-hop supersessions (A -> B -> C)."""
    ledger = empty_ledger

    cA = Constraint(
        id="c-v1",
        name="v1",
        description="Version 1",
        strength=ConstraintStrength.HARD,
        provenance=ConstraintProvenance(source=ConstraintSource.USER),
    )
    cB = Constraint(
        id="c-v2",
        name="v2",
        description="Version 2",
        strength=ConstraintStrength.HARD,
        provenance=ConstraintProvenance(source=ConstraintSource.USER),
    )
    cC = Constraint(
        id="c-v3",
        name="v3",
        description="Version 3",
        strength=ConstraintStrength.HARD,
        provenance=ConstraintProvenance(source=ConstraintSource.USER),
    )

    ledger.add(cA)
    ledger.supersede("c-v1", cB)
    ledger.supersede("c-v2", cC)

    # Lineage accessed from root
    history_from_A = ledger.get_history("c-v1")
    assert [c.id for c in history_from_A] == ["c-v1", "c-v2", "c-v3"]

    # Lineage accessed from intermediate
    history_from_B = ledger.get_history("c-v2")
    assert [c.id for c in history_from_B] == ["c-v1", "c-v2", "c-v3"]

    # Lineage accessed from tip
    history_from_C = ledger.get_history("c-v3")
    assert [c.id for c in history_from_C] == ["c-v1", "c-v2", "c-v3"]


def test_not_found_errors(empty_ledger: ConstraintLedger):
    """Querying or operating on non-existent IDs raises ConstraintNotFoundError."""
    ledger = empty_ledger

    with pytest.raises(ConstraintNotFoundError):
        ledger.get("non-existent")

    with pytest.raises(ConstraintNotFoundError):
        ledger.revoke("non-existent")

    dummy = Constraint(
        id="c-dummy",
        name="dummy",
        description="Dummy",
        strength=ConstraintStrength.SOFT,
        provenance=ConstraintProvenance(source=ConstraintSource.USER),
    )
    with pytest.raises(ConstraintNotFoundError):
        ledger.supersede("non-existent", dummy)

    with pytest.raises(ConstraintNotFoundError):
        ledger.get_history("non-existent")


# --- Round 2 Blocker 2: Table-Driven Lifecycle Tests & Explicit Enforcement ---

def test_all_lifecycle_status_pairs_table_driven():
    """Round 2 Blocker 2 requirement: table-driven test for all 16 status transitions."""
    all_statuses = list(ConstraintStatus)
    assert len(all_statuses) == 4

    tested_count = 0
    for from_status, to_status in itertools.product(all_statuses, all_statuses):
        tested_count += 1
        is_allowed = to_status in ALLOWED_TRANSITIONS[from_status]

        if is_allowed:
            # Must succeed without error
            validate_transition(from_status, to_status, constraint_id="c-test")
        else:
            # Must explicitly fail with InvalidConstraintTransitionError
            with pytest.raises(InvalidConstraintTransitionError) as exc_info:
                validate_transition(from_status, to_status, constraint_id="c-test")
            assert f"cannot transition from '{from_status.value}' to '{to_status.value}'" in str(exc_info.value)

    assert tested_count == 16


def test_add_rejects_non_active_initial_states(empty_ledger: ConstraintLedger):
    """New constraints entering ledger must have status ACTIVE."""
    ledger = empty_ledger

    for bad_status in (ConstraintStatus.REVOKED, ConstraintStatus.SUPERSEDED, ConstraintStatus.CONFLICTED):
        bad_c = Constraint(
            id=f"c-{bad_status.value.lower()}",
            name=f"bad_{bad_status.value.lower()}",
            description="Testing non-active add rejection",
            strength=ConstraintStrength.SOFT,
            status=bad_status,
            provenance=ConstraintProvenance(source=ConstraintSource.POLICY),
        )
        with pytest.raises(InvalidConstraintTransitionError) as exc_info:
            ledger.add(bad_c)
        assert f"must enter ledger with status ACTIVE, got '{bad_status.value}'" in str(exc_info.value)


def test_supersede_rejects_non_active_replacement_states(empty_ledger: ConstraintLedger, sample_user_constraint: Constraint):
    """Replacement constraint must enter with status ACTIVE."""
    ledger = empty_ledger
    ledger.add(sample_user_constraint)

    for bad_status in (ConstraintStatus.REVOKED, ConstraintStatus.SUPERSEDED, ConstraintStatus.CONFLICTED):
        bad_replacement = Constraint(
            id=f"c-repl-{bad_status.value.lower()}",
            name=f"repl_{bad_status.value.lower()}",
            description="Testing non-active replacement rejection",
            strength=ConstraintStrength.SOFT,
            status=bad_status,
            provenance=ConstraintProvenance(source=ConstraintSource.POLICY),
        )
        with pytest.raises(InvalidConstraintTransitionError) as exc_info:
            ledger.supersede("c-db-schema", bad_replacement)
        assert f"must have status ACTIVE, got '{bad_status.value}'" in str(exc_info.value)


def test_conflicted_lifecycle_transitions(empty_ledger: ConstraintLedger):
    """Explicit test of CONFLICTED lifecycle progression rules:

    1. ACTIVE -> CONFLICTED (via mark_conflicted)
    2. CONFLICTED -> CONFLICTED is rejected (Round 2 Blocker 2 fix)
    3. CONFLICTED -> ACTIVE (via resolve_conflict)
    4. CONFLICTED -> REVOKED (via revoke to cancel conflicting requirement)
    5. CONFLICTED -> SUPERSEDED (via supersede to harmonize/replace conflicting requirement)
    """
    ledger = empty_ledger

    c1 = Constraint(
        id="c-port-80",
        name="port_80",
        description="Bind to port 80",
        strength=ConstraintStrength.HARD,
        provenance=ConstraintProvenance(source=ConstraintSource.USER),
    )
    c2 = Constraint(
        id="c-port-80-alt",
        name="port_80_alt",
        description="Bind other service to port 80",
        strength=ConstraintStrength.HARD,
        provenance=ConstraintProvenance(source=ConstraintSource.POLICY),
    )
    c3 = Constraint(
        id="c-peer-3",
        name="peer_3",
        description="Peer 3",
        strength=ConstraintStrength.HARD,
        provenance=ConstraintProvenance(source=ConstraintSource.POLICY),
    )
    ledger.add(c1)
    ledger.add(c2)
    ledger.add(c3)

    # 1. ACTIVE -> CONFLICTED
    conflicted = ledger.mark_conflicted("c-port-80", "c-port-80-alt", reason="Port collision")
    assert conflicted.status == ConstraintStatus.CONFLICTED
    assert conflicted.is_active is False
    assert conflicted.relations.conflicts_with == ("c-port-80-alt",)

    # 2. Round 2 Blocker 2: CONFLICTED -> CONFLICTED must be rejected!
    with pytest.raises(InvalidConstraintTransitionError) as exc_info:
        ledger.mark_conflicted("c-port-80", "c-peer-3", reason="Conflict again while conflicted")
    assert "cannot transition from 'CONFLICTED' to 'CONFLICTED'" in str(exc_info.value)

    # Cannot resolve conflict on an already active constraint
    with pytest.raises(InvalidConstraintTransitionError):
        ledger.resolve_conflict("c-peer-3")

    # 3. CONFLICTED -> ACTIVE (resolve_conflict)
    resolved = ledger.resolve_conflict("c-port-80", reason="Port 80 conflict cleared")
    assert resolved.status == ConstraintStatus.ACTIVE
    assert resolved.is_active is True
    assert resolved.relations.conflicts_with == ()
    assert resolved.relations.metadata["conflict_resolution"] == "Port 80 conflict cleared"

    # Re-mark as conflicted (ACTIVE -> CONFLICTED) to test CONFLICTED -> REVOKED
    ledger.mark_conflicted("c-port-80", "c-port-80-alt", reason="Conflict again")

    # 4. CONFLICTED -> REVOKED
    revoked = ledger.revoke("c-port-80", reason="Revoked to resolve port clash")
    assert revoked.status == ConstraintStatus.REVOKED
    assert revoked.is_terminal is True
    assert revoked.relations.revocation_reason == "Revoked to resolve port clash"

    # 5. CONFLICTED -> SUPERSEDED
    # Mark c2 as conflicted with active c3, then supersede c2
    ledger.mark_conflicted("c-port-80-alt", "c-peer-3", reason="Conflict on c2")
    assert ledger.get("c-port-80-alt").status == ConstraintStatus.CONFLICTED

    harmonized_replacement = Constraint(
        id="c-port-unified",
        name="port_unified",
        description="Use dynamic ports instead",
        strength=ConstraintStrength.HARD,
        provenance=ConstraintProvenance(source=ConstraintSource.USER),
    )
    superseded = ledger.supersede("c-port-80-alt", harmonized_replacement)
    assert superseded.id == "c-port-unified"
    assert superseded.status == ConstraintStatus.ACTIVE
    assert ledger.get("c-port-80-alt").status == ConstraintStatus.SUPERSEDED


def test_mark_conflicted_peer_precondition(empty_ledger: ConstraintLedger, sample_user_constraint: Constraint):
    """Round 2 Blocker 2: Conflicting peer named in conflicts_with must be ACTIVE."""
    ledger = empty_ledger
    ledger.add(sample_user_constraint)

    c_terminal = Constraint(
        id="c-term",
        name="term",
        description="term",
        strength=ConstraintStrength.SOFT,
        provenance=ConstraintProvenance(source=ConstraintSource.POLICY),
    )
    ledger.add(c_terminal)
    ledger.revoke("c-term")

    c_conf = Constraint(
        id="c-conf",
        name="conf",
        description="conf",
        strength=ConstraintStrength.SOFT,
        provenance=ConstraintProvenance(source=ConstraintSource.POLICY),
    )
    c_conf_peer = Constraint(
        id="c-conf-peer",
        name="conf_peer",
        description="conf_peer",
        strength=ConstraintStrength.SOFT,
        provenance=ConstraintProvenance(source=ConstraintSource.POLICY),
    )
    ledger.add(c_conf)
    ledger.add(c_conf_peer)
    ledger.mark_conflicted("c-conf", "c-conf-peer")

    # 1. Peer cannot be terminal (REVOKED)
    with pytest.raises(InvalidConstraintTransitionError) as exc_info:
        ledger.mark_conflicted("c-db-schema", "c-term")
    assert "must be in ACTIVE status, got 'REVOKED'" in str(exc_info.value)

    # 2. Peer cannot be CONFLICTED
    with pytest.raises(InvalidConstraintTransitionError) as exc_info:
        ledger.mark_conflicted("c-db-schema", "c-conf")
    assert "must be in ACTIVE status, got 'CONFLICTED'" in str(exc_info.value)

    # 3. Source cannot be terminal (REVOKED)
    with pytest.raises(InvalidConstraintTransitionError) as exc_info:
        ledger.mark_conflicted("c-term", "c-db-schema")
    assert "cannot transition from 'REVOKED' to 'CONFLICTED'" in str(exc_info.value)


# --- Snapshot Immutability Tests (Round 2 Blocker 1) ---

def test_snapshot_deep_immutability(empty_ledger: ConstraintLedger, sample_user_constraint: Constraint):
    """Snapshot collections are structurally immutable and reject |= and in-place tampering."""
    ledger = empty_ledger
    ledger.add(sample_user_constraint)

    snapshot = ledger.snapshot(metadata={"environment": "production"})

    # 1. constraints collection is a tuple
    assert isinstance(snapshot.constraints, tuple)
    with pytest.raises(AttributeError):
        snapshot.constraints.append(sample_user_constraint)  # type: ignore[attr-defined]

    # 2. metadata is a FrozenDict using composition
    assert isinstance(snapshot.metadata, FrozenDict)
    assert not isinstance(snapshot.metadata, dict)
    with pytest.raises(TypeError):
        snapshot.metadata["tamper"] = True  # type: ignore[index]
    with pytest.raises(TypeError):
        snapshot.metadata |= {"tamper": True}  # type: ignore[operator]
    with pytest.raises(TypeError):
        dict.__setitem__(snapshot.metadata, "tamper", True)  # type: ignore[arg-type]

    # 3. Mutating external metadata dict passed to snapshot has no effect
    raw_meta = {"version": "1.0"}
    snap2 = ledger.snapshot(metadata=raw_meta)
    raw_meta["version"] = "2.0"
    assert snap2.metadata["version"] == "1.0"


def test_ledger_initialization_with_iterable(sample_user_constraint: Constraint):
    """Ledger can be initialized with an iterable of constraints."""
    c2 = Constraint(
        id="c-2",
        name="name_2",
        description="Desc 2",
        strength=ConstraintStrength.SOFT,
        provenance=ConstraintProvenance(source=ConstraintSource.POLICY),
    )
    ledger = ConstraintLedger([sample_user_constraint, c2])
    assert len(ledger) == 2
    assert "c-db-schema" in ledger
    assert "c-2" in ledger


def test_corrupted_snapshot_with_duplicate_id_rejected(sample_user_constraint: Constraint):
    """Snapshot deserialization rejects duplicate IDs with DuplicateConstraintError."""
    dup_snapshot = LedgerSnapshot(
        constraints=[sample_user_constraint, sample_user_constraint],
    )
    with pytest.raises(DuplicateConstraintError) as exc_info:
        ConstraintLedger.from_snapshot(dup_snapshot)
    assert "duplicate constraint id" in str(exc_info.value)


def test_top_level_package_exports():
    """Verify package imports successfully from root agentcontract package."""
    from agentcontract import (
        Constraint as RootConstraint,
        ConstraintLedger as RootConstraintLedger,
        ConstraintProvenance as RootProvenance,
        ConstraintScope as RootScope,
        ConstraintSource as RootSource,
        ConstraintStatus as RootStatus,
        ConstraintStrength as RootStrength,
        __version__,
    )

    assert __version__ == "0.1.0"
    assert RootConstraint is Constraint
    assert RootConstraintLedger is ConstraintLedger
    assert RootProvenance is ConstraintProvenance
    assert RootScope is ConstraintScope
    assert RootSource is ConstraintSource
    assert RootStatus is ConstraintStatus
    assert RootStrength is ConstraintStrength
