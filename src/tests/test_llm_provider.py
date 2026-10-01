from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

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
    with override_settings(LLM_ALLOW_LOCAL_COMPATIBLE_ENDPOINTS=True):
        normalized = validate_provider_config({"provider": "compatible", "model": "m", "api_key": "x", "endpoint": "http://localhost:4000/v1/chat/completions"})
    assert normalized["endpoint"] == "http://localhost:4000/v1"


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://localhost:4001/v1",
        "http://localhost.evil.test/v1",
        "http://127.0.0.1:4000/v1",
        "https://api.example.test/v1/",
    ],
)
def test_production_compatible_endpoint_requires_exact_allowlist(endpoint):
    with override_settings(
        LLM_ALLOW_LOCAL_COMPATIBLE_ENDPOINTS=False,
        LLM_COMPATIBLE_ENDPOINT_ALLOWLIST=("https://api.example.test/v1",),
    ):
        if endpoint == "https://api.example.test/v1/":
            config = validate_provider_config(
                {"provider": "compatible", "model": "m", "api_key": "x", "endpoint": endpoint}
            )
            assert config["endpoint"] == "https://api.example.test/v1"
        else:
            with pytest.raises(ValueError):
                validate_provider_config(
                    {"provider": "compatible", "model": "m", "api_key": "x", "endpoint": endpoint}
                )


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://user:pass@localhost:4000/v1",
        "http://localhost:4000/v1?next=https://example.test",
        "http://localhost:4000/v1#fragment",
        "http://localhost:4000/../admin",
        "http://localhost:bad/v1",
    ],
)
def test_ambiguous_compatible_urls_are_rejected(endpoint):
    with override_settings(LLM_ALLOW_LOCAL_COMPATIBLE_ENDPOINTS=True):
        with pytest.raises(ValueError):
            validate_provider_config(
                {"provider": "compatible", "model": "m", "api_key": "x", "endpoint": endpoint}
            )


def test_compatible_endpoint_is_revalidated_immediately_before_network_request():
    config = {
        "provider": "compatible",
        "model": "m",
        "api_key": "x",
        "endpoint": "http://localhost:4000/v1",
    }
    with override_settings(LLM_ALLOW_LOCAL_COMPATIBLE_ENDPOINTS=False):
        with patch("src.processing.llm_provider.requests.post") as post:
            with pytest.raises(ValueError):
                list(stream_text("prompt", config, temperature=0.3, max_tokens=20))
    post.assert_not_called()
