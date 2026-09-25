from unittest.mock import Mock

from src.apps.ingestion.management.commands.bulk_embed_batch import generate_embeddings_batch


def test_generate_embeddings_batch_uses_single_ollama_request():
    ollama = Mock()
    response = Mock(status_code=200)
    response.json.return_value = {
        "embeddings": [[0.1] * 768, [0.2] * 768],
    }
    ollama.session.post.return_value = response
    ollama.base_url = "http://ollama:11434"
    ollama.timeout = 30

    result = generate_embeddings_batch(
        ollama, ["primeiro texto", "segundo texto"], "nomic-embed-text"
    )

    assert len(result) == 2
    ollama.session.post.assert_called_once_with(
        "http://ollama:11434/api/embed",
        json={
            "model": "nomic-embed-text",
            "input": ["primeiro texto", "segundo texto"],
        },
        timeout=30,
    )


def test_generate_embeddings_batch_falls_back_for_legacy_ollama():
    ollama = Mock()
    ollama.session.post.return_value = Mock(status_code=404)
    ollama.generate_embedding.side_effect = [[0.1] * 768, [0.2] * 768]
    ollama.base_url = "http://ollama:11434"
    ollama.timeout = 30

    result = generate_embeddings_batch(
        ollama, ["primeiro texto", "segundo texto"], "nomic-embed-text"
    )

    assert len(result) == 2
    assert ollama.generate_embedding.call_count == 2
