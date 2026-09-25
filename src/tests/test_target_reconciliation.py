from types import SimpleNamespace

from src.processing.target_reconciliation import parse_target_reference


def test_parse_target_reference_from_target_text():
    event = SimpleNamespace(
        referencia_tipo=None,
        referencia_numero=None,
        target_text='altera a Lei nº 8.206/2026',
        norma=SimpleNamespace(ano=2026),
    )
    ref = parse_target_reference(event)
    assert ref is not None
    assert ref.numero == '8.206'
    assert ref.ano == 2026


def test_reference_uses_source_year_when_target_has_no_year():
    event = SimpleNamespace(
        referencia_tipo='Lei',
        referencia_numero='8206',
        target_text='Lei nº 8206',
        norma=SimpleNamespace(ano=2026),
    )
    ref = parse_target_reference(event)
    assert ref is not None
    assert ref.numero == '8206'
