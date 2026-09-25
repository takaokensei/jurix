from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase


class VerifyVectorIndexTests(SimpleTestCase):
    @patch("src.apps.operations.management.commands.verify_vector_index.connection")
    def test_rejects_missing_ann_index(self, connection):
        connection.vendor = "postgresql"
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = []
        with self.assertRaises(CommandError):
            call_command("verify_vector_index")

    @patch("src.apps.operations.management.commands.verify_vector_index.connection")
    def test_accepts_hnsw_cosine_index(self, connection):
        connection.vendor = "postgresql"
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [
            ("dispositivo_embedding_hnsw", "USING hnsw (embedding vector_cosine_ops)")
        ]
        call_command("verify_vector_index")
