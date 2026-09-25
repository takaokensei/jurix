import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.test import RequestFactory

from src.apps.legislation.api_views import _chat_session_response, chatbot_stream_api
from src.apps.legislation.models import (
    ChatMessage,
    ChatSession,
    Dispositivo,
    EventoAlteracao,
    Norma,
)
from src.processing.adaptive_rag_service import AdaptiveRAGService
from src.processing.adaptive_retrieval import AdaptiveRetriever, RetrievalOptions
from src.processing.target_reconciliation import (
    parse_target_reference,
    reconcile_unresolved_event_targets,
)


def test_minimum_rejects_first_weak_result():
    row = {'retrieval_score': .01, 'dispositivo': SimpleNamespace(norma_id=1)}
    assert AdaptiveRetriever._select([row], 12, .9) == []


def test_scope_still_applies_with_all_statuses():
    row = {'dispositivo': SimpleNamespace(norma=SimpleNamespace(sapl_url='https://example.com', status='pending'))}
    assert AdaptiveRAGService._filter_status([row], RetrievalOptions(norma_status='all')) == []


@pytest.mark.parametrize('kind,number', [('artigo', '5º'), ('', '')])
def test_article_reference_extracts_containing_law(kind, number):
    ref = parse_target_reference(SimpleNamespace(referencia_tipo=kind, referencia_numero=number,
                                                 target_text='Art. 5º da Lei nº 8.206/2026'))
    assert (ref.tipo.lower(), ref.numero, ref.ano) == ('lei', '8.206', 2026)


@pytest.mark.django_db
def test_reconciliation_uses_real_relations_and_exact_type():
    source = Norma.objects.create(tipo='Lei', numero='1', ano=2026)
    disp = Dispositivo.objects.create(norma=source, tipo='artigo', numero='1', ordem=1, texto='Altera')
    target = Norma.objects.create(tipo='Lei Ordinária', numero='8206', ano=2020)
    event = EventoAlteracao.objects.create(dispositivo_fonte=disp, acao='ALTERA',
        referencia_tipo='artigo', referencia_numero='5º', target_text='Art. 5º da Lei 8206/2020')
    assert reconcile_unresolved_event_targets()['resolved'] == 1
    event.refresh_from_db()
    assert event.norma_alvo_id == target.pk
    event.norma_alvo = None
    event.target_text = 'Lei Complementar 8206/2020'
    event.save()
    assert reconcile_unresolved_event_targets()['resolved'] == 0


@pytest.mark.django_db
def test_lexical_context_has_scores_and_only_used_sources():
    norma = Norma.objects.create(tipo='Lei', numero='1', ano=2026, status='consolidated')
    Dispositivo.objects.create(norma=norma, tipo='artigo', numero='1', ordem=1, texto='zoneamento ' * 100)
    service = AdaptiveRAGService(use_cache=False)
    service._jurix_retrieval_options = RetrievalOptions(mode='lexical')
    context, rows = service.get_relevant_context('zoneamento', k=12, max_tokens=20)
    assert 0 < len(context) <= 80
    assert len(rows) == 1
    assert 0 <= rows[0]['similarity_score'] <= 1


@pytest.mark.django_db
def test_history_cursor_retrieves_all_messages_once(user):
    session = ChatSession.objects.create(user=user, title='History')
    ChatMessage.objects.bulk_create([ChatMessage(session=session, role='user', content=str(i)) for i in range(60)])
    seen = []
    cursor = None
    while True:
        page = json.loads(_chat_session_response(session, cursor).content)
        seen.extend(msg['content'] for msg in page['messages'])
        cursor = page['next_cursor']
        if not cursor:
            break
    assert len(seen) == len(set(seen)) == 60
    other = ChatSession.objects.create(user=user, title='Other')
    cursor = json.loads(_chat_session_response(session).content)['next_cursor']
    assert _chat_session_response(other, cursor).status_code == 400


@pytest.mark.django_db
def test_closing_stream_persists_partial_once(user):
    cache.clear()
    request = RequestFactory().post('/api/v1/search/answer/stream/',
        data=json.dumps({'question': 'teste'}), content_type='application/json')
    request.user = user
    events = iter([{'event': 'chunk', 'chunk': 'Resposta parcial'}, {'event': 'done', 'answer': 'Completa'}])
    with patch('src.apps.legislation.api_views.RAGService') as service:
        service.return_value.stream_answer_question.return_value = events
        response = chatbot_stream_api(request)
        stream = iter(response.streaming_content)
        next(stream)  # session identity arrives before generation
        next(stream)  # partial text
        response._iterator.close()  # server closes the generator before request-finished signals
    saved = ChatMessage.objects.get(role='assistant')
    assert saved.content == 'Resposta parcial'
    assert saved.metadata_json['interrupted'] is True


@pytest.mark.django_db
def test_reingestion_preserves_extracted_text():
    from src.apps.ingestion.tasks import _process_norma_data
    norma = Norma.objects.create(sapl_id=99, tipo='Lei', numero='1', ano=2026,
        status='consolidated', texto_original='Art. 1º Texto extraído', pdf_url='https://example.com/law.pdf')
    _process_norma_data({'id': 99, 'tipo': 'Lei', 'numero': '1', 'ano': 2026,
                         'texto_integral': 'https://example.com/law.pdf'})
    norma.refresh_from_db()
    assert norma.texto_original == 'Art. 1º Texto extraído'


@pytest.mark.parametrize('page_size', [0, -1, True])
def test_bulk_rejects_unbounded_loop(page_size):
    from src.apps.ingestion.tasks import bulk_ingest_normas_task
    with pytest.raises(ValueError):
        bulk_ingest_normas_task.run(page_size=page_size)
