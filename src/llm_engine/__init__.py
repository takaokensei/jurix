"""
LLM Engine module for Jurix.

Provides integration with Ollama for embeddings and text generation.
"""

from .ollama_service import OllamaService

__all__ = ['OllamaService']

