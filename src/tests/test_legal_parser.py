"""
Unit tests for LegalTextParser.
Covers articles, paragraphs, incisos, alíneas, structural divisions, and hierarchy.
"""
import textwrap
import pytest
from src.processing.legal_parser import LegalTextParser


@pytest.fixture
def parser():
    return LegalTextParser()


def test_extract_articles_basic(parser):
    text = textwrap.dedent("""
    Art. 1º Esta Lei institui o Código Tributário Municipal.
    
    Art. 2º O imposto é devido por pessoas físicas e jurídicas.
    
    Art. 15-A Fica criado o regime simplificado.
    """).strip()
    articles = parser.extract_articles(text)
    assert len(articles) == 3
    assert articles[0]['numero'] == '1º'
    assert 'institui o Código' in articles[0]['texto']
    assert articles[1]['numero'] == '2º'
    assert articles[2]['numero'] == '15-A'


def test_extract_paragraphs_numbered_and_unico(parser):
    text = textwrap.dedent("""
    Art. 5º O tributo incidirá anualmente.
    
    § 1º O lançamento é feito de ofício.
    
    § 2º A base de cálculo considerará o valor venal.
    
    Art. 6º A alíquota é progressiva.
    
    Parágrafo único. Nos imóveis residenciais haverá desconto.
    """).strip()
    paragraphs = parser.extract_paragraphs(text)
    assert len(paragraphs) == 3
    
    nums = [p['numero'] for p in paragraphs]
    assert '1º' in nums
    assert '2º' in nums
    assert 'único' in nums


def test_extract_incisos_and_alineas(parser):
    text = textwrap.dedent("""
    Art. 10. São isentos do tributo:
    I - templos de qualquer culto;
    II - partidos políticos;
    a) desde que mantida contabilidade regular;
    b) vedada a distribuição de renda.
    """).strip()
    all_markers = parser._find_all_markers(text)
    incisos = parser.extract_incisos(text, all_markers)
    alineas = parser.extract_alineas(text, all_markers)
    
    assert len(incisos) == 2
    assert incisos[0]['numero'] == 'I'
    assert incisos[1]['numero'] == 'II'
    
    assert len(alineas) == 2
    assert alineas[0]['numero'] == 'a'
    assert alineas[1]['numero'] == 'b'


def test_extract_divisions(parser):
    text = textwrap.dedent("""
    TÍTULO I - DOS PRINCÍPIOS FUNDAMENTAIS
    
    CAPÍTULO I - DA TRIBUTAÇÃO
    
    SEÇÃO I - DAS IMUNIDADES
    
    Art. 1º São imunes aos impostos...
    """).strip()
    divisions = parser.extract_divisions(text)
    assert len(divisions) == 3
    tipos = [d['tipo'] for d in divisions]
    assert 'titulo' in tipos
    assert 'capitulo' in tipos
    assert 'secao' in tipos


def test_parse_and_build_hierarchy_complete(parser):
    text = textwrap.dedent("""
    CAPÍTULO I - DO REGIME JURÍDICO
    
    Art. 1º O IPTU incide sobre a propriedade predial e territorial.
    
    § 1º O fato gerador ocorre no primeiro dia de cada exercício.
    
    I - para terrenos edificados;
    II - para imóveis em construção.
    
    a) com alvará expedido;
    b) sem alvará regular.
    
    Parágrafo único. Aplica-se aos imóveis urbanos.
    """).strip()
    elements = parser.parse_legal_text(text)
    hierarchy = parser.build_hierarchy(elements)
    
    assert len(hierarchy) >= 6
    
    # Check Chapter
    capitulo = hierarchy[0]
    assert capitulo['tipo'] == 'capitulo'
    assert capitulo['parent_index'] is None
    assert capitulo['nivel'] == 0
    assert 'Capítulo I' in capitulo['caminho']
    
    # Check Article (child of Chapter)
    artigo = hierarchy[1]
    assert artigo['tipo'] == 'artigo'
    assert artigo['parent_index'] == 0
    assert artigo['nivel'] == 1
    assert artigo['caminho'] == 'Capítulo I > Art. 1º'
    
    # Check § 1º (child of Article)
    p1 = hierarchy[2]
    assert p1['tipo'] == 'paragrafo'
    assert p1['parent_index'] == 1
    assert p1['nivel'] == 2
    assert p1['caminho'] == 'Capítulo I > Art. 1º > § 1º'
    
    # Check Inciso I (child of § 1º)
    inciso_i = hierarchy[3]
    assert inciso_i['tipo'] == 'inciso'
    assert inciso_i['parent_index'] == 2
    assert inciso_i['nivel'] == 3
    assert 'Capítulo I > Art. 1º > § 1º > Inciso I' == inciso_i['caminho']


def test_clean_text(parser):
    raw = "  Art.  1º   Texto com    espaços múltiplos  – traço en-dash  "
    cleaned = parser.clean_text(raw)
    assert "  " not in cleaned
    assert "–" not in cleaned
    assert cleaned.startswith("Art. 1º")


# ---------------------------------------------------------------------------
# Regression tests (audit P0.2 / P2.4)
# ---------------------------------------------------------------------------

def _flat(parser, text):
    """Parse + build hierarchy and return a compact, easy-to-assert view."""
    return [
        (e["tipo"], e["numero"], e["parent_index"], parser.clean_text(e["texto"]))
        for e in parser.build_hierarchy(parser.parse_legal_text(textwrap.dedent(text)))
    ]


def test_prose_starting_with_roman_letter_is_not_an_inciso(parser):
    """'Instituições', 'Vereadores', 'Xerox' must not become incisos I, V, X."""
    result = _flat(parser, """\
        Art. 1º Ficam autorizados os órgãos:
        Instituições públicas municipais poderão aderir.
        Vereadores e servidores terão prioridade.
        Xerox de documentos será dispensado.
        Art. 2º Vigência imediata.
    """)
    assert [r[0] for r in result] == ["artigo", "artigo"]
    # Nothing may be truncated: the prose stays inside the article text.
    assert "Instituições públicas" in result[0][3]
    assert "Vereadores e servidores" in result[0][3]
    assert "Xerox de documentos" in result[0][3]


def test_inciso_requires_explicit_separator(parser):
    """A real inciso needs '-', '–' or '.' after the roman numeral."""
    result = _flat(parser, """\
        Art. 1º Requisitos:
        I - primeiro;
        II – segundo;
        III. terceiro.
    """)
    assert [(r[0], r[1]) for r in result] == [
        ("artigo", "1º"), ("inciso", "I"), ("inciso", "II"), ("inciso", "III"),
    ]
    assert result[1][3] == "primeiro;"


def test_inciso_after_line_ending_with_year_or_law_number_is_kept(parser):
    """Previously the '\\d{4}' look-behind silently dropped inciso I."""
    result = _flat(parser, """\
        Art. 1º Aplica-se o disposto na Lei nº 8.666/1993:
        I - licitações de obras;
        II - licitações de serviços.
    """)
    assert [(r[0], r[1]) for r in result] == [
        ("artigo", "1º"), ("inciso", "I"), ("inciso", "II"),
    ]


def test_invalid_roman_numeral_is_rejected(parser):
    result = _flat(parser, """\
        Art. 1º Texto:
        IIII - não é romano válido
        VX - também não
    """)
    assert [r[0] for r in result] == ["artigo"]


def test_article_reference_broken_across_lines_is_not_a_new_article(parser):
    """'Art. 10 da Lei 123/2020 ...' (lowercase continuation) is a citation."""
    result = _flat(parser, """\
        Art. 5º Altera-se a redação conforme abaixo:
        Art. 10 da Lei 123/2020 passa a vigorar com a seguinte redação.
        Art. 6º Revogam-se as disposições em contrário.
    """)
    assert [(r[0], r[1]) for r in result] == [("artigo", "5º"), ("artigo", "6º")]
    assert "Art. 10 da Lei 123/2020" in result[0][3]


def test_numbered_items_become_children_of_their_inciso(parser):
    result = _flat(parser, """\
        Art. 1º Constituem requisitos:
        I - documentos:
        1. identidade;
        2. comprovante de residência;
        II - declaração firmada.
    """)
    assert [(r[0], r[1], r[2]) for r in result] == [
        ("artigo", "1º", None),
        ("inciso", "I", 0),
        ("item", "1", 1),
        ("item", "2", 1),
        ("inciso", "II", 0),
    ]
    assert result[2][3] == "identidade;"


def test_year_at_line_start_is_not_an_item(parser):
    result = _flat(parser, """\
        Art. 1º Aprova o plano.
        2020. Este exercício será considerado.
        Art. 2º Fim.
    """)
    assert [r[0] for r in result] == ["artigo", "artigo"]
    assert "2020. Este exercício" in result[0][3]


def test_item_caminho_is_materialized(parser):
    hier = parser.build_hierarchy(parser.parse_legal_text(textwrap.dedent("""\
        Art. 1º Requisitos:
        I - documentos:
        1. identidade;
    """)))
    item = next(e for e in hier if e["tipo"] == "item")
    assert item["caminho"] == "Art. 1º > Inciso I > Item 1"
    assert item["nivel"] == 2


# ---------------------------------------------------------------------------
# Regression tests (audit P2.4: repeated blocks from OCR)
# ---------------------------------------------------------------------------

def test_consecutive_duplicate_article_from_ocr_is_dropped(parser):
    result = _flat(parser, """\
        Art. 1º Primeiro.
        Art. 1º Primeiro.
        Art. 2º Segundo.
    """)
    assert [(r[0], r[1]) for r in result] == [("artigo", "1º"), ("artigo", "2º")]


def test_repeated_page_block_with_its_paragraphs_is_dropped_as_a_unit(parser):
    """A page repeated by the OCR must not double the paragraphs under the first article."""
    result = _flat(parser, """\
        Art. 1º Primeiro.
        § 1º Um.
        Art. 2º Segundo.
        Art. 1º Primeiro.
        § 1º Um.
        Art. 3º Terceiro.
    """)
    assert [(r[0], r[1]) for r in result] == [
        ("artigo", "1º"), ("paragrafo", "1º"), ("artigo", "2º"), ("artigo", "3º"),
    ]


def test_same_number_with_different_text_is_kept_never_silently_lost(parser):
    result = _flat(parser, """\
        Art. 1º Primeiro texto.
        Art. 1º Texto diferente, talvez um erro de OCR.
        Art. 2º Segundo.
    """)
    assert [(r[0], r[1]) for r in result] == [("artigo", "1º"), ("artigo", "1º"), ("artigo", "2º")]


def test_same_article_with_different_subtree_is_kept(parser):
    result = _flat(parser, """\
        Art. 1º Primeiro.
        § 1º Um.
        Art. 1º Primeiro.
        § 1º Outro texto.
    """)
    assert [r[0] for r in result].count("artigo") == 2


def test_repeated_numbering_of_incisos_across_articles_is_not_deduplicated(parser):
    result = _flat(parser, """\
        Art. 1º Requisitos:
        I - primeiro;
        Art. 2º Outros requisitos:
        I - primeiro;
    """)
    assert [r[0] for r in result] == ["artigo", "inciso", "artigo", "inciso"]


def test_dropping_a_duplicate_is_logged(parser):
    from unittest.mock import patch
    with patch("src.processing.legal_parser.logger") as log:
        _flat(parser, "Art. 1º A.\nArt. 1º A.\nArt. 2º B.")
    assert any("duplicate" in str(c.args[0]).lower() for c in log.warning.call_args_list)


# ---------------------------------------------------------------------------
# Structural divisions (audit P3.4) -- Título > Capítulo > Seção > Subseção > Artigo
# ---------------------------------------------------------------------------

FULL_LAW = """\
TÍTULO I - DAS DISPOSIÇÕES PRELIMINARES
CAPÍTULO I - DO OBJETO
Seção I - Das Definições
Art. 1º Esta Lei dispõe sobre X.
Subseção I - Dos Prazos
Art. 2º Os prazos são contados em dias.
CAPÍTULO II - DAS PENALIDADES
Art. 3º Aplica-se multa.
TÍTULO II - DAS DISPOSIÇÕES FINAIS
Art. 4º Revogam-se as disposições em contrário.
"""


def _paths(parser, text):
    return [(e["tipo"], e["numero"], e["caminho"], e["nivel"])
            for e in parser.build_hierarchy(parser.parse_legal_text(text))]


def test_full_division_hierarchy_paths_and_levels(parser):
    assert _paths(parser, FULL_LAW) == [
        ("titulo", "I", "Título I", 0),
        ("capitulo", "I", "Título I > Capítulo I", 1),
        ("secao", "I", "Título I > Capítulo I > Seção I", 2),
        ("artigo", "1º", "Título I > Capítulo I > Seção I > Art. 1º", 3),
        ("subsecao", "I", "Título I > Capítulo I > Seção I > Subseção I", 3),
        ("artigo", "2º", "Título I > Capítulo I > Seção I > Subseção I > Art. 2º", 4),
        ("capitulo", "II", "Título I > Capítulo II", 1),
        ("artigo", "3º", "Título I > Capítulo II > Art. 3º", 2),
        ("titulo", "II", "Título II", 0),
        ("artigo", "4º", "Título II > Art. 4º", 1),
    ]


def test_new_chapter_closes_the_previous_section_and_new_title_closes_the_chapter(parser):
    by = {(e["tipo"], e["numero"]): e for e in parser.build_hierarchy(parser.parse_legal_text(FULL_LAW))}
    hier = parser.build_hierarchy(parser.parse_legal_text(FULL_LAW))
    parent_of = lambda key: hier[by[key]["parent_index"]]["tipo"] if by[key]["parent_index"] is not None else None
    assert parent_of(("artigo", "3º")) == "capitulo"          # not the stale Seção I
    assert parent_of(("artigo", "4º")) == "titulo"            # not the stale Capítulo II
    assert by[("titulo", "II")]["parent_index"] is None


def test_division_headings_do_not_leak_into_the_previous_articles_text(parser):
    result = {(e["tipo"], e["numero"]): parser.clean_text(e["texto"])
              for e in parser.build_hierarchy(parser.parse_legal_text(FULL_LAW))}
    assert result[("artigo", "1º")] == "Esta Lei dispõe sobre X."
    assert result[("artigo", "3º")] == "Aplica-se multa."
    assert "CAPÍTULO" not in result[("artigo", "2º")].upper()
    assert "TÍTULO" not in result[("artigo", "3º")].upper()


def test_heading_title_text_is_kept_on_the_division(parser):
    divs = {e["tipo"]: parser.clean_text(e["texto"])
            for e in parser.build_hierarchy(parser.parse_legal_text(FULL_LAW))
            if e["tipo"] in ("titulo", "secao", "subsecao")}
    assert "DISPOSIÇÕES" in divs["titulo"].upper()
    assert "Definições" in divs["secao"]
    assert "Prazos" in divs["subsecao"]


def test_paragraphs_incisos_and_articles_nest_under_the_active_division(parser):
    result = _paths(parser, """\
        CAPÍTULO I - DO OBJETO
        Art. 1º Requisitos:
        § 1º Regra.
        I - inciso do parágrafo;
        CAPÍTULO II - OUTRO
        Art. 2º Outro.
    """.replace("        ", ""))
    assert result == [
        ("capitulo", "I", "Capítulo I", 0),
        ("artigo", "1º", "Capítulo I > Art. 1º", 1),
        ("paragrafo", "1º", "Capítulo I > Art. 1º > § 1º", 2),
        ("inciso", "I", "Capítulo I > Art. 1º > § 1º > Inciso I", 3),
        ("capitulo", "II", "Capítulo II", 0),
        ("artigo", "2º", "Capítulo II > Art. 2º", 1),
    ]


def test_article_before_any_division_has_no_division_parent(parser):
    result = _paths(parser, "Art. 1º Solto.\nCAPÍTULO I - DEPOIS\nArt. 2º Dentro.")
    assert result[0] == ("artigo", "1º", "Art. 1º", 0)
    assert result[2] == ("artigo", "2º", "Capítulo I > Art. 2º", 1)


def test_repeated_chapter_numbers_in_different_titles_are_kept(parser):
    """'CAPÍTULO I' under TÍTULO I and again under TÍTULO II are different divisions."""
    result = _paths(parser, """\
        TÍTULO I - A
        CAPÍTULO I - X
        Art. 1º Um.
        TÍTULO II - B
        CAPÍTULO I - Y
        Art. 2º Dois.
    """.replace("        ", ""))
    assert [r[2] for r in result if r[0] == "capitulo"] == ["Título I > Capítulo I", "Título II > Capítulo I"]


def test_capitulo_unico_and_roman_lowercase_headings_do_not_crash(parser):
    """Robustness: headings without a numeral or in unusual case must not raise."""
    parser.build_hierarchy(parser.parse_legal_text("CAPÍTULO ÚNICO\nArt. 1º Texto.\nCapítulo iii - x\nArt. 2º T."))
