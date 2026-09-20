"""
Backfill Dispositivo.caminho / nivel for rows created before migration 0010.

0010 added the materialized columns but only newly segmented normas fill them.
Older rows kept caminho='' / nivel=0, so get_caminho_completo() fell back to
walking the parent chain with one query per level.

Self-contained on purpose (no imports from application code): migrations must
keep working when the application code changes. The label format mirrors
LegalTextParser.build_hierarchy so old and new rows are indistinguishable.
"""
from django.db import migrations

BATCH_SIZE = 1000
CAMINHO_MAX_LENGTH = 500  # Dispositivo.caminho max_length

_LABELS = {
    'artigo': 'Art. {}', 'inciso': 'Inciso {}', 'alinea': 'Alínea {}', 'item': 'Item {}',
    'capitulo': 'Capítulo {}', 'secao': 'Seção {}', 'subsecao': 'Subseção {}',
    'titulo': 'Título {}', 'livro': 'Livro {}', 'parte': 'Parte {}',
}


def _label(tipo, numero):
    numero = (numero or '').strip()
    if tipo == 'paragrafo':
        return 'Parágrafo único' if numero.lower() in ('único', 'unico') else f'§ {numero}'
    if tipo in _LABELS:
        return _LABELS[tipo].format(numero)
    return f'{tipo.title()} {numero}'.strip()


def backfill_caminho_nivel(apps, schema_editor):
    Dispositivo = apps.get_model('legislation', 'Dispositivo')

    # order_by() is essential: Dispositivo.Meta.ordering would leak into SELECT DISTINCT
    # and return each norma once per distinct ordering value (i.e. once per row).
    norma_ids = list(
        Dispositivo.objects.filter(caminho='').order_by()
        .values_list('norma_id', flat=True).distinct()
    )
    for norma_id in norma_ids:
        rows = {
            d.id: d
            for d in Dispositivo.objects.filter(norma_id=norma_id).only(
                'id', 'tipo', 'numero', 'dispositivo_pai_id', 'caminho', 'nivel'
            )
        }
        to_update = []
        for d in rows.values():
            if d.caminho:
                continue  # already materialized: never overwrite
            labels, seen, cur = [], set(), d
            while cur is not None and cur.id not in seen:  # `seen` guards corrupt cycles
                seen.add(cur.id)
                labels.append(_label(cur.tipo, cur.numero))
                cur = rows.get(cur.dispositivo_pai_id)
            labels.reverse()
            d.caminho = ' > '.join(labels)[:CAMINHO_MAX_LENGTH]
            d.nivel = len(labels) - 1
            to_update.append(d)
        # bulk_update does not touch auto_now fields: updated_at stays truthful
        Dispositivo.objects.bulk_update(to_update, ['caminho', 'nivel'], batch_size=BATCH_SIZE)


class Migration(migrations.Migration):

    dependencies = [
        ('legislation', '0010_dispositivo_caminho_dispositivo_nivel_and_more'),
    ]

    operations = [
        # Reverse is a no-op: the columns simply keep their (correct) values.
        migrations.RunPython(backfill_caminho_nivel, migrations.RunPython.noop),
    ]
