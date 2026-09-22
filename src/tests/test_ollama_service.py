from unittest.mock import Mock

import requests

from src.llm_engine.ollama_service import OllamaService


def test_streaming_error_does_not_leak_internal_exception():
    service = OllamaService()
    service.session = Mock()
    service.session.post.side_effect = requests.ConnectionError(
        'HTTPConnectionPool(host="10.20.30.40", port=11434): connection refused'
    )

    chunks = list(service.stream_text('teste', model='llama3'))

    assert chunks == ['\n[Erro ao gerar resposta. Tente novamente.]']
    assert '10.20.30.40' not in chunks[0]
    assert '11434' not in chunks[0]
