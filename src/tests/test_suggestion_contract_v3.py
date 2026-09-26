from __future__ import annotations

from io import StringIO
from pathlib import Path

from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse

from src.apps.legislation.models import Norma
from src.apps.legislation.suggestion_service import build_dynamic_suggestions

ROOT = Path(__file__).resolve().parents[2]


def make_norma(**overrides):
    values = {
        "tipo": "Lei",
        "numero": "900",
        "ano": 2026,
        "ementa": "Dispõe sobre atendimento digital ao cidadão e acesso a serviços públicos.",
        "sapl_id": 9001,
        "status": Norma.Status.CONSOLIDATED,
    }
    values.update(overrides)
    return Norma.objects.create(**values)


class SuggestionSurfaceTests(TestCase):
    def setUp(self):
        cache.clear()
        make_norma()
        make_norma(
            numero="901",
            ano=2025,
            ementa="Institui regras para mobilidade e transporte público municipal.",
            sapl_id=9002,
        )

    def test_suggestions_use_multiple_norms_before_repeating_topics(self):
        suggestions = build_dynamic_suggestions(4)
        self.assertGreaterEqual(len(suggestions), 2)
        identifiers = {item["identifier"] for item in suggestions}
        self.assertGreaterEqual(len(identifiers), 2)

    def test_api_response_is_cacheable_but_private(self):
        response = self.client.get(reverse("legislation_api:dynamic_suggestions"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("private", response["Cache-Control"])
        self.assertEqual(response["X-Jurix-Suggestion-Source"], "corpus")

    @override_settings(LLM_RATE_LIMIT_REQUESTS=1, LLM_RATE_LIMIT_WINDOW_SECONDS=60)
    def test_suggestion_endpoint_is_rate_limited(self):
        first = self.client.get(reverse("legislation_api:dynamic_suggestions"))
        second = self.client.get(reverse("legislation_api:dynamic_suggestions"))
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertIn("Retry-After", second)


class SuggestionCommandTests(TestCase):
    def test_warm_command_outputs_json(self):
        make_norma(
            numero="950",
            ementa="Regulamenta atendimento eletrônico e tramitação digital.",
            sapl_id=9050,
        )
        stdout = StringIO()
        call_command("warm_dynamic_suggestions", "--json", stdout=stdout)
        output = stdout.getvalue()
        self.assertIn('"source": "municipal_natal_corpus"', output)
        self.assertIn('"suggestions"', output)

    def test_warm_command_rejects_invalid_limit(self):
        with self.assertRaises(CommandError):
            call_command("warm_dynamic_suggestions", "--limit", "99")


class StaticSuggestionContractTests(TestCase):
    def test_contract_command_passes_against_current_tree(self):
        stdout = StringIO()
        call_command("validate_suggestion_contract", stdout=stdout)
        self.assertIn("Suggestion contract: PASS", stdout.getvalue())

    def test_no_placeholder_card_markup_exists(self):
        template = (
            ROOT
            / "src"
            / "apps"
            / "legislation"
            / "templates"
            / "legislation"
            / "chatbot.html"
        ).read_text(encoding="utf-8")
        section = template.split("figma-suggestions-cards", 1)[1].split("</div>", 1)[0]
        self.assertNotIn("data-question=", section)

