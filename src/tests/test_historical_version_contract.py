import json
from unittest.mock import patch

import pytest
from django.test import Client, override_settings


def test_json_answer_delegates_historical_availability_to_temporal_retrieval():
    expected = {
        "answer": "Em 2020, o artigo previa dez dias [[1]].",
        "sources": [{"norma_ref": "Lei nº 9001/2020", "dispositivo_ref": "Art. 5º", "text": "O prazo é de dez dias."}],
        "confidence": 0.8,
        "grounded": True,
        "grounding": {"grounded": True, "claims": []},
        "reason_code": None,
    }
    with patch("src.apps.legislation.api_search.RAGService"), patch(
        "src.apps.legislation.api_views.RAGService"
    ) as service_class:
        service_class.return_value.answer_question.return_value = expected
        response = Client().post(
            "/api/v1/search/answer/",
            data=json.dumps({"question": "Qual era o prazo do Art. 5º da Lei Ordinária nº 9001/2020?", "as_of": "2021-02-28", "norma_status": "all"}),
            content_type="application/json",
        )

    assert response.status_code == 200
    assert response.json()["answer"] == expected["answer"]
    assert response.json()["sources"]
    options = service_class.return_value.answer_question.call_args.kwargs["options"]
    assert options.temporal_scope.as_of.isoformat() == "2021-02-28"
    assert options.norma_status == "all"


def test_sse_answer_passes_historical_scope_to_temporal_retrieval():
    source = {"norma_ref": "Lei nº 9001/2020", "dispositivo_ref": "Art. 5º", "text": "O prazo é de dez dias."}
    events = [
        {"event": "sources", "sources": [source]},
        {"event": "chunk", "text": "Em 2020, o prazo era de dez dias [[1]]."},
        {"event": "done", "answer": "Em 2020, o prazo era de dez dias [[1]].", "sources": [source], "grounded": True, "grounding": {"grounded": True, "claims": []}},
    ]
    with patch("src.apps.legislation.api_search.RAGService"), patch(
        "src.apps.legislation.api_views.RAGService"
    ) as service_class:
        service_class.return_value.stream_answer_question.return_value = iter(events)
        response = Client().post(
            "/api/v1/search/answer/stream/",
            data=json.dumps({"question": "Qual era o prazo do Art. 5º da Lei Ordinária nº 9001/2020?", "as_of": "2021-02-28", "norma_status": "all"}),
            content_type="application/json",
        )
        body = b"".join(response.streaming_content).decode()
        events = [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]

    assert response.status_code == 200
    assert any(event.get("type") == "sources" and event["sources"] for event in events)
    done = next(event for event in events if event.get("type") == "done")
    assert done["grounded"] is True
    assert done["contract"]["sources"]
    options = service_class.return_value.stream_answer_question.call_args.kwargs["options"]
    assert options.temporal_scope.as_of.isoformat() == "2021-02-28"
    assert options.norma_status == "all"


@pytest.mark.parametrize(
    "date_filter",
    [
        {"as_of": "2000-01-01"},
        {"published_from": "2000-01-01"},
        {"published_to": "2000-01-01"},
    ],
)
@override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
def test_archive_sse_abstains_when_temporal_filter_has_no_reviewed_versions(date_filter):
    with patch("src.apps.legislation.api_search.RAGService") as service_class:
        response = Client(REMOTE_ADDR="192.0.2.101").post(
            "/api/v1/search/answer/stream/",
            data=json.dumps({
                "question": "O que previa o art. 5º da Lei Complementar nº 120/2010?",
                "qa_archive_corpus": True,
                **date_filter,
            }),
            content_type="application/json",
        )
        events = [
            json.loads(line.removeprefix("data: "))
            for line in b"".join(response.streaming_content).decode().splitlines()
            if line.startswith("data: ")
        ]

    assert response.status_code == 200
    assert any(
        event.get("type") == "status" and event.get("status") == "insufficient_evidence"
        for event in events
    )
    source_event = next(event for event in events if event.get("type") == "sources")
    done_event = next(event for event in events if event.get("type") == "done")
    assert source_event["sources"] == []
    assert done_event["grounded"] is False
    assert done_event["reason_code"] == "historical_evidence_unavailable"
    assert done_event["sources"] == []
    assert "redação atual" in done_event["answer"]
    service_class.return_value.answer_question.assert_not_called()
    service_class.return_value.stream_answer_question.assert_not_called()
