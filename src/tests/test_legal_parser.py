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
