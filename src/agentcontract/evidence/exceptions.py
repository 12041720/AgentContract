"""Exceptions for the evidence and claim verification subsystem."""


class EvidenceError(Exception):
    """Base exception for all evidence and verification errors."""


class EvidenceValidationError(EvidenceError, ValueError):
    """Raised when claim or evidence models violate domain invariants."""


class ClaimNotFoundError(EvidenceError, KeyError):
    """Raised when a requested claim cannot be located in the evidence graph."""
