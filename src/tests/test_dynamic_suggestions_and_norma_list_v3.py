from __future__ import annotations

from pathlib import Path

from django.test import TestCase
from django.urls import reverse

from src.apps.legislation.models import Norma
from src.apps.legislation.suggestion_service import build_dynamic_suggestions

ROOT = Path(__file__).resolve().parents[2]
CHAT_JS = ROOT / "src" / "apps" / "core" / "static" / "js" / "chat.js"
CHATBOT_HTML = ROOT / "src" / "apps" / "legislation" / "templates" / "legislation" / "chatbot.html"
NORMA_TEMPLATE = ROOT / "src" / "apps" / "legislation" / "templates" / "legislation" / "norma_list.html"


class DynamicSuggestionContractTests(TestCase):
    def setUp(self):
        Norma.objects.create(
            tipo="Lei",
            numero="1234",
            ano=2026,
            ementa="Dispõe sobre mobilidade urbana e transporte coletivo municipal.",
            sapl_id=99123,
            status=Norma.Status.CONSOLIDATED,
        )

    def test_suggestions_are_derived_from_corpus(self):
        suggestions = build_dynamic_suggestions(4)
        self.assertGreaterEqual(len(suggestions), 1)
        self.assertTrue(any("1234/2026" in item["question"] for item in suggestions))
        self.assertTrue(all(item["source"] == "municipal_natal_corpus" for item in suggestions))

    def test_api_returns_corpus_source(self):
        response = self.client.get(reverse("legislation_api:dynamic_suggestions"), {"limit": 4})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["source"], "municipal_natal_corpus")
        self.assertTrue(payload["suggestions"])

    def test_no_hardcoded_legal_questions_remain_in_frontend(self):
        js = CHAT_JS.read_text(encoding="utf-8")
        html = CHATBOT_HTML.read_text(encoding="utf-8")
        forbidden = (
            "Como funciona o zoneamento urbano?",
            "Quais as regras para licença de construção?",
            "Lei nº 14.133/2021",
            "zoneamento urbano estão atualmente vigentes",
            "entendimentos jurisprudenciais do STF sobre desapropriação",
        )
        for text in forbidden:
            self.assertNotIn(text, js)
            self.assertNotIn(text, html)


class NormaListContractTests(TestCase):
    def setUp(self):
        Norma.objects.create(
            tipo="Lei",
            numero="100",
            ano=2025,
            ementa="Regula o transporte escolar municipal.",
            sapl_id=1001,
            status=Norma.Status.CONSOLIDATED,
        )
        Norma.objects.create(
            tipo="Decreto",
            numero="200",
            ano=2026,
            ementa="Regulamenta o programa municipal de mobilidade.",
            sapl_id=1002,
            status=Norma.Status.CONSOLIDATED,
        )

    def test_list_has_type_and_year_filters(self):
        response = self.client.get(reverse("legislation:norma_list"), {"tipo": "Lei", "ano": "2025"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Lei 100/2025")
        self.assertNotContains(response, "Decreto 200/2026")

    def test_query_filter_is_preserved(self):
        response = self.client.get(reverse("legislation:norma_list"), {"q": "transporte"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Lei 100/2025")
        self.assertContains(response, 'name="q"')

    def test_template_uses_dedicated_responsive_surface(self):
        template = NORMA_TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("jurix-norma-shell", template)
        self.assertIn("jurix-norma-grid", template)
        self.assertIn("jurix-norma-list.js", template)
        self.assertNotIn('class="norma-grid"', template)
