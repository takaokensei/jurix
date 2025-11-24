"""
Core models for Jurix project.
"""
from django.db import models


class TimeStampedModel(models.Model):
    """
    Abstract base model with timestamp fields.
    All models should inherit from this.
    """
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Criado em')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Atualizado em')

    class Meta:
        abstract = True

