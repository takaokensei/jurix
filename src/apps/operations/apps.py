from django.apps import AppConfig


class OperationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'src.apps.operations'
    verbose_name = 'Operations'

    def ready(self):
        from . import checks  # noqa: F401
