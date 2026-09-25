"""Compatibility facade for ingestion tasks."""

from .tasks_legacy import generate_embedding_task

__all__ = ["generate_embedding_task"]
