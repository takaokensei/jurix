"""
Legislation models for Jurix project.
"""
from django.db import models
from django.contrib.auth.models import User
from pgvector.django import VectorField
from src.apps.core.models import TimeStampedModel


class Norma(TimeStampedModel):
    """
    Core model representing a legal norm (Law, Decree, etc.).
    
    Stores original metadata from SAPL API and controls processing status
    through the pipeline (PDF Download -> OCR -> NLP -> Consolidation).
    
    Attributes:
        tipo: Type of legal norm (e.g., "Lei", "Decreto")
        numero: Norm number
        ano: Year of publication
        texto_original: Original text extracted from PDF
        texto_consolidado: Consolidated text after applying all alterations
        status: Current processing status in the pipeline
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
    texto_consolidado = models.TextField(
        verbose_name='Texto Consolidado',
        blank=True,
        help_text='Texto legal consolidado após aplicação de todas as alterações'
    )
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
        ('consolidation', 'Consolidação em Processamento'),
        ('consolidated', 'Consolidado'),
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
    
    # Embedding for semantic search (pgvector)
    embedding = VectorField(
        dimensions=768,  # BERTimbau embedding size (or llama3 embedding size)
        null=True,
        blank=True,
        verbose_name='Embedding Vetorial',
        help_text='Vetor de embedding para busca semântica (gerado via Ollama/BERTimbau)'
    )
    
    embedding_model = models.CharField(
        max_length=100,
        blank=True,
        verbose_name='Modelo de Embedding',
        help_text='Nome do modelo usado para gerar o embedding (ex: "nomic-embed-text")'
    )
    
    embedding_generated_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Data de Geração do Embedding',
        help_text='Timestamp de quando o embedding foi gerado'
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
    
    def get_full_identifier(self) -> str:
        """
        Retorna o identificador completo do dispositivo.
        
        Alias para get_caminho_completo() para compatibilidade com 
        código existente (especialmente no Admin e ConsolidationEngine).
        
        Returns:
            String formatada com o caminho hierárquico completo
            Exemplo: "Art. 1º > § 2º > Inciso III"
        """
        return self.get_caminho_completo()


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


class ChatSession(TimeStampedModel):
    """
    Model for storing chat conversation sessions.
    
    Each session represents a conversation between a user and the chatbot.
    Sessions are linked to authenticated users for persistence.
    """
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='chat_sessions',
        verbose_name='Usuário',
        help_text='Usuário dono desta sessão de conversa'
    )
    
    title = models.CharField(
        max_length=200,
        verbose_name='Título',
        blank=True,
        help_text='Título da sessão (gerado a partir da primeira pergunta ou manual)'
    )
    
    slug = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        verbose_name='Slug',
        help_text='Identificador único da sessão para URL (ex: abc123def456)',
        blank=True,
        null=True
    )
    
    is_active = models.BooleanField(
        default=True,
        verbose_name='Ativa',
        help_text='Se esta sessão está atualmente ativa'
    )
    
    class Meta:
        verbose_name = 'Sessão de Chat'
        verbose_name_plural = 'Sessões de Chat'
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['user', '-updated_at']),
            models.Index(fields=['is_active']),
        ]
    
    def __str__(self) -> str:
        return f"{self.title or 'Conversa sem título'} - {self.user.username}"
    
    def get_last_message_preview(self) -> str:
        """Retorna preview da primeira pergunta do usuário da sessão."""
        first_user_msg = self.messages.filter(role='user').order_by('created_at').first()
        if first_user_msg:
            preview = first_user_msg.content[:50] + ('...' if len(first_user_msg.content) > 50 else '')
            return preview
        return ''
    
    def generate_slug(self) -> str:
        """Gera um slug único para a sessão (estilo Gemini: caracteres aleatórios)."""
        import secrets
        import string
        
        # Generate 12-character random slug (like Gemini: de2a906759f920b3)
        alphabet = string.ascii_lowercase + string.digits
        slug = ''.join(secrets.choice(alphabet) for _ in range(12))
        
        # Ensure uniqueness (only if slug field exists in database)
        # Check if field exists by trying to query it
        try:
            # Try to check if slug field exists by attempting a query
            # If field doesn't exist, this will raise an exception
            from django.db import connection
            table_name = self._meta.db_table
            with connection.cursor() as cursor:
                cursor.execute(f"""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name = %s AND column_name = 'slug'
                """, [table_name])
                has_slug_column = cursor.fetchone() is not None
            
            if has_slug_column:
                # Field exists, check uniqueness
                max_attempts = 10
                attempts = 0
                while ChatSession.objects.filter(slug=slug).exists() and attempts < max_attempts:
                    slug = ''.join(secrets.choice(alphabet) for _ in range(12))
                    attempts += 1
        except (AttributeError, ValueError, Exception) as e:
            # Field doesn't exist yet or query failed - just return generated slug
            # This is safe because if field doesn't exist, we can't check uniqueness anyway
            pass
        
        return slug
    
    def save(self, *args, **kwargs):
        """Auto-generate slug if not provided."""
        # Only generate slug if field exists in database (migration has been run)
        # Use try/except to handle case where field doesn't exist
        try:
            # Try to get current slug value - if this fails, field doesn't exist
            current_slug = getattr(self, 'slug', None)
            
            # If slug is None or empty, try to generate one
            if not current_slug:
                try:
                    # Check if slug field exists by trying to access it
                    # If field doesn't exist, this will raise an exception
                    self.slug = self.generate_slug()
                except (AttributeError, ValueError, Exception):
                    # Field doesn't exist or generation failed - skip
                    pass
        except (AttributeError, Exception):
            # Field doesn't exist in database - skip slug generation
            # This is safe because the field is optional (blank=True, null=True)
            pass
        
        # Always call super().save() - this will work even if slug field doesn't exist
        try:
            super().save(*args, **kwargs)
        except Exception as e:
            # If save fails due to slug field, try saving without slug
            # This handles the case where migration hasn't been run
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Save failed, retrying without slug: {e}")
            # Remove slug from kwargs if it exists
            if 'slug' in kwargs:
                del kwargs['slug']
            # Try to remove slug attribute if it exists
            if hasattr(self, 'slug'):
                try:
                    delattr(self, 'slug')
                except:
                    pass
            # Retry save
            super().save(*args, **kwargs)


class ChatMessage(TimeStampedModel):
    """
    Model for storing individual chat messages within a session.
    
    Stores both user questions and assistant responses with their sources.
    """
    ROLE_CHOICES = [
        ('user', 'Usuário'),
        ('assistant', 'Assistente'),
    ]
    
    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name='messages',
        verbose_name='Sessão',
        help_text='Sessão de chat à qual esta mensagem pertence'
    )
    
    role = models.CharField(
        max_length=10,
        choices=ROLE_CHOICES,
        verbose_name='Papel',
        help_text='Papel da mensagem (usuário ou assistente)'
    )
    
    content = models.TextField(
        verbose_name='Conteúdo',
        help_text='Conteúdo da mensagem (pergunta do usuário ou resposta do assistente)'
    )
    
    # For assistant messages: store sources as JSON
    sources_json = models.JSONField(
        default=list,
        blank=True,
        verbose_name='Fontes',
        help_text='Lista de fontes citadas na resposta (JSON)'
    )
    
    # Metadata for assistant responses
    metadata_json = models.JSONField(
        default=dict,
        blank=True,
        verbose_name='Metadados',
        help_text='Metadados da resposta (modelo usado, confidence, etc.)'
    )
    
    class Meta:
        verbose_name = 'Mensagem de Chat'
        verbose_name_plural = 'Mensagens de Chat'
        ordering = ['session', 'created_at']
        indexes = [
            models.Index(fields=['session', 'created_at']),
            models.Index(fields=['role']),
        ]
    
    def __str__(self) -> str:
        preview = self.content[:50] + ('...' if len(self.content) > 50 else '')
        return f"{self.get_role_display()}: {preview}"
