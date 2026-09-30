from unittest.mock import MagicMock, patch

import pytest

from src.processing.llm_provider import stream_text, validate_provider_config


def test_public_provider_uses_fixed_endpoint_and_keeps_api_key_out_of_url():
    config = validate_provider_config({"provider": "openai", "model": "gpt-4o-mini", "api_key": "secret"})
    assert config["endpoint"] == "https://api.openai.com/v1"
    response = MagicMock()
    response.__enter__.return_value = response
    response.iter_lines.return_value = [b'data: {"choices":[{"delta":{"content":"Resposta"}}]}', b"data: [DONE]"]
    with patch("src.processing.llm_provider.requests.post", return_value=response) as post:
        assert list(stream_text("prompt", config, temperature=0.3, max_tokens=20)) == ["Resposta"]
    assert post.call_args.args[0] == "https://api.openai.com/v1/chat/completions"
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer secret"
    assert "secret" not in post.call_args.args[0]


def test_provider_validation_rejects_unlisted_public_hosts_and_empty_keys():
    with pytest.raises(ValueError):
        validate_provider_config({"provider": "compatible", "model": "m", "api_key": "x", "endpoint": "https://example.com/v1"})
    with pytest.raises(ValueError):
        validate_provider_config({"provider": "groq", "model": "m", "api_key": ""})
    normalized = validate_provider_config({"provider": "compatible", "model": "m", "api_key": "x", "endpoint": "http://localhost:4000/v1/chat/completions"})
    assert normalized["endpoint"] == "http://localhost:4000/v1"
