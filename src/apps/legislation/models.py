"""
Legislation models for Jurix project.
"""

from django.contrib.auth.models import User
from django.db import models
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
    tipo = models.CharField(max_length=100, verbose_name="Tipo", db_index=True)
    numero = models.CharField(max_length=50, verbose_name="Número")
    ano = models.IntegerField(verbose_name="Ano", db_index=True)
    ementa = models.TextField(verbose_name="Ementa", blank=True)

    # Datas (Seção 6.E - Complexidade Temporal)
    data_publicacao = models.DateField(
        verbose_name="Data de Publicação",
        null=True,
        blank=True,
        db_index=True,
        help_text="Data de publicação oficial da norma",
    )
    data_vigencia = models.DateField(
        verbose_name="Data de Vigência",
        null=True,
        blank=True,
        db_index=True,
        help_text="Data de início de vigência (pode diferir da publicação devido à vacatio legis)",
    )

    # Conteúdo
    texto_original = models.TextField(verbose_name="Texto Original", blank=True)
    texto_consolidado = models.TextField(
        verbose_name="Texto Consolidado",
        blank=True,
        help_text="Texto legal consolidado após aplicação de todas as alterações",
    )
    observacao = models.TextField(verbose_name="Observação", blank=True)

    # Recursos (PDF)
    pdf_url = models.URLField(
        verbose_name="URL do PDF",
        max_length=500,
        blank=True,
        help_text="URL original do PDF no SAPL",
    )
    pdf_path = models.CharField(
        max_length=500,
        verbose_name="Caminho do PDF",
        blank=True,
        help_text="Caminho local do PDF baixado (data/raw/...)",
    )

    # Integração SAPL
    sapl_id = models.IntegerField(
        verbose_name="ID no SAPL",
        unique=True,
        null=True,
        blank=True,
        help_text="ID primário da norma no sistema SAPL",
    )
    sapl_url = models.URLField(
        verbose_name="URL SAPL",
        max_length=500,
        blank=True,
        help_text="URL da página da norma no SAPL",
    )
    sapl_metadata = models.JSONField(
        verbose_name="Metadados SAPL",
        default=dict,
        blank=True,
        help_text="Payload JSON bruto retornado pela API SAPL",
    )

    # Aditive identity/document links. Legacy rows remain unlinked until reviewed.
    identity_key = models.CharField(max_length=300, unique=True, null=True, blank=True)
    identity_json = models.JSONField(default=dict, blank=True)
    data_norma = models.DateField(null=True, blank=True, db_index=True)
    documento_base = models.ForeignKey(
        "legislation.DocumentoNormativo",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="normas_como_documento_base",
    )

    # Controle de Processamento (Pipeline Status)
    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        PDF_DOWNLOADED = "pdf_downloaded", "PDF Baixado"
        OCR_PROCESSING = "ocr_processing", "OCR em Processamento"
        OCR_COMPLETED = "ocr_completed", "OCR Completo"
        SEGMENTATION_PROCESSING = "segmentation_processing", "Segmentação em Processamento"
        SEGMENTED = "segmented", "Texto Segmentado"
        ENTITY_EXTRACTION = "entity_extraction", "Extração de Entidades"
        ENTITIES_EXTRACTED = "entities_extracted", "Entidades Extraídas"
        CONSOLIDATION = "consolidation", "Consolidação em Processamento"
        CONSOLIDATED = "consolidated", "Consolidado"
        NLP_PROCESSING = "nlp_processing", "NLP em Processamento"
        READY = "ready", "Pronto para Consolidação"
        FAILED = "failed", "Falha no Processamento"

    STATUS_CHOICES = Status.choices
    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name="Status",
        db_index=True,
    )

    needs_review = models.BooleanField(
        default=False,
        verbose_name="Requer Revisão",
        help_text="Marcado se OCR teve baixa confiança ou erro de parsing",
    )

    processing_error = models.TextField(
        verbose_name="Erro de Processamento",
        blank=True,
        help_text="Mensagem de erro caso o processamento falhe",
    )

    class Meta:
        verbose_name = "Norma"
        verbose_name_plural = "Normas"
        ordering = ["-ano", "-numero"]
        indexes = [
            models.Index(fields=["tipo", "numero", "ano"]),
            models.Index(fields=["sapl_id"]),
            models.Index(fields=["status"]),
            models.Index(fields=["data_publicacao"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["tipo", "numero", "ano"], name="unique_norma_identifier"
            )
        ]

    def get_tipo_display_name(self) -> str:
        """Return a type label from text or catalog provenance, never an ID guess."""
        from src.clients.sapl.sapl_types import resolve_norma_type_display

        return resolve_norma_type_display(self.tipo, self.sapl_metadata)

    def __str__(self) -> str:
        tipo_str = self.get_tipo_display_name()
        return f"{tipo_str} nº {self.numero}/{self.ano}"

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
        ("artigo", "Artigo"),
        ("paragrafo", "Parágrafo"),
        ("inciso", "Inciso"),
        ("alinea", "Alínea"),
        ("item", "Item"),
        ("capitulo", "Capítulo"),
        ("secao", "Seção"),
        ("titulo", "Título"),
        ("livro", "Livro"),
        ("parte", "Parte"),
    ]

    # Relacionamentos
    norma = models.ForeignKey(
        Norma,
        on_delete=models.CASCADE,
        related_name="dispositivos",
        verbose_name="Norma",
        help_text="Norma à qual este dispositivo pertence",
    )

    dispositivo_pai = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="filhos",
        verbose_name="Dispositivo Pai",
        help_text="Dispositivo pai na hierarquia (null para elementos raiz)",
    )

    # Identificação
    tipo = models.CharField(
        max_length=20,
        choices=TIPO_CHOICES,
        verbose_name="Tipo",
        db_index=True,
        help_text="Tipo do dispositivo (artigo, parágrafo, etc.)",
    )

    numero = models.CharField(
        max_length=50,
        verbose_name="Número",
        help_text='Número ou identificador do dispositivo (ex: "1º", "I", "a")',
    )

    # Conteúdo
    texto = models.TextField(verbose_name="Texto", help_text="Conteúdo textual do dispositivo")

    # Ordenação
    ordem = models.IntegerField(
        verbose_name="Ordem",
        help_text="Ordem sequencial do dispositivo na norma (para preservar sequência original)",
        db_index=True,
    )

    # Metadados de segmentação
    segmentation_confidence = models.FloatField(
        verbose_name="Confiança da Segmentação",
        default=1.0,
        help_text="Confiança do regex na identificação deste dispositivo (0-1)",
    )

    texto_bruto = models.TextField(
        verbose_name="Texto Bruto",
        blank=True,
        help_text="Texto original antes da limpeza (para auditoria)",
    )

    structural_key = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        help_text="Identidade estrutural estável do dispositivo dentro da norma.",
    )
    revision_fingerprint = models.CharField(
        max_length=64,
        blank=True,
        help_text="Hash do texto e redação bruta desta revisão do dispositivo.",
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Dispositivo presente na última segmentação validada da norma.",
    )

    # Hierarquia Materializada (O(1) lookups sem queries recursivas)
    caminho = models.CharField(
        max_length=500,
        blank=True,
        db_index=True,
        verbose_name="Caminho Hierárquico",
        help_text='Caminho materializado na hierarquia (ex: "Art. 1º > § 2º > Inciso III")',
    )
    nivel = models.IntegerField(
        default=0,
        db_index=True,
        verbose_name="Nível Hierárquico",
        help_text="Nível na árvore hierárquica (0 = raiz)",
    )

    # Embedding for semantic search (pgvector)
    embedding = VectorField(
        dimensions=768,  # BERTimbau embedding size (or llama3 embedding size)
        null=True,
        blank=True,
        verbose_name="Embedding Vetorial",
        help_text="Vetor de embedding para busca semântica (gerado via Ollama/BERTimbau)",
    )

    embedding_model = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="Modelo de Embedding",
        help_text='Nome do modelo usado para gerar o embedding (ex: "nomic-embed-text")',
    )

    embedding_generated_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Data de Geração do Embedding",
        help_text="Timestamp de quando o embedding foi gerado",
    )
    embedding_revision_fingerprint = models.CharField(
        max_length=64,
        blank=True,
        help_text="Fingerprint do conteúdo de origem usado para gerar o embedding.",
    )

    class Meta:
        verbose_name = "Dispositivo"
        verbose_name_plural = "Dispositivos"
        ordering = ["norma", "ordem"]
        indexes = [
            models.Index(fields=["norma", "tipo"]),
            models.Index(fields=["norma", "ordem"]),
            models.Index(fields=["dispositivo_pai"]),
            models.Index(fields=["norma", "nivel"]),
            models.Index(fields=["embedding_model"], name="disp_embed_model_idx"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["norma", "ordem"], name="unique_dispositivo_ordem")
        ]

    def __str__(self) -> str:
        if self.tipo == "artigo":
            return f"Art. {self.numero}"
        elif self.tipo == "paragrafo":
            return f"§ {self.numero}"
        elif self.tipo == "inciso":
            return f"Inciso {self.numero}"
        elif self.tipo == "alinea":
            return f"Alínea {self.numero}"
        else:
            return f"{self.get_tipo_display()} {self.numero}"

    def _validate_parent_hierarchy(self):
        """Reject self-parenting, cross-norma parents, and cycles on row saves."""
        from django.core.exceptions import ValidationError

        if not self.dispositivo_pai_id:
            return
        if self.pk and self.dispositivo_pai_id == self.pk:
            raise ValidationError(
                {"dispositivo_pai": "Um dispositivo não pode ser pai de si mesmo."}
            )
        parent = self.dispositivo_pai
        if parent is None or parent.pk is None:
            raise ValidationError(
                {"dispositivo_pai": "O dispositivo pai precisa estar persistido."}
            )
        if parent.norma_id != self.norma_id:
            raise ValidationError({"dispositivo_pai": "O pai deve pertencer à mesma norma."})

        visited = {self.pk} if self.pk else set()
        current = parent
        while current is not None:
            if current.pk in visited:
                raise ValidationError({"dispositivo_pai": "A hierarquia contém um ciclo."})
            visited.add(current.pk)
            parent_id = current.dispositivo_pai_id
            if not parent_id:
                break
            current = (
                Dispositivo.objects.filter(pk=parent_id)
                .only("id", "norma_id", "dispositivo_pai_id")
                .first()
            )
            if current is not None and current.norma_id != self.norma_id:
                raise ValidationError({"dispositivo_pai": "A cadeia de pais cruza normas."})

    def save(self, *args, **kwargs):
        self._validate_parent_hierarchy()
        return super().save(*args, **kwargs)

    def get_caminho_completo(self) -> str:
        """
        Retorna o caminho hierárquico completo do dispositivo.

        Utiliza o campo materializado `caminho` quando disponível (O(1)),
        com fallback para computação dinâmica caso ainda não preenchido.
        Exemplo: "Art. 1º > § 2º > Inciso III > Alínea b"
        """
        if self.caminho:
            return self.caminho

        caminho = [str(self)]
        visited = {self.pk} if self.pk else set()
        pai = self.dispositivo_pai

        while pai and len(visited) < 64:
            if pai.pk in visited:
                caminho.insert(0, "[ciclo hierárquico detectado]")
                break
            visited.add(pai.pk)
            caminho.insert(0, str(pai))
            pai = pai.dispositivo_pai
        if pai and len(visited) >= 64:
            caminho.insert(0, "[limite hierárquico excedido]")

        return " > ".join(caminho)

    def get_nivel(self) -> int:
        """
        Retorna o nível hierárquico do dispositivo (0 = raiz).

        Utiliza o campo materializado `nivel` quando disponível,
        com fallback para computação dinâmica.
        """
        if self.nivel is not None and self.nivel > 0:
            return self.nivel

        nivel = 0
        visited = {self.pk} if self.pk else set()
        pai = self.dispositivo_pai

        while pai and len(visited) < 64:
            if pai.pk in visited:
                return nivel
            visited.add(pai.pk)
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
        ("REVOGA", "Revogação"),  # Revokes/annuls
        ("ALTERA", "Alteração"),  # Modifies/changes
        ("ADICIONA", "Adição"),  # Adds new content
        ("SUBSTITUI", "Substituição"),  # Replaces
        ("REGULAMENTA", "Regulamentação"),  # Regulates
        ("REFERENCIA", "Referência"),  # Generic reference
    ]

    # Source: the dispositivo that causes the change
    dispositivo_fonte = models.ForeignKey(
        Dispositivo,
        on_delete=models.CASCADE,
        related_name="alteracoes_causadas",
        verbose_name="Dispositivo Fonte",
        help_text="Dispositivo que origina a alteração",
    )

    # Action type
    acao = models.CharField(
        max_length=20,
        choices=ACAO_CHOICES,
        verbose_name="Ação",
        db_index=True,
        help_text="Tipo de ação legal (revoga, altera, etc.)",
    )

    # Raw text of the reference (for auditing)
    target_text = models.CharField(
        max_length=500,
        verbose_name="Texto da Referência",
        help_text='Texto bruto da referência extraída (ex: "o Art. 5º da Lei 123/2020")',
    )

    # Target norma (if identified)
    norma_alvo = models.ForeignKey(
        Norma,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="alteracoes_recebidas",
        verbose_name="Norma Alvo",
        help_text="Norma que é alvo da alteração (se identificada)",
    )

    # Target dispositivo (if identified within same norma or linked norma)
    dispositivo_alvo = models.ForeignKey(
        Dispositivo,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="alteracoes_recebidas",
        verbose_name="Dispositivo Alvo",
        help_text="Dispositivo específico que é alvo da alteração",
    )

    # Extraction metadata
    extraction_confidence = models.FloatField(
        verbose_name="Confiança da Extração",
        default=0.0,
        help_text="Confiança do NER na extração (0-1)",
    )

    extraction_method = models.CharField(
        max_length=50,
        verbose_name="Método de Extração",
        default="regex",
        help_text="Método usado para extração (regex, spacy, bert, etc.)",
    )

    # Parsed components (for complex references)
    referencia_tipo = models.CharField(
        max_length=50,
        verbose_name="Tipo Referenciado",
        blank=True,
        help_text="Tipo do elemento referenciado (artigo, parágrafo, lei, etc.)",
    )

    referencia_numero = models.CharField(
        max_length=50,
        verbose_name="Número Referenciado",
        blank=True,
        help_text='Número do elemento referenciado (ex: "5º", "123/2020")',
    )

    # Status tracking
    validado = models.BooleanField(
        default=False,
        verbose_name="Validado",
        help_text="Se a referência foi validada/confirmada manualmente",
    )
    revision_fingerprint = models.CharField(
        max_length=64,
        blank=True,
        db_index=True,
        help_text="Identidade da evidência e da versão do extrator desta revisão.",
    )
    provenance_json = models.JSONField(
        default=dict,
        blank=True,
        help_text="Proveniência da extração, sem credenciais ou dados de requisição.",
    )
    target_reference_json = models.JSONField(
        default=dict,
        blank=True,
        help_text="Candidato tipado de identidade/alvo; não constitui validação jurídica.",
    )
    evidence_json = models.JSONField(
        default=dict,
        blank=True,
        help_text="Citação literal e spans da extração que sustentam o evento candidato.",
    )
    effective_on = models.DateField(null=True, blank=True, db_index=True)
    effective_date_status = models.CharField(
        max_length=16,
        choices=[("unknown", "Desconhecida"), ("candidate", "Candidata"), ("confirmed", "Confirmada")],
        default="unknown",
        db_index=True,
    )
    effective_date_basis = models.JSONField(default=dict, blank=True)
    review_revision = models.ForeignKey(
        "legislation.RevisaoJuridica",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="eventos_revisados",
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Evento encontrado na extração atual; revisões antigas são preservadas.",
    )

    class Meta:
        verbose_name = "Evento de Alteração"
        verbose_name_plural = "Eventos de Alteração"
        ordering = ["dispositivo_fonte__norma", "dispositivo_fonte__ordem"]
        indexes = [
            models.Index(fields=["dispositivo_fonte", "acao"]),
            models.Index(fields=["norma_alvo"]),
            models.Index(fields=["dispositivo_alvo"]),
            models.Index(fields=["acao"]),
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


class Collection(TimeStampedModel):
    """Authenticated user's curated set of norms for recurring legal work."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="jurix_collections")
    name = models.CharField(max_length=120)
    description = models.CharField(max_length=500, blank=True)
    normas = models.ManyToManyField(Norma, related_name="collections", blank=True)

    class Meta:
        ordering = ["-updated_at", "name"]
        constraints = [
            models.UniqueConstraint(fields=["user", "name"], name="unique_collection_per_user")
        ]

    def __str__(self) -> str:
        return self.name


class ChatSession(TimeStampedModel):
    """
    Model for storing chat conversation sessions.

    Each session represents a conversation between a user and the chatbot.
    Sessions are linked to authenticated users for persistence.
    """

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="chat_sessions",
        verbose_name="Usuário",
        help_text="Usuário dono desta sessão de conversa",
    )

    title = models.CharField(
        max_length=200,
        verbose_name="Título",
        blank=True,
        help_text="Título da sessão (gerado a partir da primeira pergunta ou manual)",
    )

    slug = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        verbose_name="Slug",
        help_text="Identificador único da sessão para URL (ex: abc123def456)",
        blank=True,
        null=True,
    )

    is_active = models.BooleanField(
        default=True, verbose_name="Ativa", help_text="Se esta sessão está atualmente ativa"
    )
    is_pinned = models.BooleanField(
        default=False,
        verbose_name="Fixada",
        help_text="Se esta conversa deve permanecer no topo do histórico do usuário",
    )

    class Meta:
        verbose_name = "Sessão de Chat"
        verbose_name_plural = "Sessões de Chat"
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["user", "-updated_at"]),
            models.Index(fields=["is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.title or 'Conversa sem título'} - {self.user.username}"

    def get_last_message_preview(self) -> str:
        """Retorna preview da primeira pergunta do usuário da sessão."""
        first_user_msg = self.messages.filter(role="user").order_by("created_at").first()
        if first_user_msg:
            preview = first_user_msg.content[:50] + (
                "..." if len(first_user_msg.content) > 50 else ""
            )
            return preview
        return ""

    SLUG_LENGTH = 12
    SLUG_MAX_ATTEMPTS = 10

    def generate_slug(self) -> str:
        """
        Random 12-character slug (Gemini style, e.g. 'de2a906759f920b3'), unique among sessions.

        Retries on collision; the unique constraint remains the final guard against a race.
        """
        import secrets
        import string

        alphabet = string.ascii_lowercase + string.digits
        for _ in range(self.SLUG_MAX_ATTEMPTS):
            slug = "".join(secrets.choice(alphabet) for _ in range(self.SLUG_LENGTH))
            if not ChatSession.objects.filter(slug=slug).exists():
                return slug
        raise RuntimeError("Could not generate a unique chat session slug")

    def save(self, *args, **kwargs):
        """Save the session, generating its slug on first save (or if it was cleared)."""
        if not self.slug:
            self.slug = self.generate_slug()
            update_fields = kwargs.get("update_fields")
            if update_fields is not None and "slug" not in update_fields:
                kwargs["update_fields"] = [*update_fields, "slug"]
        super().save(*args, **kwargs)


class ChatTurn(TimeStampedModel):
    """Idempotency and lifecycle record for an authenticated client chat turn."""

    STATE_CHOICES = [
        ("reserved", "Reservado"),
        ("in_progress", "Em andamento"),
        ("completed", "Concluído"),
        ("failed", "Falhou"),
        ("cancelled", "Cancelado"),
        ("interrupted", "Interrompido"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="chat_turns")
    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name="turns",
        null=True,
        blank=True,
    )
    retry_of = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        related_name="retries",
        null=True,
        blank=True,
    )
    client_session_id = models.CharField(max_length=80)
    client_turn_id = models.UUIDField()
    payload_digest = models.CharField(max_length=64)
    state = models.CharField(max_length=16, choices=STATE_CHOICES, default="reserved")

    class Meta:
        indexes = [models.Index(fields=["user", "state", "updated_at"])]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "client_session_id", "client_turn_id"],
                name="unique_chat_turn_client_identity",
            )
        ]


class ChatMessage(TimeStampedModel):
    """
    Model for storing individual chat messages within a session.

    Stores both user questions and assistant responses with their sources.
    """

    ROLE_CHOICES = [
        ("user", "Usuário"),
        ("assistant", "Assistente"),
    ]

    session = models.ForeignKey(
        ChatSession,
        on_delete=models.CASCADE,
        related_name="messages",
        verbose_name="Sessão",
        help_text="Sessão de chat à qual esta mensagem pertence",
    )

    turn = models.ForeignKey(
        ChatTurn,
        on_delete=models.SET_NULL,
        related_name="messages",
        null=True,
        blank=True,
    )

    role = models.CharField(
        max_length=10,
        choices=ROLE_CHOICES,
        verbose_name="Papel",
        help_text="Papel da mensagem (usuário ou assistente)",
    )

    content = models.TextField(
        verbose_name="Conteúdo",
        help_text="Conteúdo da mensagem (pergunta do usuário ou resposta do assistente)",
    )

    # For assistant messages: store sources as JSON
    sources_json = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Fontes",
        help_text="Lista de fontes citadas na resposta (JSON)",
    )

    # Metadata for assistant responses
    metadata_json = models.JSONField(
        default=dict,
        blank=True,
        verbose_name="Metadados",
        help_text="Metadados da resposta (modelo usado, confidence, etc.)",
    )

    class Meta:
        verbose_name = "Mensagem de Chat"
        verbose_name_plural = "Mensagens de Chat"
        ordering = ["session", "created_at"]
        indexes = [
            models.Index(fields=["session", "created_at"]),
            models.Index(fields=["role"]),
        ]

    def __str__(self) -> str:
        preview = self.content[:50] + ("..." if len(self.content) > 50 else "")
        return f"{self.get_role_display()}: {preview}"


# Explicit imports register models defined in cohesive modules without introducing
# a reverse import from those modules back to this one.
from src.apps.legislation.document_models import (  # noqa: E402,F401
    DocumentoDispositivo,
    DocumentoNormativo,
    ExtracaoDocumento,
)
from src.apps.legislation.review_models import RevisaoJuridica  # noqa: E402,F401
from src.apps.legislation.topic_models import NormaTopic, Topic  # noqa: E402,F401
