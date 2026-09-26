from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Valida o contrato de que sugestões visíveis vêm somente do corpus dinâmico."

    ROOT = Path(__file__).resolve().parents[5]
    CHAT_JS = ROOT / "src" / "apps" / "core" / "static" / "js" / "chat.js"
    CHATBOT_HTML = (
        ROOT / "src" / "apps" / "legislation" / "templates" / "legislation" / "chatbot.html"
    )
    SUGGESTIONS_JS = (
        ROOT / "src" / "apps" / "core" / "static" / "js" / "jurix-dynamic-suggestions.js"
    )

    def _read(self, path: Path) -> str:
        if not path.exists():
            raise CommandError(f"Arquivo esperado não encontrado: {path}")
        return path.read_text(encoding="utf-8")

    def handle(self, *args, **options):
        chat_js = self._read(self.CHAT_JS)
        chatbot = self._read(self.CHATBOT_HTML)
        dynamic_js = self._read(self.SUGGESTIONS_JS)

        violations = []
        for token in ("SUGGESTION_QUESTIONS", "renderFallbackChips", "fetchDynamicSuggestions"):
            if token in chat_js:
                violations.append(f"chat.js ainda contém {token}")

        card_section = (
            chatbot.split("figma-suggestions-cards", 1)[1]
            if "figma-suggestions-cards" in chatbot
            else ""
        )
        if "data-question=" in card_section.split("</div>", 1)[0]:
            violations.append("chatbot.html contém perguntas hardcoded no container de sugestões")

        for token in ("/api/v1/suggestions/", 'data-source="corpus"', "municipal_natal_corpus"):
            if token not in dynamic_js:
                violations.append(f"controller dinâmico sem contrato esperado: {token}")

        if violations:
            raise CommandError("; ".join(violations))

        self.stdout.write(self.style.SUCCESS("Suggestion contract: PASS"))
