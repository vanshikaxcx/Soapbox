"""Opaque identifier dependency shared by the baseline transport."""

from typing import Protocol


class IdGenerator(Protocol):
    """Generate a new opaque identifier without exposing an ID format."""

    def new_id(self) -> str:
        """Return a non-empty opaque identifier."""
