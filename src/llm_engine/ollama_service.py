"""
Ollama Service for LLM integration.

This module provides integration with Ollama for:
- Embedding generation (with /api/embed and /api/embeddings fallback)
- Text generation/completion (batch and streaming)
- Connection pooling via requests.Session

Ollama runs on the host machine and is accessible via host.docker.internal:11434
"""

import json
import logging
from collections.abc import Generator
from typing import Any

import requests
from django.conf import settings
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class OllamaService:
    """
    Service class for interacting with Ollama API.

    Provides methods for embedding generation and text generation
    using Ollama models running on the host machine with persistent
    connection pooling.
    """

    def __init__(self, base_url: str | None = None, model: str = "nomic-embed-text"):
        """
        Initialize Ollama service with connection pooling.

        Args:
            base_url: Base URL for Ollama API (defaults to settings.OLLAMA_BASE_URL)
            model: Default model to use for operations
        """
        self.base_url = (base_url or getattr(
            settings,
            'OLLAMA_BASE_URL',
            'http://host.docker.internal:11434'
        )).rstrip('/')
        self.model = model
        self.timeout = 60  # Seconds

        # Connection pooling
        self.session = requests.Session()
        retries = Retry(
            total=2,
            backoff_factor=0.3,
            status_forcelist=[502, 503, 504],
            raise_on_status=False
        )
        adapter = HTTPAdapter(pool_connections=10, pool_maxsize=20, max_retries=retries)
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)

    def generate_embedding(self, text: str, model: str | None = None) -> list[float] | None:
        """
        Generate embedding vector for given text using Ollama.
        Prefers the modern /api/embed endpoint with fallback to legacy /api/embeddings.

        Args:
            text: Input text to embed
            model: Model to use (defaults to self.model)

        Returns:
            List of floats representing the embedding vector, or None if failed
        """
        model = model or self.model

        if not text or not text.strip():
            logger.warning("Empty text provided for embedding generation")
            return None

        clean_text = text.strip()

        # 1. Attempt modern /api/embed endpoint (Ollama >= 0.1.30)
        try:
            embed_url = f"{self.base_url}/api/embed"
            payload = {
                "model": model,
                "input": clean_text
            }
            response = self.session.post(embed_url, json=payload, timeout=self.timeout)
            if response.status_code == 200:
                data = response.json()
                embeddings = data.get('embeddings', [])
                if embeddings and len(embeddings) > 0:
                    return embeddings[0]
        except Exception as e:
            logger.debug(f"Attempt via /api/embed failed, trying fallback: {e}")

        # 2. Fallback to /api/embeddings endpoint
        try:
            legacy_url = f"{self.base_url}/api/embeddings"
            payload = {
                "model": model,
                "prompt": clean_text
            }
            response = self.session.post(legacy_url, json=payload, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()
            embedding = data.get('embedding')
            if embedding:
                return embedding
            logger.error(f"No embedding in response: {data}")
            return None
        except Exception as e:
            logger.error(f"Error generating embedding with model {model}: {e}")
            return None

    def generate_text(
        self,
        prompt: str,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 500
    ) -> str | None:
        """
        Generate text completion synchronously using Ollama.

        Args:
            prompt: Input prompt
            model: Model to use (defaults to llama3)
            temperature: Sampling temperature (0-1)
            max_tokens: Maximum tokens to generate

        Returns:
            Generated text, or None if failed
        """
        model = model or "llama3"
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens
            }
        }

        try:
            response = self.session.post(
                url,
                json=payload,
                timeout=self.timeout * 2
            )
            response.raise_for_status()
            data = response.json()
            return data.get('response', '')
        except Exception as e:
            logger.error(f"Error generating text: {e}", exc_info=True)
            return None

    def stream_text(
        self,
        prompt: str,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 500
    ) -> Generator[str, None, None]:
        """
        Stream text completion from Ollama yielding chunks as they arrive.

        Args:
            prompt: Input prompt
            model: Model to use (defaults to llama3)
            temperature: Sampling temperature (0-1)
            max_tokens: Maximum tokens to generate

        Yields:
            Token/text chunks as strings
        """
        model = model or "llama3"
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens
            }
        }

        response = None
        completed = False
        try:
            response = self.session.post(
                url,
                json=payload,
                stream=True,
                timeout=self.timeout * 2
            )
            response.raise_for_status()

            for line in response.iter_lines(decode_unicode=True):
                if line:
                    try:
                        data = json.loads(line)
                        if data.get('error'):
                            raise RuntimeError('Ollama returned an error')
                        chunk = data.get('response', '')
                        if chunk:
                            yield chunk
                        if data.get('done', False):
                            completed = True
                            break
                    except json.JSONDecodeError:
                        raise RuntimeError('Invalid Ollama stream') from None
            if not completed:
                raise RuntimeError('Incomplete Ollama stream')
        except Exception as e:
            logger.error(f"Error streaming text from Ollama: {e}", exc_info=True)
            raise RuntimeError('Erro ao gerar resposta. Tente novamente.') from None
        finally:
            if response is not None:
                response.close()

    def check_health(self) -> bool:
        """
        Check if Ollama service is accessible.

        Returns:
            True if service is healthy, False otherwise
        """
        try:
            url = f"{self.base_url}/api/tags"
            response = self.session.get(url, timeout=5)
            response.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Ollama service health check failed: {e}")
            return False

    def list_models(self) -> list[dict[str, Any]]:
        """
        List available models in Ollama.

        Returns:
            List of model dictionaries
        """
        try:
            url = f"{self.base_url}/api/tags"
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            return data.get('models', [])
        except Exception as e:
            logger.error(f"Error listing models: {e}")
            return []
