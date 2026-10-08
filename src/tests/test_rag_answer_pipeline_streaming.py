from src.processing.rag_answer_pipeline import (
    forward_grounded_generation,
    stream_grounded_generation,
)


def _grounded_validation(answer):
    supported = "afirmação sem suporte" not in answer.casefold()
    return {
        "answer": answer,
        "grounded": supported,
        "source_only": supported,
        "grounding": {
            "grounded": supported,
            "score": 1.0 if supported else 0.0,
            "claims": [],
            "failed_claims": [] if supported else ["unsupported"],
        },
    }


def test_streams_a_complete_validated_sentence_before_requesting_more_model_text():
    state = {"requested_second_chunk": False, "closed": False}

    def provider(_prompt):
        try:
            yield "O prazo é de dez dias. [[1]] "
            state["requested_second_chunk"] = True
            yield "Afirmação sem suporte. [[2]]"
        finally:
            state["closed"] = True

    events = stream_grounded_generation(
        "prompt", stream_attempt=provider, validate_attempt=_grounded_validation
    )

    first = next(events)
    assert first == {
        "event": "chunk",
        "chunk": "O prazo é de dez dias. [[1]]",
        "provisional": False,
    }
    assert state["requested_second_chunk"] is False

    visible = first["chunk"]
    while True:
        try:
            event = next(events)
        except StopIteration as completed:
            result = completed.value
            break
        if event.get("event") == "chunk":
            visible += event["chunk"]

    assert state == {"requested_second_chunk": True, "closed": True}
    assert result["partial"] is True
    assert result["answer"] == visible
    assert "Afirmação sem suporte" not in visible
    assert "A resposta foi limitada ao que as fontes consultadas permitem confirmar." in visible
    assert result["validated_prefix"] == "O prazo é de dez dias. [[1]]"


def test_partial_generation_exposes_only_the_already_validated_prefix_separately():
    def provider(_prompt):
        yield "O programa foi instituído. [[1]] "
        yield "Uma afirmação sem suporte. [[2]]"

    events = stream_grounded_generation(
        "prompt", stream_attempt=provider, validate_attempt=_grounded_validation
    )
    while True:
        try:
            next(events)
        except StopIteration as completed:
            result = completed.value
            break

    assert result["partial"] is True
    assert result["validated_prefix"] == "O programa foi instituído. [[1]]"
    assert result["answer"].startswith(result["validated_prefix"])
    assert "Uma afirmação sem suporte" not in result["validated_prefix"]
    assert result["grounding"]["grounded"] is True


def test_rejected_first_sentence_is_never_streamed_and_revision_can_succeed():
    prompts = []

    def provider(prompt):
        prompts.append(prompt)
        if len(prompts) == 1:
            yield "Afirmação sem suporte. [[1]]"
        else:
            yield "O prazo é de dez dias. [[1]]"

    events = stream_grounded_generation(
        "prompt", stream_attempt=provider, validate_attempt=_grounded_validation
    )
    streamed = []
    while True:
        try:
            streamed.append(next(events))
        except StopIteration as completed:
            result = completed.value
            break

    visible = "".join(item["chunk"] for item in streamed)
    assert len(prompts) == 2
    assert "REVISÃO OBRIGATÓRIA" in prompts[1]
    assert "Afirmação sem suporte" not in visible
    assert visible == result["answer"]
    assert result["partial"] is False
    assert result["grounding"]["grounded"] is True


def test_partial_grounded_prefix_can_be_discarded_for_one_revision_attempt():
    prompts = []

    def provider(prompt):
        prompts.append(prompt)
        if len(prompts) == 1:
            yield "A lei cria um programa. [[1]] "
            yield "Afirmação sem suporte sobre todas as escolas. [[2]]"
        else:
            yield "A lei cria um programa. [[1]] A execução observa os critérios do Art. 4º. [[2]]"

    events = stream_grounded_generation(
        "prompt",
        stream_attempt=provider,
        validate_attempt=_grounded_validation,
        retry_after_partial_rejection=True,
        revision_instruction="\n\nREVISÃO OBRIGATÓRIA — VISÃO GERAL PARCIAL: cite três dispositivos.",
    )
    visible_events = []
    while True:
        try:
            visible_events.append(next(events))
        except StopIteration as completed:
            result = completed.value
            break

    assert len(prompts) == 2
    assert "REVISÃO OBRIGATÓRIA" in prompts[1]
    assert "VISÃO GERAL PARCIAL: cite três dispositivos." in prompts[1]
    assert result["partial"] is False
    assert result["answer"] == (
        "A lei cria um programa. [[1]] A execução observa os critérios do Art. 4º. [[2]]"
    )
    assert result["generation_attempts"][0]["attempt"] == 1
    assert result["generation_attempts"][1]["attempt"] == 2


def test_partial_retry_keeps_first_grounded_prefix_for_caller_breadth_check():
    prompts = []

    def provider(prompt):
        prompts.append(prompt)
        if len(prompts) == 1:
            yield "Afirmação válida para a amostra. [[1]] "
            yield "Afirmação sem suporte. [[2]]"
        else:
            yield "Afirmação sem suporte. [[2]]"

    events = stream_grounded_generation(
        "prompt",
        stream_attempt=provider,
        validate_attempt=_grounded_validation,
        retry_after_partial_rejection=True,
        revision_instruction="\n\nREVISÃO OBRIGATÓRIA",
    )
    while True:
        try:
            next(events)
        except StopIteration as completed:
            result = completed.value
            break

    assert len(prompts) == 2
    assert result["partial"] is True
    assert result["validated_prefix"] == "Afirmação válida para a amostra. [[1]]"
    assert result["validated_prefix_candidates"] == [
        {
            "answer": "Afirmação válida para a amostra. [[1]]",
            "grounding": _grounded_validation(
                "Afirmação válida para a amostra. [[1]]"
            )["grounding"],
            "source_only": True,
        }
    ]


def test_broad_partial_prefix_can_finish_without_retry_or_internal_notice():
    prompts = []

    def provider(prompt):
        prompts.append(prompt)
        yield "O programa é instituído. [[1]] "
        yield "A execução segue os critérios da unidade. [[2]] "
        yield "A seleção considera as atividades realizadas. [[3]] "
        yield "Afirmação sem suporte. [[4]]"

    events = stream_grounded_generation(
        "prompt",
        stream_attempt=provider,
        validate_attempt=_grounded_validation,
        retry_after_partial_rejection=True,
        should_retry_after_partial=lambda answer, validation: "[[3]]" not in answer,
        include_partial_notice=False,
    )
    visible = []
    while True:
        try:
            event = next(events)
            if event.get("event") == "chunk":
                visible.append(event["chunk"])
        except StopIteration as completed:
            result = completed.value
            break

    assert len(prompts) == 1
    assert result["partial"] is True
    assert "A resposta foi limitada" not in result["answer"]
    assert "Afirmação sem suporte" not in result["answer"]
    assert "".join(visible) == result["answer"]


def test_partial_prefix_callback_can_still_request_revision_when_too_narrow():
    prompts = []

    def provider(prompt):
        prompts.append(prompt)
        if len(prompts) == 1:
            yield "O programa é instituído. [[1]] "
            yield "Afirmação sem suporte. [[2]]"
        else:
            yield "A execução segue os critérios previstos. [[1]]"

    events = stream_grounded_generation(
        "prompt",
        stream_attempt=provider,
        validate_attempt=_grounded_validation,
        retry_after_partial_rejection=True,
        should_retry_after_partial=lambda _answer, _validation: True,
    )
    while True:
        try:
            next(events)
        except StopIteration as completed:
            result = completed.value
            break

    assert len(prompts) == 2
    assert result["partial"] is False
    assert result["answer"] == "A execução segue os critérios previstos. [[1]]"


def test_abbreviation_does_not_trigger_an_incomplete_sentence_release():
    state = {"continued": False}

    def provider(_prompt):
        yield "O Art. "
        state["continued"] = True
        yield "18 prevê dez dias. [[1]]"

    events = stream_grounded_generation(
        "prompt", stream_attempt=provider, validate_attempt=_grounded_validation
    )
    first = next(events)
    assert state["continued"] is True
    assert first["chunk"] == "O Art. 18 prevê dez dias. [[1]]"
    try:
        next(events)
    except StopIteration as completed:
        result = completed.value
    assert result["answer"] == first["chunk"]


def test_forwarder_returns_exactly_the_validated_text_it_yielded():
    generation = {"answer": "Trecho validado.", "partial": False}

    def events():
        yield {"event": "chunk", "chunk": "Trecho "}
        yield {"event": "status", "status": "ignored-by-answer-forwarder"}
        yield {"event": "chunk", "chunk": "validado."}
        return generation

    forwarded = forward_grounded_generation(events())
    chunks = []
    while True:
        try:
            chunks.append(next(forwarded))
        except StopIteration as completed:
            result, streamed_answer = completed.value
            break

    assert chunks == [
        {"event": "chunk", "chunk": "Trecho "},
        {"event": "chunk", "chunk": "validado."},
    ]
    assert result is generation
    assert streamed_answer == result["answer"]
