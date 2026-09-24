"""SpecGuard runtime validation engine, models, and decision primitives."""

from agentcontract.constraints.models import RuleEffect
from agentcontract.guard.engine import SpecGuard, match_scope
from agentcontract.guard.exceptions import GuardError, GuardValidationError
from agentcontract.guard.models import (
    Action,
    ActionKind,
    ActionObservation,
    DecisionKind,
    GuardDecision,
)

__all__ = [
    "Action",
    "ActionKind",
    "ActionObservation",
    "DecisionKind",
    "GuardDecision",
    "GuardError",
    "GuardValidationError",
    "RuleEffect",
    "SpecGuard",
    "match_scope",
]
