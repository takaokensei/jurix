from django.contrib import admin
from django.utils.html import format_html
from .models import Norma, Dispositivo, EventoAlteracao, ChatSession, ChatMessage


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
            'consolidated': '#10b981',  # green
            'ready': '#3b82f6',  # blue
            'failed': '#ef4444',  # red
            'pending': '#f59e0b',  # yellow
        }
        color = colors.get(obj.status, '#6b7280')
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; border-radius: 4px; font-size: 11px;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_badge.short_description = 'Status'
    
    def vacatio_status(self, obj):
        """Indica se está em vacatio legis."""
        if obj.is_em_vacatio_legis():
            return format_html('<span style="color: #f59e0b;">⚠️ Em vacatio legis</span>')
        return '—'
    vacatio_status.short_description = 'Vacatio Legis'


@admin.register(Dispositivo)
class DispositivoAdmin(admin.ModelAdmin):
    list_display = ('norma', 'tipo', 'numero', 'texto_preview', 'has_embedding')
    list_filter = ('tipo', 'norma__tipo', 'norma__ano')
    search_fields = ('texto', 'numero', 'norma__numero', 'norma__tipo')
    ordering = ('norma', 'ordem')
    readonly_fields = ('created_at', 'updated_at', 'embedding_generated_at')
    
    def texto_preview(self, obj):
        """Preview do texto (primeiros 100 caracteres)."""
        return obj.texto[:100] + ('...' if len(obj.texto) > 100 else '')
    texto_preview.short_description = 'Texto'
    
    def has_embedding(self, obj):
        """Indica se tem embedding."""
        return '✅' if obj.embedding else '❌'
    has_embedding.short_description = 'Embedding'


@admin.register(EventoAlteracao)
class EventoAlteracaoAdmin(admin.ModelAdmin):
    list_display = ('dispositivo_fonte', 'acao', 'norma_alvo', 'dispositivo_alvo', 'validado')
    list_filter = ('acao', 'validado', 'extraction_method')
    search_fields = ('target_text', 'dispositivo_fonte__texto', 'norma_alvo__numero')
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ('title', 'user', 'is_active', 'message_count', 'created_at', 'updated_at')
    list_filter = ('is_active', 'created_at', 'updated_at')
    search_fields = ('title', 'user__username')
    ordering = ('-updated_at',)
    readonly_fields = ('created_at', 'updated_at')
    
    def message_count(self, obj):
        """Conta mensagens na sessão."""
        return obj.messages.count()
    message_count.short_description = 'Mensagens'


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ('session', 'role', 'content_preview', 'created_at')
    list_filter = ('role', 'created_at', 'session__user')
    search_fields = ('content', 'session__title', 'session__user__username')
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at')
    
    def content_preview(self, obj):
        """Preview do conteúdo."""
        return obj.content[:100] + ('...' if len(obj.content) > 100 else '')
    content_preview.short_description = 'Conteúdo'
