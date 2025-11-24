"""
Legislation models for Jurix project.
"""
from django.db import models
from src.apps.core.models import TimeStampedModel


class Norma(TimeStampedModel):
    """
    Modelo base para uma Norma Jurídica (Lei, Decreto, etc).
    
    Armazena metadados originais da API SAPL e controla o status de processamento
    através do pipeline (Download PDF -> OCR -> NLP -> Consolidação).
    """
    
    # Identificação (Fonte: API SAPL)
    tipo = models.CharField(max_length=100, verbose_name='Tipo', db_index=True)
    numero = models.CharField(max_length=50, verbose_name='Número')
    ano = models.IntegerField(verbose_name='Ano', db_index=True)
    ementa = models.TextField(verbose_name='Ementa', blank=True)
    
    # Datas (Seção 6.E - Complexidade Temporal)
    data_publicacao = models.DateField(
        verbose_name='Data de Publicação',
        null=True,
        blank=True,
        db_index=True,
        help_text='Data de publicação oficial da norma'
    )
    data_vigencia = models.DateField(
        verbose_name='Data de Vigência',
        null=True,
        blank=True,
        db_index=True,
        help_text='Data de início de vigência (pode diferir da publicação devido à vacatio legis)'
    )
    
    # Conteúdo
    texto_original = models.TextField(verbose_name='Texto Original', blank=True)
    observacao = models.TextField(verbose_name='Observação', blank=True)
    
    # Recursos (PDF)
    pdf_url = models.URLField(
        verbose_name='URL do PDF',
        max_length=500,
        blank=True,
        help_text='URL original do PDF no SAPL'
    )
    pdf_path = models.CharField(
        max_length=500,
        verbose_name='Caminho do PDF',
        blank=True,
        help_text='Caminho local do PDF baixado (data/raw/...)'
    )
    
    # Integração SAPL
    sapl_id = models.IntegerField(
        verbose_name='ID no SAPL',
        unique=True,
        null=True,
        blank=True,
        help_text='ID primário da norma no sistema SAPL'
    )
    sapl_url = models.URLField(
        verbose_name='URL SAPL',
        max_length=500,
        blank=True,
        help_text='URL da página da norma no SAPL'
    )
    sapl_metadata = models.JSONField(
        verbose_name='Metadados SAPL',
        default=dict,
        blank=True,
        help_text='Payload JSON bruto retornado pela API SAPL'
    )
    
    # Controle de Processamento (Pipeline Status)
    STATUS_CHOICES = [
        ('pending', 'Pendente'),
        ('pdf_downloaded', 'PDF Baixado'),
        ('ocr_processing', 'OCR em Processamento'),
        ('ocr_completed', 'OCR Completo'),
        ('nlp_processing', 'NLP em Processamento'),
        ('ready', 'Pronto para Consolidação'),
        ('failed', 'Falha no Processamento'),
    ]
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        verbose_name='Status',
        db_index=True
    )
    
    needs_review = models.BooleanField(
        default=False,
        verbose_name='Requer Revisão',
        help_text='Marcado se OCR teve baixa confiança ou erro de parsing'
    )
    
    processing_error = models.TextField(
        verbose_name='Erro de Processamento',
        blank=True,
        help_text='Mensagem de erro caso o processamento falhe'
    )
    
    class Meta:
        verbose_name = 'Norma'
        verbose_name_plural = 'Normas'
        ordering = ['-ano', '-numero']
        indexes = [
            models.Index(fields=['tipo', 'numero', 'ano']),
            models.Index(fields=['sapl_id']),
            models.Index(fields=['status']),
            models.Index(fields=['data_publicacao']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['tipo', 'numero', 'ano'],
                name='unique_norma_identifier'
            )
        ]
    
    def __str__(self) -> str:
        return f"{self.tipo} {self.numero}/{self.ano}"
    
    def is_em_vacatio_legis(self) -> bool:
        """
        Verifica se a norma está em período de vacatio legis.
        Retorna True se publicada mas ainda não vigente.
        """
        from django.utils import timezone
        
        if not self.data_publicacao or not self.data_vigencia:
            return False
        
        hoje = timezone.now().date()
        return self.data_publicacao <= hoje < self.data_vigencia

