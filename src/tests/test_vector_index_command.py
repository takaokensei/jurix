from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase


class VectorIndexCommandTests(SimpleTestCase):
    @patch("src.apps.operations.management.commands.ensure_vector_index.connection")
    def test_non_postgresql_is_safe(self, connection):
        connection.vendor = "sqlite"
        out = StringIO()
        call_command("ensure_vector_index", stdout=out)
        assert "skipped" in out.getvalue()

    @patch("src.apps.operations.management.commands.ensure_vector_index.connection")
    def test_invalid_parameters_are_rejected(self, connection):
        connection.vendor = "postgresql"
        with self.assertRaises(CommandError):
            call_command("ensure_vector_index", "--m", "2")
