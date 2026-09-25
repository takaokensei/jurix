"""Compatibility facade for ingestion tasks."""

from .tasks_legacy import ocr_pdf_task

__all__ = ["ocr_pdf_task"]
