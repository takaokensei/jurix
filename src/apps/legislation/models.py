"""
Legislation models for Jurix project.
"""
from django.db import models
from src.apps.core.models import TimeStampedModel


class Norma(TimeStampedModel):
    """
    Modelo base para uma Norma Jurídica (Lei, Decreto, etc).
    """
    tipo = models.CharField(max_length=100, verbose_name='Tipo')
    numero = models.CharField(max_length=50, verbose_name='Número')
    ano = models.IntegerField(verbose_name='Ano')
    ementa = models.TextField(verbose_name='Ementa', blank=True)
    
    data_publicacao = models.DateField(verbose_name='Data de Publicação', null=True, blank=True)
    data_vigencia = models.DateField(verbose_name='Data de Vigência', null=True, blank=True)
    
    texto_original = models.TextField(verbose_name='Texto Original', blank=True)
    pdf_url = models.URLField(verbose_name='URL do PDF', blank=True)
    pdf_path = models.CharField(max_length=500, verbose_name='Caminho do PDF', blank=True)
    
    sapl_id = models.IntegerField(verbose_name='ID no SAPL', unique=True, null=True, blank=True)
    
    class Meta:
        verbose_name = 'Norma'
        verbose_name_plural = 'Normas'
        ordering = ['-ano', '-numero']
        indexes = [
            models.Index(fields=['tipo', 'numero', 'ano']),
            models.Index(fields=['sapl_id']),
        ]
    
    def __str__(self):
        return f"{self.tipo} {self.numero}/{self.ano}"

