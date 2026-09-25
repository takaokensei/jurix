from unittest.mock import Mock

import requests
import pytest

from src.llm_engine.ollama_service import OllamaService


def test_streaming_error_does_not_leak_internal_exception():
    service = OllamaService()
    service.session = Mock()
    service.session.post.side_effect = requests.ConnectionError(
        'HTTPConnectionPool(host="10.20.30.40", port=11434): connection refused'
    )

    with pytest.raises(RuntimeError, match='Erro ao gerar resposta') as exc:
        list(service.stream_text('teste', model='llama3'))
    assert '10.20.30.40' not in str(exc.value)
    assert '11434' not in str(exc.value)
