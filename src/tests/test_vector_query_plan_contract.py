from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase


class VectorQueryPlanContractTests(SimpleTestCase):
    @patch("src.apps.operations.management.commands.verify_vector_query_plan.connection")
    def test_rejects_seq_scan_plan(self, connection):
        connection.vendor = "postgresql"
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (5000,)
        cursor.fetchall.return_value = [("Limit",), ("Seq Scan on legislation_dispositivo",)]
        with self.assertRaises(CommandError):
            call_command("verify_vector_query_plan")

    @patch("src.apps.operations.management.commands.verify_vector_query_plan.connection")
    def test_allows_seq_scan_for_tiny_empty_test_corpus(self, connection):
        connection.vendor = "postgresql"
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (0,)
        cursor.fetchall.return_value = [("Seq Scan on legislation_dispositivo",)]
        call_command("verify_vector_query_plan")

    @patch("src.apps.operations.management.commands.verify_vector_query_plan.connection")
    def test_accepts_indexed_plan(self, connection):
        connection.vendor = "postgresql"
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (5000,)
        cursor.fetchall.return_value = [("Limit",), ("Index Scan using dispositivo_embedding_hnsw on legislation_dispositivo",)]
        call_command("verify_vector_query_plan")
