from django.core.management.base import BaseCommand

from src.apps.legislation.attachment_service import cleanup_expired_attachments


class Command(BaseCommand):
    help = "Remove expired temporary chat attachments, including abandoned sessions."

    def handle(self, *args, **options):
        self.stdout.write(str(cleanup_expired_attachments()))
