"""Deterministic evidence graph indexing claims, evidence references, and relations."""

from collections.abc import Iterable
from agentcontract.evidence.exceptions import ClaimNotFoundError
from agentcontract.evidence.models import Claim, ClaimEvaluation, EvidenceRef
from agentcontract.trace.models import TraceEvent, TracePointer
from agentcontract.trace.store import TraceStore


class EvidenceGraph:
    """An index linking claims to supporting/contradicting evidence and vice-versa.

    Maintains bidirectional relationships:
    - Claim -> Supporting / Contradicting Evidence
    - Evidence (event_id, trace_id) -> Claims citing it
    - Resolves TracePointer references via TraceStore
    """

    def __init__(self, evaluations: Iterable[ClaimEvaluation] | None = None) -> None:
        self._evaluations: dict[str, ClaimEvaluation] = {}
        self._claim_order: list[str] = []
        self._event_to_claims: dict[str, list[str]] = {}
        self._trace_and_event_to_claims: dict[tuple[str, str], list[str]] = {}

        if evaluations is not None:
            for evaluation in evaluations:
                self.add_evaluation(evaluation)

    def add_evaluation(self, evaluation: ClaimEvaluation) -> None:
        """Register or update an evaluation in the evidence graph."""
        cid = evaluation.claim.claim_id
        if cid not in self._evaluations:
            self._claim_order.append(cid)
        self._evaluations[cid] = evaluation

        # Index reverse lookups for each referenced evidence event
        for ref in evaluation.evidence_refs:
            # By event_id
            c_list = self._event_to_claims.setdefault(ref.event_id, [])
            if cid not in c_list:
                c_list.append(cid)

            # By (trace_id, event_id)
            te_key = (ref.trace_id, ref.event_id)
            te_list = self._trace_and_event_to_claims.setdefault(te_key, [])
            if cid not in te_list:
                te_list.append(cid)

    def get_evaluation(self, claim_id: str) -> ClaimEvaluation:
        """Retrieve evaluation for a claim, or raise ClaimNotFoundError."""
        if claim_id not in self._evaluations:
            raise ClaimNotFoundError(f"Claim with id '{claim_id}' not found in evidence graph.")
        return self._evaluations[claim_id]

    def get_evaluation_optional(self, claim_id: str) -> ClaimEvaluation | None:
        """Retrieve evaluation for a claim, or return None if not present."""
        return self._evaluations.get(claim_id)

    def get_supporting_evidence(self, claim_id: str) -> tuple[EvidenceRef, ...]:
        """Return all evidence references supporting the specified claim."""
        evaluation = self.get_evaluation_optional(claim_id)
        if evaluation is None:
            return ()
        return evaluation.supporting_evidence

    def get_contradicting_evidence(self, claim_id: str) -> tuple[EvidenceRef, ...]:
        """Return all evidence references contradicting the specified claim."""
        evaluation = self.get_evaluation_optional(claim_id)
        if evaluation is None:
            return ()
        return evaluation.contradicting_evidence

    def get_claims_citing_evidence(
        self,
        event_id: str,
        trace_id: str | None = None,
    ) -> tuple[str, ...]:
        """Return all claim IDs citing the specified evidence event in deterministic order."""
        if trace_id is not None:
            return tuple(self._trace_and_event_to_claims.get((trace_id, event_id), []))
        return tuple(self._event_to_claims.get(event_id, []))

    def resolve_pointer(self, pointer: TracePointer, store: TraceStore) -> TraceEvent:
        """Resolve a TracePointer to its referenced TraceEvent via the provided TraceStore."""
        return store.resolve_pointer(pointer)

    def resolve_pointer_optional(
        self,
        pointer: TracePointer,
        store: TraceStore,
    ) -> TraceEvent | None:
        """Resolve a TracePointer to its referenced TraceEvent, or return None if not found or invalid."""
        try:
            return store.resolve_pointer(pointer)
        except Exception:
            return None

    def all_evaluations(self) -> tuple[ClaimEvaluation, ...]:
        """Return all evaluations currently registered in deterministic encounter order."""
        return tuple(self._evaluations[cid] for cid in self._claim_order)

    def all_claims(self) -> tuple[Claim, ...]:
        """Return all claims currently evaluated in deterministic encounter order."""
        return tuple(self._evaluations[cid].claim for cid in self._claim_order)

    def __len__(self) -> int:
        return len(self._evaluations)

    def __contains__(self, claim_id: str) -> bool:
        return claim_id in self._evaluations
