"""Compatibility facade for ingestion tasks."""

from .tasks_legacy import cleanup_chat_attachments, extract_entities_task

__all__ = ["cleanup_chat_attachments", "extract_entities_task"]
