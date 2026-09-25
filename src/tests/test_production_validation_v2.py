from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase


class ProductionValidationCommandTests(SimpleTestCase):
    @patch("src.apps.operations.management.commands.production_validation.call_command")
    def test_command_reports_django_check_failure(self, mocked):
        mocked.side_effect = SystemExit(1)
        out = StringIO()
        call_command("production_validation", stdout=out)
        assert "FAIL" in out.getvalue()
