"""
Static guards for the chat frontend (audit P3.6).

The server enforces CSRF on every session endpoint (audit P0.1), so a single fetch() that
forgets X-CSRFToken silently breaks that feature for every user. This is cheap to check
statically, without a browser.
"""
import re
from pathlib import Path

JS = Path(__file__).resolve().parents[1] / "apps" / "core" / "static" / "js"
MUTATING = re.compile(r"method:\s*['\"](POST|PUT|PATCH|DELETE)['\"]", re.I)


def _fetch_calls(source):
    """Yield (line_number, text_of_the_call) for every fetch( ... ) with balanced parentheses."""
    for m in re.finditer(r"\bfetch\(", source):
        depth, i = 0, m.end() - 1
        while i < len(source):
            depth += {"(": 1, ")": -1}.get(source[i], 0)
            if depth == 0:
                break
            i += 1
        yield source[: m.start()].count("\n") + 1, source[m.start(): i + 1]


def test_every_mutating_fetch_in_chat_js_sends_the_csrf_token():
    source = (JS / "chat.js").read_text(encoding="utf-8")
    calls = [(n, c) for n, c in _fetch_calls(source) if MUTATING.search(c)]
    assert calls, "expected chat.js to contain mutating fetch() calls (parser sanity check)"
    missing = [n for n, c in calls if "X-CSRFToken" not in c]
    assert missing == [], f"mutating fetch() without X-CSRFToken at chat.js lines {missing}"


def test_no_frontend_file_builds_javascript_urls_or_string_evals():
    for path in JS.glob("*.js"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\beval\(|new Function\(|document\.write\(", text), path.name


def test_source_card_url_is_never_interpolated_into_an_inline_handler():
    """Regression for the onclick=\"window.open('${url}')\" injection."""
    text = (JS / "chat.js").read_text(encoding="utf-8")
    assert "window.open('${" not in text
    assert "data-url=" in text and "safeHttpUrl(" in text


def test_all_markdown_is_rendered_through_the_single_sanitising_helper():
    """Answers come from an LLM fed with ingested text: every render must use renderMarkdown()."""
    text = (JS / "chat.js").read_text(encoding="utf-8")
    assert text.count("marked.parse(") == 1, "marked.parse() must only be called inside renderMarkdown()"
    assert text.count("DOMPurify.sanitize(") == 1, "DOMPurify.sanitize() must only be called inside renderMarkdown()"
    for tag in ("img", "style", "svg", "link"):
        assert f"'{tag}'" in text.split("const SANITIZE_CONFIG")[1].split("};")[0], tag


def test_chatbot_template_has_no_inline_handlers_scripts_or_javascript_urls():
    """Regression guard for the CSP hardening: chatbot.html must stay free of inline execution."""
    html = (
        Path(__file__).resolve().parents[1] / "apps" / "legislation" / "templates" / "legislation" / "chatbot.html"
    ).read_text(encoding="utf-8")
    assert not re.search(r"\son[a-z]+\s*=", html, re.IGNORECASE), "inline event handler attribute found"
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>\s*\S", html, re.IGNORECASE), "inline <script> with a body found"
    assert "javascript:" not in html.lower()


def test_chatbot_csp_does_not_allow_unsafe_inline_or_unsafe_eval_scripts():
    html = (
        Path(__file__).resolve().parents[1] / "apps" / "legislation" / "templates" / "legislation" / "chatbot.html"
    ).read_text(encoding="utf-8")
    match = re.search(r'Content-Security-Policy"\s+content="([^"]+)"', html)
    assert match, "expected a CSP meta tag"
    script_src = next(d for d in match.group(1).split(";") if d.strip().startswith("script-src"))
    assert "unsafe-inline" not in script_src and "unsafe-eval" not in script_src
