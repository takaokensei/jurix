from django.contrib import admin
from django.utils.html import format_html
from .models import Norma


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

