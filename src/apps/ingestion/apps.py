from django.apps import AppConfig


class IngestionConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'src.apps.ingestion'
    verbose_name = 'Ingestion'

