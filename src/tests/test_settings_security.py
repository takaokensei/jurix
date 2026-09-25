"""
Settings are evaluated at import time, so each scenario runs in a fresh
interpreter with a controlled environment (audit P1.5).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROBE = (
    "import json, config.settings as s;"
    "print(json.dumps({k: getattr(s, k, None) for k in ("
    "'DEBUG','ALLOWED_HOSTS','SESSION_COOKIE_SECURE','CSRF_COOKIE_SECURE',"
    "'CSRF_COOKIE_HTTPONLY','SECURE_HSTS_SECONDS','SECURE_SSL_REDIRECT',"
    "'SECURE_PROXY_SSL_HEADER','CSRF_TRUSTED_ORIGINS','SECRET_KEY')}))"
)


def load_settings(**env):
    """Import config.settings in a clean subprocess; return (returncode, dict|stderr)."""
    clean = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(ROOT),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "WINDIR": os.environ.get("WINDIR", ""),
        "PYTHONUTF8": "1",
        "DJANGO_SKIP_DOTENV": "1",
    }
    clean.update({k: v for k, v in env.items() if v is not None})
    proc = subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=ROOT,
        env=clean,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        return proc.returncode, proc.stderr
    return 0, json.loads(proc.stdout.strip().splitlines()[-1])


def test_debug_defaults_to_false_and_refuses_to_start_without_a_secret():
    code, err = load_settings()  # nothing set: the production mistake
    assert code != 0
    assert "DJANGO_SECRET_KEY" in err


def test_public_dev_key_is_rejected_when_debug_is_off():
    code, err = load_settings(DJANGO_SECRET_KEY="django-insecure-dev-key-change-in-production")
    assert code != 0
    assert "DJANGO_SECRET_KEY" in err


def test_debug_true_allows_the_dev_fallback_key():
    code, cfg = load_settings(DEBUG="True")
    assert code == 0
    assert cfg["DEBUG"] is True
    assert cfg["SECRET_KEY"]


def test_production_defaults_are_secure():
    code, cfg = load_settings(DJANGO_SECRET_KEY="a-private-key-of-reasonable-length-1234567890")
    assert code == 0
    assert cfg["DEBUG"] is False
    assert cfg["ALLOWED_HOSTS"] == ["localhost", "127.0.0.1"]  # never ['*']
    assert cfg["SESSION_COOKIE_SECURE"] is True
    assert cfg["CSRF_COOKIE_SECURE"] is True


def test_csrf_cookie_stays_readable_by_javascript():
    """chat.js reads csrftoken to send X-CSRFToken; HttpOnly would break every POST."""
    code, cfg = load_settings(DJANGO_SECRET_KEY="a-private-key-of-reasonable-length-1234567890")
    assert cfg["CSRF_COOKIE_HTTPONLY"] is False


def test_hsts_and_ssl_redirect_are_opt_in():
    code, cfg = load_settings(DJANGO_SECRET_KEY="a-private-key-of-reasonable-length-1234567890")
    assert cfg["SECURE_HSTS_SECONDS"] == 0
    assert cfg["SECURE_SSL_REDIRECT"] is False


def test_secure_cookies_can_be_disabled_for_plain_http_deployments():
    code, cfg = load_settings(
        DJANGO_SECRET_KEY="a-private-key-of-reasonable-length-1234567890",
        SESSION_COOKIE_SECURE="False",
        CSRF_COOKIE_SECURE="false",
    )
    assert cfg["SESSION_COOKIE_SECURE"] is False and cfg["CSRF_COOKIE_SECURE"] is False


def test_debug_is_case_insensitive():
    assert load_settings(DEBUG="true")[1]["DEBUG"] is True
    assert load_settings(DEBUG="TRUE")[1]["DEBUG"] is True


def test_proxy_ssl_header_and_trusted_origins_are_opt_in():
    base = {"DJANGO_SECRET_KEY": "a-private-key-of-reasonable-length-1234567890"}
    _, off = load_settings(**base)
    assert off["SECURE_PROXY_SSL_HEADER"] is None and off["CSRF_TRUSTED_ORIGINS"] == []
    _, on = load_settings(
        **base,
        TRUST_X_FORWARDED_PROTO="1",
        CSRF_TRUSTED_ORIGINS="https://a.example, https://b.example",
    )
    assert on["SECURE_PROXY_SSL_HEADER"] == ["HTTP_X_FORWARDED_PROTO", "https"]
    assert on["CSRF_TRUSTED_ORIGINS"] == ["https://a.example", "https://b.example"]
