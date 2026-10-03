"""Integrated, isolated-database smoke coverage for core legal journeys."""

from datetime import date

import fitz
import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from src.apps.legislation.models import ChatMessage, ChatSession, Dispositivo, Norma

pytestmark = pytest.mark.django_db


def test_public_research_journey_from_exact_reference_to_official_text_and_pdf():
    text = (
        "Art. 1º Fica instituído o Programa Municipal de Educação Popular.\n"
        "Art. 2º O Município apoiará ações de educação e cidadania.\n"
        "Art. 3º Esta Lei entra em vigor na data de sua publicação."
    )
    norma = Norma.objects.create(
        tipo="Lei",
        numero="8206",
        ano=2026,
        status="consolidated",
        ementa="Institui programa municipal de educação popular.",
        data_publicacao=date(2026, 9, 21),
        data_vigencia=date(2026, 9, 21),
        texto_original=text,
        texto_consolidado=text,
    )
    article = Dispositivo.objects.create(
        norma=norma,
        tipo="artigo",
        numero="1º",
        texto="Fica instituído o Programa Municipal de Educação Popular.",
        ordem=1,
    )
    client = Client()

    catalog = client.get("/normas/", {"q": "Lei nº 8.206/2026"})
    research = client.get("/pesquisa/", {"q": "Lei nº 8.206/2026"})
    detail = client.get(f"/normas/{norma.pk}/")
    tree = client.get(f"/normas/{norma.pk}/tree/")
    comparison = client.get(f"/normas/{norma.pk}/compare/")
    api_detail = client.get(f"/api/v1/normas/{norma.pk}/")
    pdf = client.get(f"/normas/{norma.pk}/export/pdf/")

    assert catalog.status_code == research.status_code == 200
    assert "8206/2026" in catalog.content.decode()
    assert "8206/2026" in research.content.decode()
    assert detail.status_code == tree.status_code == comparison.status_code == 200
    assert "Programa Municipal de Educação Popular" in detail.content.decode()
    assert f"dispositivo-{article.pk}" in detail.content.decode()
    assert "Art. 1º" in tree.content.decode()
    assert "Programa Municipal de Educação Popular" in comparison.content.decode()
    assert api_detail.status_code == 200
    assert api_detail.json()["success"] is True
    assert pdf.status_code == 200
    assert pdf["Content-Type"] == "application/pdf"
    with fitz.open(stream=pdf.content, filetype="pdf") as document:
        extracted = " ".join(page.get_text() for page in document)
    assert "educação popular" in extracted.casefold()


def test_authenticated_workspace_journey_restores_the_same_chat_and_recent_history():
    user = get_user_model().objects.create_user(
        username="legal-journey", password="journey-password"
    )
    session = ChatSession.objects.create(
        user=user, title="Programa de Educação Popular", is_active=True
    )
    ChatMessage.objects.create(
        session=session,
        role="user",
        content="O que prevê a Lei nº 8.206/2026?",
    )
    ChatMessage.objects.create(
        session=session,
        role="assistant",
        content="A lei institui um programa municipal de educação popular.",
        metadata_json={"grounded": False},
    )
    client = Client()
    assert client.login(username="legal-journey", password="journey-password")

    assistant = client.get(f"/assistente/{session.slug}/")
    history = client.get("/historico/")
    settings = client.get("/configuracoes/")
    collections = client.get("/colecoes/")
    restored_session = client.get(f"/api/v1/chat/sessions/slug/{session.slug}/")

    assert assistant.status_code == history.status_code == 200
    assert settings.status_code == collections.status_code == 200
    assert restored_session.status_code == 200
    assert any(
        message["content"] == "O que prevê a Lei nº 8.206/2026?"
        for message in restored_session.json()["messages"]
    )
    assert "Programa de Educação Popular" in history.content.decode()
