from django.contrib import admin
from .models import Norma


@admin.register(Norma)
class NormaAdmin(admin.ModelAdmin):
    list_display = ('tipo', 'numero', 'ano', 'data_publicacao', 'data_vigencia', 'created_at')
    list_filter = ('tipo', 'ano', 'data_publicacao')
    search_fields = ('numero', 'ementa', 'tipo')
    ordering = ('-ano', '-numero')
    date_hierarchy = 'data_publicacao'
    
    fieldsets = (
        ('Identificação', {
            'fields': ('tipo', 'numero', 'ano', 'ementa', 'sapl_id')
        }),
        ('Datas', {
            'fields': ('data_publicacao', 'data_vigencia')
        }),
        ('Conteúdo', {
            'fields': ('texto_original', 'pdf_url', 'pdf_path')
        }),
    )

