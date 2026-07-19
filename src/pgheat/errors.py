"""Domain errors surfaced by the pgheat command-line interface."""


class PgheatError(Exception):
    """Base class for actionable pgheat errors."""


class ConfigurationError(PgheatError):
    """Raised when command-line or source configuration is invalid."""


class CollectionError(PgheatError):
    """Raised when PostgreSQL statistics cannot be collected safely."""


class StoreError(PgheatError):
    """Raised when persisted samples are missing or inconsistent."""
