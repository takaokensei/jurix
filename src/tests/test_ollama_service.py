from unittest.mock import Mock

import pytest
import requests
from django.test import override_settings

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


@override_settings(OLLAMA_MODEL='qwen2.5:7b')
def test_generate_text_uses_configured_default_model():
    service = OllamaService()
    service.session = Mock()
    response = Mock()
    response.json.return_value = {'response': 'ok'}
    service.session.post.return_value = response

    assert service.generate_text('teste') == 'ok'

    payload = service.session.post.call_args.kwargs['json']
    assert payload['model'] == 'qwen2.5:7b'


@override_settings(OLLAMA_MODEL='qwen2.5:7b')
def test_stream_text_uses_configured_default_model():
    service = OllamaService()
    service.session = Mock()
    response = Mock()
    response.iter_lines.return_value = [
        b'{"response":"ok","done":true}'
    ]
    service.session.post.return_value = response

    assert list(service.stream_text('teste')) == ['ok']

    payload = service.session.post.call_args.kwargs['json']
    assert payload['model'] == 'qwen2.5:7b'
