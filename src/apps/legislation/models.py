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
        ('segmentation_processing', 'Segmentação em Processamento'),
        ('segmented', 'Texto Segmentado'),
        ('entity_extraction', 'Extração de Entidades'),
        ('entities_extracted', 'Entidades Extraídas'),
        ('nlp_processing', 'NLP em Processamento'),
        ('ready', 'Pronto para Consolidação'),
        ('failed', 'Falha no Processamento'),
    ]
    status = models.CharField(
        max_length=30,
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


class Dispositivo(TimeStampedModel):
    """
    Modelo para armazenar a estrutura hierárquica de uma norma jurídica.
    
    Representa elementos estruturais como Artigos, Parágrafos, Incisos, Alíneas, etc.
    Mantém relações pai-filho para navegação hierárquica.
    
    Exemplos:
    - Artigo 1º (sem pai)
    - § 1º (pai: Artigo 1º)
    - Inciso I (pai: § 1º ou Artigo 1º)
    - Alínea a) (pai: Inciso I)
    """
    
    # Tipos de dispositivos legais
    TIPO_CHOICES = [
        ('artigo', 'Artigo'),
        ('paragrafo', 'Parágrafo'),
        ('inciso', 'Inciso'),
        ('alinea', 'Alínea'),
        ('item', 'Item'),
        ('capitulo', 'Capítulo'),
        ('secao', 'Seção'),
        ('titulo', 'Título'),
        ('livro', 'Livro'),
        ('parte', 'Parte'),
    ]
    
    # Relacionamentos
    norma = models.ForeignKey(
        Norma,
        on_delete=models.CASCADE,
        related_name='dispositivos',
        verbose_name='Norma',
        help_text='Norma à qual este dispositivo pertence'
    )
    
    dispositivo_pai = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='filhos',
        verbose_name='Dispositivo Pai',
        help_text='Dispositivo pai na hierarquia (null para elementos raiz)'
    )
    
    # Identificação
    tipo = models.CharField(
        max_length=20,
        choices=TIPO_CHOICES,
        verbose_name='Tipo',
        db_index=True,
        help_text='Tipo do dispositivo (artigo, parágrafo, etc.)'
    )
    
    numero = models.CharField(
        max_length=50,
        verbose_name='Número',
        help_text='Número ou identificador do dispositivo (ex: "1º", "I", "a")'
    )
    
    # Conteúdo
    texto = models.TextField(
        verbose_name='Texto',
        help_text='Conteúdo textual do dispositivo'
    )
    
    # Ordenação
    ordem = models.IntegerField(
        verbose_name='Ordem',
        help_text='Ordem sequencial do dispositivo na norma (para preservar sequência original)',
        db_index=True
    )
    
    # Metadados de segmentação
    segmentation_confidence = models.FloatField(
        verbose_name='Confiança da Segmentação',
        default=1.0,
        help_text='Confiança do regex na identificação deste dispositivo (0-1)'
    )
    
    texto_bruto = models.TextField(
        verbose_name='Texto Bruto',
        blank=True,
        help_text='Texto original antes da limpeza (para auditoria)'
    )
    
    class Meta:
        verbose_name = 'Dispositivo'
        verbose_name_plural = 'Dispositivos'
        ordering = ['norma', 'ordem']
        indexes = [
            models.Index(fields=['norma', 'tipo']),
            models.Index(fields=['norma', 'ordem']),
            models.Index(fields=['dispositivo_pai']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['norma', 'ordem'],
                name='unique_dispositivo_ordem'
            )
        ]
    
    def __str__(self) -> str:
        if self.tipo == 'artigo':
            return f"Art. {self.numero}"
        elif self.tipo == 'paragrafo':
            return f"§ {self.numero}"
        elif self.tipo == 'inciso':
            return f"Inciso {self.numero}"
        elif self.tipo == 'alinea':
            return f"Alínea {self.numero}"
        else:
            return f"{self.get_tipo_display()} {self.numero}"
    
    def get_caminho_completo(self) -> str:
        """
        Retorna o caminho hierárquico completo do dispositivo.
        
        Exemplo: "Art. 1º > § 2º > Inciso III > Alínea b"
        """
        caminho = [str(self)]
        pai = self.dispositivo_pai
        
        while pai:
            caminho.insert(0, str(pai))
            pai = pai.dispositivo_pai
        
        return " > ".join(caminho)
    
    def get_nivel(self) -> int:
        """
        Retorna o nível hierárquico do dispositivo (0 = raiz).
        """
        nivel = 0
        pai = self.dispositivo_pai
        
        while pai:
            nivel += 1
            pai = pai.dispositivo_pai
        
        return nivel


class EventoAlteracao(TimeStampedModel):
    """
    Model for tracking legal alteration events and cross-references.
    
    Represents relationships where one dispositivo modifies, revokes, or
    references another norma or dispositivo.
    
    Examples:
    - "Revoga-se o Art. 5º da Lei 1.234/2020"
    - "Dê-se nova redação ao § 2º do Art. 10"
    - "Fica alterado o inciso III..."
    """
    
    # Action types for legal modifications
    ACAO_CHOICES = [
        ('REVOGA', 'Revogação'),          # Revokes/annuls
        ('ALTERA', 'Alteração'),          # Modifies/changes
        ('ADICIONA', 'Adição'),           # Adds new content
        ('SUBSTITUI', 'Substituição'),    # Replaces
        ('REGULAMENTA', 'Regulamentação'), # Regulates
        ('REFERENCIA', 'Referência'),     # Generic reference
    ]
    
    # Source: the dispositivo that causes the change
    dispositivo_fonte = models.ForeignKey(
        Dispositivo,
        on_delete=models.CASCADE,
        related_name='alteracoes_causadas',
        verbose_name='Dispositivo Fonte',
        help_text='Dispositivo que origina a alteração'
    )
    
    # Action type
    acao = models.CharField(
        max_length=20,
        choices=ACAO_CHOICES,
        verbose_name='Ação',
        db_index=True,
        help_text='Tipo de ação legal (revoga, altera, etc.)'
    )
    
    # Raw text of the reference (for auditing)
    target_text = models.CharField(
        max_length=500,
        verbose_name='Texto da Referência',
        help_text='Texto bruto da referência extraída (ex: "o Art. 5º da Lei 123/2020")'
    )
    
    # Target norma (if identified)
    norma_alvo = models.ForeignKey(
        Norma,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='alteracoes_recebidas',
        verbose_name='Norma Alvo',
        help_text='Norma que é alvo da alteração (se identificada)'
    )
    
    # Target dispositivo (if identified within same norma or linked norma)
    dispositivo_alvo = models.ForeignKey(
        Dispositivo,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='alteracoes_recebidas',
        verbose_name='Dispositivo Alvo',
        help_text='Dispositivo específico que é alvo da alteração'
    )
    
    # Extraction metadata
    extraction_confidence = models.FloatField(
        verbose_name='Confiança da Extração',
        default=0.0,
        help_text='Confiança do NER na extração (0-1)'
    )
    
    extraction_method = models.CharField(
        max_length=50,
        verbose_name='Método de Extração',
        default='regex',
        help_text='Método usado para extração (regex, spacy, bert, etc.)'
    )
    
    # Parsed components (for complex references)
    referencia_tipo = models.CharField(
        max_length=50,
        verbose_name='Tipo Referenciado',
        blank=True,
        help_text='Tipo do elemento referenciado (artigo, parágrafo, lei, etc.)'
    )
    
    referencia_numero = models.CharField(
        max_length=50,
        verbose_name='Número Referenciado',
        blank=True,
        help_text='Número do elemento referenciado (ex: "5º", "123/2020")'
    )
    
    # Status tracking
    validado = models.BooleanField(
        default=False,
        verbose_name='Validado',
        help_text='Se a referência foi validada/confirmada manualmente'
    )
    
    class Meta:
        verbose_name = 'Evento de Alteração'
        verbose_name_plural = 'Eventos de Alteração'
        ordering = ['dispositivo_fonte__norma', 'dispositivo_fonte__ordem']
        indexes = [
            models.Index(fields=['dispositivo_fonte', 'acao']),
            models.Index(fields=['norma_alvo']),
            models.Index(fields=['dispositivo_alvo']),
            models.Index(fields=['acao']),
        ]
    
    def __str__(self) -> str:
        acao_display = self.get_acao_display()
        fonte = str(self.dispositivo_fonte)
        
        if self.dispositivo_alvo:
            return f"{fonte} {acao_display} {self.dispositivo_alvo}"
        elif self.norma_alvo:
            return f"{fonte} {acao_display} {self.norma_alvo}"
        else:
            return f"{fonte} {acao_display} (não identificado)"
    
    def get_descricao_completa(self) -> str:
        """
        Retorna descrição completa do evento com contexto.
        """
        fonte_caminho = self.dispositivo_fonte.get_caminho_completo()
        norma_fonte = self.dispositivo_fonte.norma
        
        desc = f"Na {norma_fonte}, o {fonte_caminho} {self.get_acao_display()}"
        
        if self.dispositivo_alvo:
            desc += f" o {self.dispositivo_alvo.get_caminho_completo()}"
            if self.dispositivo_alvo.norma != norma_fonte:
                desc += f" da {self.dispositivo_alvo.norma}"
        elif self.norma_alvo:
            desc += f" dispositivo(s) da {self.norma_alvo}"
        else:
            desc += f" '{self.target_text}'"
        
        return desc

