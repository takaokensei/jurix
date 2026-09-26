from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from src.apps.legislation.suggestion_service import build_dynamic_suggestions


class Command(BaseCommand):
    help = (
        "Pré-aquece o cache de sugestões dinâmicas usando exclusivamente o corpus "
        "municipal atualmente ingerido."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=4,
            help="Quantidade máxima de sugestões a gerar (1–8).",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            help="Emite o resultado como JSON puro para automação.",
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        if not 1 <= limit <= 8:
            raise CommandError("--limit deve estar entre 1 e 8.")

        suggestions = build_dynamic_suggestions(limit)
        payload = {
            "success": True,
            "count": len(suggestions),
            "source": "municipal_natal_corpus",
            "suggestions": suggestions,
        }

        if options["json"]:
            self.stdout.write(json.dumps(payload, ensure_ascii=False))
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Cache de sugestões aquecido com {len(suggestions)} item(ns)."
            )
        )
        for item in suggestions:
            self.stdout.write(f"• {item['identifier']}: {item['question']}")

