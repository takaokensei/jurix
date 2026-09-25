"""
Resolving WHICH dispositivo an alteration event targets (audit P0.3, part 2).

EventoAlteracao.dispositivo_alvo is never filled by the ingestion, so REVOGA/ALTERA used to be
reported as unresolved forever. The resolver fills it in memory at consolidation time, but only
when the reference is unambiguous: in a legal text, applying the WRONG revocation is worse than
reporting an unresolved one. Every guard below comes from a case the NER really produces.
"""

from datetime import date
from types import SimpleNamespace as NS

from src.processing.consolidation_engine import ConsolidationEngine
from src.processing.target_resolver import article_key, resolve_targets

NORMA_ALVO = NS(
    id=1,
    tipo="Lei",
    numero="123",
    ano=2020,
    ementa="",
    texto_original="",
    data_publicacao=date(2020, 1, 1),
    data_vigencia=None,
)
NORMA_ALVO.__str__ = lambda self=None: "Lei 123/2020"


class Disp(NS):
    def __str__(self):
        return f"Art. {self.numero}" if self.tipo == "artigo" else f"§ {self.numero}"


def art(id_, numero, texto="Texto.", pai=None, ordem=None, tipo="artigo"):
    return Disp(
        id=id_,
        tipo=tipo,
        numero=numero,
        texto=texto,
        dispositivo_pai_id=pai,
        ordem=ordem or id_,
        norma=NORMA_ALVO,
    )


def evento(
    id_,
    acao,
    tipo,
    numero,
    fonte_id=100,
    fonte_texto="Fica revogado o art. 5º da Lei nº 123/2020.",
    alvo=None,
    data=date(2021, 5, 1),
    norma_num=200,
):
    norma_fonte = NS(
        tipo="Lei", numero=str(norma_num), ano=data.year, data_publicacao=data, data_vigencia=data
    )
    fonte = NS(id=fonte_id, norma=norma_fonte, texto=fonte_texto, ordem=1)
    return NS(
        id=id_,
        acao=acao,
        referencia_tipo=tipo,
        referencia_numero=numero,
        target_text=f"art. {numero}" if tipo == "artigo" else numero,
        dispositivo_alvo=alvo,
        dispositivo_fonte=fonte,
        dispositivo_fonte_id=fonte_id,
    )


DISPS = [
    art(1, "1º"),
    art(2, "5º", "Prazo antigo."),
    art(3, "5º-A"),
    art(4, "9º"),
    art(5, "2º", tipo="paragrafo", pai=2, ordem=2.5),
]


def resolved(res, ev_id):
    return getattr(res[ev_id].dispositivo, "id", None), res[ev_id].reason


class TestArticleKey:
    def test_parsing(self):
        assert (
            article_key("5º") == (5, "")
            and article_key("5º-A") == (5, "A")
            and article_key("10") == (10, "")
        )
        assert article_key("5º") < article_key("5º-A") < article_key("6º")
        assert article_key("abc") is None and article_key(None) is None


class TestResolutionOfPlainArticles:
    def test_revoked_article_is_found_by_number(self):
        ev = evento(1, "REVOGA", "artigo", "5º")
        assert resolved(resolve_targets([ev], DISPS), 1) == (2, "")

    def test_suffixed_article_is_not_confused_with_its_base(self):
        assert resolved(resolve_targets([evento(1, "REVOGA", "artigo", "5º-A")], DISPS), 1)[0] == 3

    def test_several_plain_articles_in_one_sentence_all_resolve(self):
        text = "Revogam-se o art. 5º e o art. 9º da Lei nº 123/2020."
        evs = [
            evento(1, "REVOGA", "artigo", "5º", fonte_texto=text),
            evento(2, "REVOGA", "artigo", "9º", fonte_texto=text),
        ]
        res = resolve_targets(evs, DISPS)
        assert (resolved(res, 1)[0], resolved(res, 2)[0]) == (2, 4)

    def test_article_missing_from_the_target_norma_is_unresolved_with_a_reason(self):
        dispositivo, reason = resolved(
            resolve_targets([evento(1, "REVOGA", "artigo", "77º")], DISPS), 1
        )
        assert dispositivo is None and "não encontrado" in reason

    def test_duplicated_numbering_in_the_target_is_ambiguous(self):
        dup = DISPS + [art(9, "5º", "Outro texto com o mesmo número.")]
        dispositivo, reason = resolved(
            resolve_targets([evento(1, "REVOGA", "artigo", "5º")], dup), 1
        )
        assert dispositivo is None and "duplicad" in reason

    def test_only_top_level_articles_are_candidates_never_a_paragraph_with_the_same_number(self):
        only_par = [art(5, "5º", tipo="paragrafo", pai=1)]
        assert (
            resolved(resolve_targets([evento(1, "REVOGA", "artigo", "5º")], only_par), 1)[0] is None
        )


class TestGuardsAgainstWrongRevocations:
    def test_paragraph_of_an_article_never_revokes_the_whole_article(self):
        """'Fica revogado o § 2º do art. 5º' makes the NER emit BOTH an artigo and a paragrafo event."""
        text = "Fica revogado o § 2º do art. 5º da Lei nº 123/2020."
        evs = [
            evento(1, "REVOGA", "artigo", "5º", fonte_texto=text),
            evento(2, "REVOGA", "paragrafo", "2º", fonte_texto=text),
        ]
        res = resolve_targets(evs, DISPS)
        assert resolved(res, 1)[0] is None and resolved(res, 2)[0] is None
        assert "hierárquica" in res[1].reason and "hierárquica" in res[2].reason

    def test_inciso_and_alinea_references_are_not_resolved(self):
        text = "Ficam revogados o parágrafo único do art. 7º e o inciso II do art. 9º da Lei nº 123/2020."
        evs = [
            evento(1, "REVOGA", "artigo", "9º", fonte_texto=text),
            evento(2, "REVOGA", "inciso", "II", fonte_texto=text),
        ]
        assert all(r.dispositivo is None for r in resolve_targets(evs, DISPS).values())

    def test_groups_are_per_source_dispositivo_and_action(self):
        """An unrelated plain 'revoga o art. 9º' elsewhere must still resolve."""
        hier = [
            evento(1, "REVOGA", "artigo", "5º", fonte_id=100),
            evento(2, "REVOGA", "paragrafo", "2º", fonte_id=100),
        ]
        plain = [
            evento(
                3,
                "REVOGA",
                "artigo",
                "9º",
                fonte_id=101,
                fonte_texto="Fica revogado o art. 9º da Lei nº 123/2020.",
            )
        ]
        res = resolve_targets(hier + plain, DISPS)
        assert res[1].dispositivo is None and resolved(res, 3)[0] == 4

    def test_text_that_cites_two_norms_is_ambiguous(self):
        text = "Altera o art. 3º da Lei nº 123/2020 e revoga o art. 8º da Lei nº 456/2019."
        res = resolve_targets([evento(1, "REVOGA", "artigo", "9º", fonte_texto=text)], DISPS)
        assert res[1].dispositivo is None and "mais de uma norma" in res[1].reason

    def test_this_law_next_to_another_norm_is_ambiguous(self):
        """'art. 5º da Lei 7/2019, e o art. 9º desta Lei': the NER attributes art. 9º to Lei 7."""
        text = "Fica revogado o art. 5º da Lei nº 7/2019, e o art. 9º desta Lei."
        res = resolve_targets([evento(1, "REVOGA", "artigo", "9º", fonte_texto=text)], DISPS)
        assert res[1].dispositivo is None and "desta Lei" in res[1].reason

    def test_the_same_norma_cited_twice_is_not_ambiguous(self):
        text = "Fica revogado o art. 5º da Lei nº 123/2020, conforme a Lei nº 123/2020."
        assert (
            resolved(
                resolve_targets([evento(1, "REVOGA", "artigo", "5º", fonte_texto=text)], DISPS), 1
            )[0]
            == 2
        )

    def test_self_reference_without_any_other_norma_is_fine(self):
        text = "Fica revogado o art. 9º desta Lei."
        assert (
            resolved(
                resolve_targets([evento(1, "REVOGA", "artigo", "9º", fonte_texto=text)], DISPS), 1
            )[0]
            == 4
        )

    def test_events_with_an_explicit_target_and_non_applying_actions_are_left_alone(self):
        already = evento(1, "REVOGA", "artigo", "5º", alvo=DISPS[1])
        info = evento(2, "REFERENCIA", "artigo", "5º")
        assert resolve_targets([already, info], DISPS) == {}


# ------------------------------------------------------------------ engine integration
def run_engine(eventos, dispositivos=None):
    eng = ConsolidationEngine(NORMA_ALVO)
    eng.dispositivos = dispositivos or DISPS
    eng.eventos = sorted(eventos, key=ConsolidationEngine._evento_sort_key)
    eng._process_eventos()
    return eng, eng._build_consolidated_text()


class TestEngineAppliesResolvedEvents:
    def test_revocation_is_applied_and_hides_the_articles_subtree(self):
        eng, text = run_engine([evento(1, "REVOGA", "artigo", "5º")])
        st = eng.get_statistics()
        assert (
            st["events_applied"] == 1 and st["events_unresolved"] == 0 and st["revoked_count"] == 1
        )
        assert "Art. 5º (Revogado pela Lei nº 200/2021)" in text
        assert "Prazo antigo." not in text
        assert "Art. 1º" in text and "Art. 9º" in text  # neighbours untouched

    def test_hierarchical_reference_is_reported_not_applied(self):
        text = "Fica revogado o § 2º do art. 5º da Lei nº 123/2020."
        eng, out = run_engine(
            [
                evento(1, "REVOGA", "artigo", "5º", fonte_texto=text),
                evento(2, "REVOGA", "paragrafo", "2º", fonte_texto=text),
            ]
        )
        st = eng.get_statistics()
        assert st["revoked_count"] == 0 and st["events_applied"] == 0
        assert st["events_unresolved"] == 2 and st["needs_review"] is True
        assert "Prazo antigo." in out  # Art. 5º is still in force
        assert "hierárquica" in out

    def test_duplicate_events_from_one_sentence_are_counted_once(self):
        """The NER emits ALTERA twice (the instruction and the quoted 'Art. 5º')."""
        text = "Altera o art. 5º da Lei nº 123/2020: “Art. 5º O prazo é de 30 dias.”"
        eng, out = run_engine(
            [
                evento(1, "ALTERA", "artigo", "5º", fonte_texto=text),
                evento(2, "ALTERA", "artigo", "5º", fonte_texto=text),
            ]
        )
        st = eng.get_statistics()
        assert st["events_applied"] == 1 and st["altered_count"] == 1
        assert "Art. 5º O prazo é de 30 dias. (Redação dada pela Lei nº 200/2021)" in out
        assert "Prazo antigo." not in out
        assert "Altera o art. 5º" not in out  # the instruction sentence must never become the text

    def test_alteration_without_extractable_wording_is_not_applied(self):
        text = "Altera a redação do art. 5º da Lei nº 123/2020, conforme anexo."
        eng, out = run_engine([evento(1, "ALTERA", "artigo", "5º", fonte_texto=text)])
        st = eng.get_statistics()
        assert st["altered_count"] == 0 and st["events_unresolved"] == 1
        assert "Prazo antigo." in out and "redação não extraída" in out

    def test_alteration_whose_wording_carries_sub_items_is_not_applied(self):
        """Applying it would duplicate the paragraphs the article already has."""
        text = "Altera o art. 5º da Lei nº 123/2020: “Art. 5º Caput novo. § 1º Novo parágrafo.”"
        eng, out = run_engine([evento(1, "ALTERA", "artigo", "5º", fonte_texto=text)])
        assert eng.get_statistics()["altered_count"] == 0 and "subdispositivos" in out

    def test_later_alteration_wins_over_an_earlier_one(self):
        e1 = evento(
            1,
            "ALTERA",
            "artigo",
            "5º",
            fonte_id=100,
            data=date(2021, 1, 1),
            norma_num=200,
            fonte_texto="Altera o art. 5º da Lei nº 123/2020: “Art. 5º Versão dois.”",
        )
        e2 = evento(
            2,
            "ALTERA",
            "artigo",
            "5º",
            fonte_id=101,
            data=date(2022, 1, 1),
            norma_num=300,
            fonte_texto="Altera o art. 5º da Lei nº 123/2020: “Art. 5º Versão três.”",
        )
        _, out = run_engine([e2, e1])
        assert "Versão três." in out and "Versão dois." not in out and "Lei nº 300/2022" in out

    def test_revocation_after_alteration_wins_and_alteration_after_revocation_restores(self):
        alt = evento(
            1,
            "ALTERA",
            "artigo",
            "5º",
            fonte_id=100,
            data=date(2021, 1, 1),
            norma_num=200,
            fonte_texto="Altera o art. 5º da Lei nº 123/2020: “Art. 5º Novo.”",
        )
        rev = evento(
            2, "REVOGA", "artigo", "5º", fonte_id=101, data=date(2022, 1, 1), norma_num=300
        )
        eng, out = run_engine([alt, rev])
        assert eng.get_statistics()["revoked_count"] == 1 and "Novo." not in out
        eng, out = run_engine(
            [
                rev,
                evento(
                    3,
                    "ALTERA",
                    "artigo",
                    "5º",
                    fonte_id=102,
                    data=date(2023, 1, 1),
                    norma_num=400,
                    fonte_texto="Altera o art. 5º da Lei nº 123/2020: “Art. 5º Restaurado.”",
                ),
            ]
        )
        assert eng.get_statistics()["revoked_count"] == 0 and "Restaurado." in out

    def test_output_is_deterministic_whatever_the_input_order(self):
        evs = [
            evento(1, "REVOGA", "artigo", "9º", fonte_id=100),
            evento(
                2,
                "ALTERA",
                "artigo",
                "5º",
                fonte_id=101,
                fonte_texto="Altera o art. 5º da Lei nº 123/2020: “Art. 5º Novo.”",
                data=date(2022, 1, 1),
                norma_num=300,
            ),
        ]
        assert run_engine(evs)[1] == run_engine(list(reversed(evs)))[1]

    def test_unresolved_duplicates_are_listed_once(self):
        text = "Fica revogado o art. 77º da Lei nº 123/2020."
        eng, out = run_engine(
            [
                evento(1, "REVOGA", "artigo", "77º", fonte_texto=text),
                evento(2, "REVOGA", "artigo", "77º", fonte_texto=text),
            ]
        )
        assert eng.get_statistics()["events_unresolved"] == 1


# ------------------------------------------------------------------ lists and ranges
RANGE_DISPS = [
    art(1, "1º"),
    art(2, "5º", "cinco"),
    art(3, "5º-A", "cinco-A"),
    art(4, "6º", "seis"),
    art(5, "7º", "sete"),
    art(6, "8º", "oito"),
    art(7, "9º", "nove"),
]


class TestArticleRanges:
    def test_spec_parsing(self):
        from src.processing.target_resolver import article_spec

        assert article_spec("5º") == ("single", (5, ""))
        assert article_spec("5º a 8º") == ("range", 5, 8)
        assert article_spec("10 a 12") == ("range", 10, 12)
        assert article_spec("9º a 5º") is None and article_spec("5º-A a 8º") is None
        assert article_spec("1 a 9999") is None and article_spec("abc") is None

    def test_range_covers_suffixed_articles_between_its_endpoints(self):
        """'arts. 5º a 8º' includes 5º-A: leaving it in force would be a silent error."""
        ev = evento(
            1,
            "REVOGA",
            "artigo",
            "5º a 8º",
            fonte_texto="Ficam revogados os arts. 5º a 8º da Lei nº 123/2020.",
        )
        res = resolve_targets([ev], RANGE_DISPS)[1]
        assert [d.numero for d in res.dispositivos] == ["5º", "5º-A", "6º", "7º", "8º"]
        assert res.reason == ""

    def test_range_only_supported_for_revocation(self):
        ev = evento(1, "ALTERA", "artigo", "5º a 8º")
        res = resolve_targets([ev], RANGE_DISPS)[1]
        assert not res.dispositivos and "intervalo" in res.reason

    def test_range_with_no_article_in_it_is_unresolved(self):
        res = resolve_targets([evento(1, "REVOGA", "artigo", "20 a 30")], RANGE_DISPS)[1]
        assert not res.dispositivos and "não encontrado" in res.reason

    def test_range_touching_duplicated_numbering_is_unresolved(self):
        dup = RANGE_DISPS + [art(99, "6º", "seis de novo")]
        res = resolve_targets([evento(1, "REVOGA", "artigo", "5º a 8º")], dup)[1]
        assert not res.dispositivos and "duplicad" in res.reason

    def test_inverted_range_is_refused(self):
        res = resolve_targets([evento(1, "REVOGA", "artigo", "9º a 5º")], RANGE_DISPS)[1]
        assert not res.dispositivos and "inválido" in res.reason

    def test_single_resolution_keeps_the_one_dispositivo_property(self):
        res = resolve_targets([evento(1, "REVOGA", "artigo", "6º")], RANGE_DISPS)[1]
        assert res.dispositivo.id == 4 and len(res.dispositivos) == 1


class TestEngineWithRanges:
    def test_range_revocation_hides_every_article_in_it_and_counts_one_event(self):
        ev = evento(
            1,
            "REVOGA",
            "artigo",
            "5º a 8º",
            fonte_texto="Ficam revogados os arts. 5º a 8º da Lei nº 123/2020.",
        )
        eng, out = run_engine([ev], RANGE_DISPS)
        st = eng.get_statistics()
        assert (
            st["revoked_count"] == 5 and st["events_applied"] == 1 and st["events_unresolved"] == 0
        )
        for gone in ("cinco", "cinco-A", "seis", "sete", "oito"):
            assert gone not in out.replace("Revogado", "")
        assert "nove" in out and "Art. 1º" in out  # outside the range: untouched
        assert out.count("Revogado pela Lei nº 200/2021") == 5

    def test_sentence_with_singular_and_plural_revokes_all_listed_articles(self):
        text = "Ficam revogados o art. 5º e os arts. 7º e 8º da Lei nº 123/2020."
        evs = [
            evento(i, "REVOGA", "artigo", n, fonte_texto=text)
            for i, n in enumerate(["5º", "7º", "8º"], start=1)
        ]
        eng, out = run_engine(evs, RANGE_DISPS)
        assert (
            eng.get_statistics()["revoked_count"] == 3
            and eng.get_statistics()["events_applied"] == 3
        )
        assert "seis" in out and "nove" in out
