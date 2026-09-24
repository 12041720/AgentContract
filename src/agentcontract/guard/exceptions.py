"""Exceptions for SpecGuard action validation."""


class GuardError(Exception):
    """Base exception for all SpecGuard errors."""


class GuardValidationError(GuardError, ValueError):
    """Raised when an action or guard input violates domain invariants."""
