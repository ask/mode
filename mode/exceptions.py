"""Custom exceptions."""

__all__ = ["MaxRestartsExceeded"]


class MaxRestartsExceeded(Exception):
    """Supervisor found restarting service too frequently."""
