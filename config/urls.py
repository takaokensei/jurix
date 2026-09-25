"""
URL configuration for Jurix project.
"""

from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("", RedirectView.as_view(url="/normas/", permanent=False), name="home_redirect"),
    path("", include("src.apps.legislation.workspace_urls")),
    path("admin/", admin.site.urls),
    path("normas/", include("src.apps.legislation.urls")),
    path("api/v1/", include("src.apps.legislation.api_urls")),
]
