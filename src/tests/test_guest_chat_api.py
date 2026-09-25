import json

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory

from src.apps.legislation.api_views import chat_sessions_api


def test_guest_sessions_endpoint_returns_empty_collection_instead_of_401():
    request = RequestFactory().get("/api/v1/chat/sessions/")
    request.user = AnonymousUser()
    response = chat_sessions_api(request)
    assert response.status_code == 200
    payload = json.loads(response.content)
    assert payload == {"success": True, "sessions": []}
