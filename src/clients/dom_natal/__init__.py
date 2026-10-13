"""Read-only client for the official Natal Municipal Gazette portal."""

from .client import DomNatalClient, DomNatalEdition, DomNatalError

__all__ = ["DomNatalClient", "DomNatalEdition", "DomNatalError"]
