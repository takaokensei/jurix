"""Release guard: the welcome screen must never reintroduce legal placeholders."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "src/apps/legislation/templates/legislation/chatbot.html"
CHAT_JS = ROOT / "src/apps/core/static/js/chat.js"

BANNED = (
    "SUGGESTION_QUESTIONS",
    "renderFallbackChips",
    "Como funciona o zoneamento urbano?",
    "Quais as regras para licença de construção?",
    "Quais normas regulam a regularização",
    "14.133/2021",
)

failures = []
for path in (TEMPLATE, CHAT_JS):
    text = path.read_text(encoding="utf-8")
    for value in BANNED:
        if value in text:
            failures.append(f"{path.relative_to(ROOT)} contains banned suggestion text: {value}")

template = TEMPLATE.read_text(encoding="utf-8")
if "jurix-dynamic-suggestions.js" not in template:
    failures.append("chatbot.html does not load jurix-dynamic-suggestions.js")

if failures:
    print("Dynamic suggestions contract FAILED")
    for failure in failures:
        print(f"BLOCK: {failure}")
    sys.exit(1)

print("Dynamic suggestions contract PASSED")
