"""Compatibility facade for ingestion tasks."""

from .tasks_legacy import segment_text_task

__all__ = ["segment_text_task"]
