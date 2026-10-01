import json
from unittest.mock import patch

from django.test import Client


def test_json_answer_refuses_historical_wording_without_a_materialized_version():
    with patch("src.apps.legislation.api_search.RAGService.answer_question") as answer:
        response = Client().post(
            "/api/v1/search/answer/",
            data=json.dumps({"question": "Art. 1º em 2020?", "as_of": "2020-01-01"}),
            content_type="application/json",
        )

    assert response.status_code == 409
    assert response.json()["code"] == "historical_version_unavailable"
    assert response.json()["metadata"]["historical_version_available"] is False
    assert response.json()["sources"] == []
    answer.assert_not_called()


def test_sse_answer_explains_historical_version_gap_without_calling_the_llm():
    with patch("src.apps.legislation.api_search.RAGService.stream_answer_question") as stream:
        response = Client().post(
            "/api/v1/search/answer/stream/",
            data=json.dumps({"question": "Art. 1º em 2020?", "as_of": "2020-01-01"}),
            content_type="application/json",
        )
        body = b"".join(response.streaming_content).decode()
        events = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]

    assert response.status_code == 200
    assert '"reason_code": "historical_version_unavailable"' in body
    assert '"historical_version_available": false' in body
    done = next(event for event in events if event.get("type") == "done")
    assert "Não posso confirmar qual redação estava vigente" in done["answer"]
    assert done["sources"] == []
    stream.assert_not_called()
