from types import SimpleNamespace

from src.processing.target_resolver import resolve_targets


def _d(dispositivo_id, tipo, numero, parent=None):
    return SimpleNamespace(
        id=dispositivo_id,
        tipo=tipo,
        numero=numero,
        dispositivo_pai=parent,
        dispositivo_pai_id=getattr(parent, "id", None),
        norma_id=1,
    )


def _event(event_id, tipo, numero, texto):
    fonte = SimpleNamespace(id=900 + event_id, texto=texto)
    return SimpleNamespace(
        id=event_id,
        dispositivo_alvo=None,
        dispositivo_fonte=fonte,
        dispositivo_fonte_id=fonte.id,
        referencia_tipo=tipo,
        referencia_numero=numero,
        acao="REVOGA",
        target_text=texto,
    )


def test_resolves_nested_item_reference():
    art5 = _d(1, "artigo", "5º")
    par2 = _d(2, "paragrafo", "2º", art5)
    inc2 = _d(3, "inciso", "II", par2)
    ali_b = _d(4, "alinea", "b", inc2)
    item3 = _d(5, "item", "3", ali_b)

    text = "Revoga o item 3 da alínea b do inciso II do § 2º do art. 5º da Lei 123/2020."
    event = _event(1, "item", "3", text)

    resolved = resolve_targets([event], [art5, par2, inc2, ali_b, item3])
    assert resolved[event.id].dispositivo is item3


def test_keeps_two_references_in_their_own_articles():
    art5 = _d(1, "artigo", "5º")
    art9 = _d(10, "artigo", "9º")
    par2 = _d(2, "paragrafo", "2º", art5)
    par3 = _d(11, "paragrafo", "3º", art9)

    text = "Revoga o § 2º do art. 5º e o § 3º do art. 9º da Lei 123/2020."
    e1 = _event(1, "paragrafo", "2º", text)
    e2 = _event(2, "paragrafo", "3º", text)

    resolved = resolve_targets([e1, e2], [art5, par2, art9, par3])

    assert resolved[e1.id].dispositivo is par2
    assert resolved[e2.id].dispositivo is par3


def test_does_not_guess_when_same_reference_is_ambiguous():
    art5 = _d(1, "artigo", "5º")
    par2_a = _d(2, "paragrafo", "2º", art5)
    par2_b = _d(3, "paragrafo", "2º", art5)

    text = "Revoga o § 2º do art. 5º e o § 2º do art. 5º."
    event = _event(1, "paragrafo", "2º", text)

    resolved = resolve_targets([event], [art5, par2_a, par2_b])

    assert resolved[event.id].dispositivo is None
    assert "ambígua" in resolved[event.id].reason
