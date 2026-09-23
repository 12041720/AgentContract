"""Exceptions for constraint domain models and the constraint ledger."""


class ConstraintError(Exception):
    """Base exception for all constraint domain and ledger errors."""


class ConstraintNotFoundError(ConstraintError):
    """Raised when a requested constraint does not exist in the ledger."""


class DuplicateConstraintError(ConstraintError):
    """Raised when attempting to add a constraint with an identifier that already exists."""


class InvalidConstraintTransitionError(ConstraintError):
    """Raised when an illegal lifecycle transition is attempted on a constraint."""


class ConstraintValidationError(ConstraintError, ValueError):
    """Raised when constraint data or attributes violate domain invariants."""
