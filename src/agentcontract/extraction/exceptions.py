"""Domain exceptions for structured requirement and claim extraction."""


class ExtractionError(Exception):
    """Base exception for all extraction failures."""

    pass


class ExtractionValidationError(ExtractionError):
    """Raised when extracted candidate data fails domain validation or violates invariants."""

    pass


class ClientExtractionError(ExtractionError):
    """Raised when the structured extraction client fails or returns invalid non-mapping responses."""

    pass
