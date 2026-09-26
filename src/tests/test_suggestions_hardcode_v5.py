from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / "src/apps/legislation/templates/legislation/chatbot.html"
CHAT_JS = ROOT / "src/apps/core/static/js/chat.js"


def test_welcome_template_has_no_legal_question_placeholders():
    text = TEMPLATE.read_text(encoding="utf-8")
    banned = (
        "Quais normas regulam a regularização",
        "Compare as principais alterações introduzidas",
        "Quais dispositivos sobre zoneamento urbano",
        "Quais são os entendimentos jurisprudenciais do STF",
        "14.133/2021",
    )
    assert not any(value in text for value in banned)
    assert 'static \'js/jurix-dynamic-suggestions.js\'' in text


def test_chat_js_contains_no_static_suggestion_catalog():
    text = CHAT_JS.read_text(encoding="utf-8")
    banned = (
        "SUGGESTION_QUESTIONS",
        "renderFallbackChips",
        "Como funciona o zoneamento urbano?",
        "renderRandomSuggestions",
    )
    assert not any(value in text for value in banned)


def test_chat_js_refuses_to_synthesize_questions_without_dynamic_module():
    text = CHAT_JS.read_text(encoding="utf-8")
    assert "Dynamic suggestion module is missing" in text
