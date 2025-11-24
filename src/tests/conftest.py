"""
Pytest configuration and fixtures for Jurix tests.
"""

import pytest
from django.test import RequestFactory
from django.contrib.auth.models import User
from django.db import connection


@pytest.fixture(scope='session')
def django_db_setup(django_db_setup, django_db_blocker):
    """
    Enable pgvector extension in test database.
    """
    with django_db_blocker.unblock():
        with connection.cursor() as cursor:
            cursor.execute('CREATE EXTENSION IF NOT EXISTS vector;')


@pytest.fixture
def factory():
    """Request factory for testing views."""
    return RequestFactory()


@pytest.fixture
def user(db):
    """Create a test user."""
    return User.objects.create_user(
        username='testuser',
        email='test@example.com',
        password='testpass123'
    )


@pytest.fixture
def mock_ollama_response():
    """Mock response from Ollama API."""
    return {
        'embedding': [0.1] * 768,  # Mock embedding vector
        'response': 'This is a mock response from Ollama',
    }

