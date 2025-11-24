from django.contrib import admin
from django.utils.html import format_html
from .models import Norma, Dispositivo, EventoAlteracao


@admin.register(Norma)
class NormaAdmin(admin.ModelAdmin):
    list_display = (
        'tipo', 'numero', 'ano', 'status_badge', 
        'data_publicacao', 'data_vigencia', 'vacatio_status', 'created_at'
    )
    list_filter = ('tipo', 'ano', 'status', 'needs_review', 'data_publicacao')
    search_fields = ('numero', 'ementa', 'tipo', 'sapl_id')
    ordering = ('-ano', '-numero')
    date_hierarchy = 'data_publicacao'
    readonly_fields = ('created_at', 'updated_at', 'sapl_metadata')
    
    fieldsets = (
        ('Identificação', {
            'fields': ('tipo', 'numero', 'ano', 'ementa', 'observacao')
        }),
        ('Datas', {
            'fields': ('data_publicacao', 'data_vigencia')
        }),
        ('Conteúdo', {
            'fields': ('texto_original', 'pdf_url', 'pdf_path')
        }),
        ('Integração SAPL', {
            'fields': ('sapl_id', 'sapl_url', 'sapl_metadata'),
            'classes': ('collapse',)
        }),
        ('Controle de Processamento', {
            'fields': ('status', 'needs_review', 'processing_error'),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def status_badge(self, obj):
        """Exibe badge colorido para o status."""
        colors = {
            'pending': '#6c757d',
            'pdf_downloaded': '#17a2b8',
            'ocr_processing': '#ffc107',
            'ocr_completed': '#28a745',
            'nlp_processing': '#007bff',
            'ready': '#28a745',
            'failed': '#dc3545',
        }
        color = colors.get(obj.status, '#6c757d')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; '
            'border-radius: 3px; font-size: 11px;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_badge.short_description = 'Status'
    
    def vacatio_status(self, obj):
        """Indica se a norma está em vacatio legis."""
        if obj.is_em_vacatio_legis():
            return format_html(
                '<span style="color: #ff6600; font-weight: bold;">⚠️ Vacatio Legis</span>'
            )
        return '✓'
    vacatio_status.short_description = 'Vigência'
    
    actions = ['marcar_para_revisao', 'resetar_status']
    
    def marcar_para_revisao(self, request, queryset):
        """Marca normas selecionadas para revisão manual."""
        count = queryset.update(needs_review=True)
        self.message_user(request, f'{count} norma(s) marcada(s) para revisão.')
    marcar_para_revisao.short_description = 'Marcar para revisão'
    
    def resetar_status(self, request, queryset):
        """Reseta o status para 'pending'."""
        count = queryset.update(status='pending', needs_review=False, processing_error='')
        self.message_user(request, f'{count} norma(s) resetada(s).')
    resetar_status.short_description = 'Resetar status'


@admin.register(Dispositivo)
class DispositivoAdmin(admin.ModelAdmin):
    list_display = ('get_identifier', 'norma', 'tipo', 'numero', 'ordem', 'get_nivel_display')
    list_filter = ('tipo', 'norma__tipo', 'norma__ano')
    search_fields = ('texto', 'numero', 'norma__numero', 'norma__ementa')
    ordering = ('norma', 'ordem')
    raw_id_fields = ('norma', 'dispositivo_pai')
    
    fieldsets = (
        ('Identificação', {
            'fields': ('norma', 'tipo', 'numero', 'ordem')
        }),
        ('Hierarquia', {
            'fields': ('dispositivo_pai',)
        }),
        ('Conteúdo', {
            'fields': ('texto',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    readonly_fields = ('created_at', 'updated_at')
    
    def get_identifier(self, obj):
        """Retorna identificador curto do dispositivo."""
        return obj.get_full_identifier()
    get_identifier.short_description = 'Dispositivo'
    
    def get_nivel_display(self, obj):
        """Exibe o nível hierárquico."""
        nivel = obj.get_nivel()
        return f"{'  ' * nivel}Nível {nivel}"
    get_nivel_display.short_description = 'Nível'


@admin.register(EventoAlteracao)
class EventoAlteracaoAdmin(admin.ModelAdmin):
    list_display = (
        'get_fonte_display', 'acao', 'target_text_short', 
        'norma_alvo', 'extraction_confidence', 'validado', 'created_at'
    )
    list_filter = ('acao', 'validado', 'extraction_method', 'dispositivo_fonte__norma__tipo')
    search_fields = (
        'target_text', 'dispositivo_fonte__texto', 
        'norma_alvo__numero', 'norma_alvo__ementa'
    )
    ordering = ('-created_at',)
    raw_id_fields = ('dispositivo_fonte', 'norma_alvo', 'dispositivo_alvo')
    
    fieldsets = (
        ('Evento', {
            'fields': ('dispositivo_fonte', 'acao', 'target_text')
        }),
        ('Alvos Identificados', {
            'fields': ('norma_alvo', 'dispositivo_alvo')
        }),
        ('Extração Detalhada', {
            'fields': (
                'referencia_tipo', 'referencia_numero', 
                'extraction_confidence', 'extraction_method'
            ),
            'classes': ('collapse',)
        }),
        ('Validação', {
            'fields': ('validado',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    readonly_fields = ('created_at', 'updated_at')
    
    actions = ['marcar_validado', 'marcar_nao_validado']
    
    def get_fonte_display(self, obj):
        """Exibe fonte de forma resumida."""
        fonte = obj.dispositivo_fonte
        return f"{fonte.norma.tipo} {fonte.norma.numero}/{fonte.norma.ano} - {fonte.get_full_identifier()}"
    get_fonte_display.short_description = 'Fonte'
    
    def target_text_short(self, obj):
        """Exibe target_text truncado."""
        if len(obj.target_text) > 50:
            return obj.target_text[:50] + '...'
        return obj.target_text
    target_text_short.short_description = 'Referência'
    
    def marcar_validado(self, request, queryset):
        """Marca eventos como validados."""
        count = queryset.update(validado=True)
        self.message_user(request, f'{count} evento(s) marcado(s) como validado.')
    marcar_validado.short_description = 'Marcar como validado'
    
    def marcar_nao_validado(self, request, queryset):
        """Marca eventos como não validados."""
        count = queryset.update(validado=False)
        self.message_user(request, f'{count} evento(s) marcado(s) como não validado.')
    marcar_nao_validado.short_description = 'Marcar como não validado'

