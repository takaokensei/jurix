"""
URL configuration for Jurix project.
"""
from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('normas/', include('src.apps.legislation.urls')),
    path('api/v1/', include('src.apps.legislation.api_urls')),
]

