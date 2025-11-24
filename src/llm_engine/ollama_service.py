"""
Ollama Service for LLM integration.

This module provides integration with Ollama for:
- Embedding generation
- Text generation/completion
- Named entity recognition

Ollama runs on the host machine and is accessible via host.docker.internal:11434
"""

import logging
import requests
from typing import List, Dict, Any, Optional
from django.conf import settings

logger = logging.getLogger(__name__)


class OllamaService:
    """
    Service class for interacting with Ollama API.
    
    Provides methods for embedding generation and text generation
    using Ollama models running on the host machine.
    """
    
    def __init__(self, base_url: Optional[str] = None, model: str = "nomic-embed-text"):
        """
        Initialize Ollama service.
        
        Args:
            base_url: Base URL for Ollama API (defaults to settings.OLLAMA_BASE_URL)
            model: Default model to use for operations
        """
        self.base_url = base_url or getattr(
            settings, 
            'OLLAMA_BASE_URL', 
            'http://host.docker.internal:11434'
        )
        self.model = model
        self.timeout = 60  # Seconds
        
    def generate_embedding(self, text: str, model: Optional[str] = None) -> Optional[List[float]]:
        """
        Generate embedding vector for given text using Ollama.
        
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
        
        url = f"{self.base_url}/api/embeddings"
        payload = {
            "model": model,
            "prompt": text.strip()
        }
        
        try:
            logger.debug(f"Generating embedding for text of length {len(text)} using model {model}")
            
            response = requests.post(
                url,
                json=payload,
                timeout=self.timeout
            )
            response.raise_for_status()
            
            data = response.json()
            embedding = data.get('embedding')
            
            if embedding:
                logger.debug(f"Successfully generated embedding of dimension {len(embedding)}")
                return embedding
            else:
                logger.error(f"No embedding in response: {data}")
                return None
                
        except requests.exceptions.Timeout:
            logger.error(f"Timeout while generating embedding (model: {model})")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error while generating embedding: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error generating embedding: {e}", exc_info=True)
            return None
    
    def generate_text(
        self, 
        prompt: str, 
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 500
    ) -> Optional[str]:
        """
        Generate text completion using Ollama.
        
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
            logger.debug(f"Generating text with model {model}")
            
            response = requests.post(
                url,
                json=payload,
                timeout=self.timeout * 2  # Text generation can take longer
            )
            response.raise_for_status()
            
            data = response.json()
            generated_text = data.get('response', '')
            
            logger.debug(f"Successfully generated {len(generated_text)} characters")
            return generated_text
                
        except requests.exceptions.Timeout:
            logger.error(f"Timeout while generating text (model: {model})")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error while generating text: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error generating text: {e}", exc_info=True)
            return None
    
    def check_health(self) -> bool:
        """
        Check if Ollama service is accessible.
        
        Returns:
            True if service is healthy, False otherwise
        """
        try:
            url = f"{self.base_url}/api/tags"
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            
            logger.info("Ollama service is healthy")
            return True
        except Exception as e:
            logger.error(f"Ollama service health check failed: {e}")
            return False
    
    def list_models(self) -> List[Dict[str, Any]]:
        """
        List available models in Ollama.
        
        Returns:
            List of model dictionaries
        """
        try:
            url = f"{self.base_url}/api/tags"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            models = data.get('models', [])
            
            logger.info(f"Found {len(models)} models in Ollama")
            return models
        except Exception as e:
            logger.error(f"Error listing models: {e}")
            return []

