from django.http import HttpResponse, JsonResponse
from django.test import RequestFactory, override_settings

from config.middleware import ContentSecurityPolicyMiddleware


def test_global_csp_is_sent_as_http_header_for_html():
    factory = RequestFactory()
    middleware = ContentSecurityPolicyMiddleware(
        lambda request: HttpResponse("<html></html>", content_type="text/html; charset=utf-8")
    )

    response = middleware(factory.get("/normas/"))

    csp = response.headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "script-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "cdn.jsdelivr.net" not in csp


def test_csp_does_not_upgrade_same_origin_http_requests_in_debug():
    from config.middleware import _build_content_security_policy

    with override_settings(DEBUG=True):
        assert "upgrade-insecure-requests" not in _build_content_security_policy()


def test_csp_upgrades_insecure_requests_outside_debug():
    from config.middleware import _build_content_security_policy

    with override_settings(DEBUG=False):
        assert "upgrade-insecure-requests" in _build_content_security_policy()


def test_csp_is_not_added_to_json_responses():
    factory = RequestFactory()
    middleware = ContentSecurityPolicyMiddleware(lambda request: JsonResponse({"ok": True}))

    response = middleware(factory.get("/api/health/"))

    assert "Content-Security-Policy" not in response.headers
