"""Conservative, source-bound previews for candidate legal consolidations.

These helpers do not adjudicate validity or currentness. They only combine a
base quotation with a promulgated amendment when the amendment's omission
markers and the base device make the operation unambiguous.
"""

from __future__ import annotations

import re

_PAGE_NOISE = re.compile(
    r"\s*---\s*P[aá]gina\s+\d+\s*---\s*"
    r"(?:ESTADO DO RIO GRANDE DO NORTE\s*)?"
    r"(?:C[ÂA]MARA MUNICIPAL DE NATAL\s*)?"
    r"(?:PAL[ÁA]CIO PADRE MIGUELINHO\s*)?",
    flags=re.IGNORECASE,
)
_OMISSION = re.compile(r"(?:\.{3,}|…{1,})")


def _clean_quote(value: str) -> str:
    value = _PAGE_NOISE.sub(" ", value or "")
    return re.sub(r"\s+", " ", value).strip()


def build_article_150_snapshot(before_quote: str, amendment_quote: str) -> dict:
    """Preserve Art. 150's unchanged caput and replace its sole paragraph.

    LC 271/2025 prints an omission marker after Art. 150's heading, then the
    new sole paragraph. The merge is allowed only when the 2024 source has one
    caput and exactly one sole paragraph, and the amendment supplies exactly
    one new sole paragraph before its next omission marker.
    """
    before = _clean_quote(before_quote)
    amendment = _clean_quote(amendment_quote)

    baseline = re.fullmatch(
        r"Art\.?\s*150\s*[-–—.]?\s*(?P<caput>.*?)\s+"
        r"Par[aá]grafo [uú]nico\s*[-.]?\s*(?P<paragraph>.+)",
        before,
        flags=re.IGNORECASE,
    )
    baseline_paragraph_count = len(
        re.findall(r"Par[aá]grafo [uú]nico", before, flags=re.IGNORECASE)
    )
    amendment_paragraph_count = len(
        re.findall(r"Par[aá]grafo [uú]nico", amendment, flags=re.IGNORECASE)
    )
    replacement = re.search(
        r"Par[aá]grafo [uú]nico\s*\.\s*(?P<paragraph>.+)$",
        amendment,
        flags=re.IGNORECASE,
    )
    if (
        not baseline
        or not replacement
        or baseline_paragraph_count != 1
        or amendment_paragraph_count != 1
    ):
        return {
            "status": "incomplete",
            "text": "",
            "reason": "Não foi possível isolar com unicidade o caput e o parágrafo substituído.",
        }

    caput = baseline.group("caput").strip()
    new_paragraph = replacement.group("paragraph").strip()
    old_paragraph = baseline.group("paragraph").strip()
    if not caput or not new_paragraph or not old_paragraph:
        return {
            "status": "incomplete",
            "text": "",
            "reason": "A extração não contém todos os segmentos necessários ao cotejo.",
        }

    return {
        "status": "candidate_integrated",
        "text": f"Art. 150. {caput}\nParágrafo único. {new_paragraph}",
        "preserved_units": ["caput"],
        "replaced_units": ["Parágrafo único"],
        "old_paragraph": old_paragraph,
        "reason": (
            "O caput foi preservado porque a LC 271/2025 o omite por reticências; "
            "o parágrafo único foi substituído pelo texto expresso no ato."
        ),
    }


def build_article_23_snapshot(before_quote: str, amendment_quote: str) -> dict:
    """Append LC 271/2025's explicit § 6º to a complete 2024 Art. 23 quote.

    The amendment uses omission dots for the existing article and then prints
    the new paragraph. This is safe only when the baseline contains exactly
    §§ 1º–5º, no § 6º, and the amendment has one complete § 6º after an omission
    marker.
    """
    before = _clean_quote(before_quote)
    amendment = _clean_quote(amendment_quote)
    heading = re.match(r"Art\.?\s*23\s*[–—.:-]?\s*(?P<body>.+)$", amendment, flags=re.IGNORECASE)
    paragraph = re.search(
        r"§\s*6\s*[º°o.]\s*(?P<text>.+)$",
        amendment,
        flags=re.IGNORECASE,
    )
    baseline_paragraphs = {
        number: len(re.findall(
            rf"(?:^|[.;)]\s*)§\s*{number}\s*[º°o.]",
            before,
            flags=re.IGNORECASE,
        ))
        for number in range(1, 7)
    }
    amendment_prefix = amendment[:paragraph.start()] if paragraph else ""
    if (
        not re.match(r"^Art\.?\s*23\b", before, flags=re.IGNORECASE)
        or _OMISSION.search(before)
        or not heading
        or not paragraph
        or not _OMISSION.search(amendment_prefix)
        or _OMISSION.search(paragraph.group("text"))
        or any(baseline_paragraphs[number] != 1 for number in range(1, 6))
        or baseline_paragraphs[6] != 0
        or len(re.findall(r"§\s*6\s*[º°o.]", amendment, flags=re.IGNORECASE)) != 1
    ):
        return {
            "status": "incomplete",
            "text": "",
            "reason": "A edição-base completa dos §§ 1º–5º e a inclusão única do § 6º não puderam ser confirmadas.",
        }

    new_paragraph = paragraph.group("text").strip()
    if not before or not new_paragraph:
        return {
            "status": "incomplete",
            "text": "",
            "reason": "A extração não contém o texto necessário para preservar o Art. 23 e acrescentar o § 6º.",
        }
    return {
        "status": "candidate_integrated",
        "text": f"{before}\n§ 6º {new_paragraph}",
        "preserved_units": ["Art. 23 da edição municipal de 2024", "§§ 1º–5º"],
        "replaced_units": [],
        "added_units": ["§ 6º"],
        "reason": (
            "A LC 271/2025 omite por reticências o texto anterior do Art. 23 e transcreve o § 6º; "
            "a minuta preserva os §§ 1º–5º da edição-base de 2024 e acrescenta somente o § 6º."
        ),
    }


def build_lc271_consolidation_previews(changes: list[dict]) -> list[dict]:
    """Build only complete, deterministic article previews from LC 271/2025."""
    by_number = {str(change["article_number"]): change for change in changes}
    previews = []

    art20 = by_number.get("20", {})
    text20 = (art20.get("after") or {}).get("quote", "").strip()
    if (
        art20.get("before")
        and text20
        and not _OMISSION.search(text20)
        and not (art20.get("after") or {}).get("omitted_following_text")
    ):
        previews.append({
            "article_number": "20",
            "status": "candidate_integrated",
            "text": text20,
            "preserved_units": [],
            "replaced_units": ["Art. 20 integral"],
            "reason": "A LC 271/2025 transcreve redação substitutiva integral, sem reticências no dispositivo.",
        })

    art23 = by_number.get("23", {})
    if art23.get("before") and art23.get("after"):
        preview = build_article_23_snapshot(
            art23["before"].get("quote", ""),
            art23["after"].get("quote", ""),
        )
        if preview["status"] == "candidate_integrated":
            previews.append({"article_number": "23", **preview})

    art150 = by_number.get("150", {})
    if art150.get("before") and art150.get("after"):
        preview = build_article_150_snapshot(
            art150["before"].get("quote", ""),
            art150["after"].get("quote", ""),
        )
        previews.append({"article_number": "150", **preview})

    return previews


def extract_lc271_added_articles(source_text: str) -> list[dict]:
    """Extract the five complete CTM provisions added by LC 271/2025, Art. 2."""
    source = _PAGE_NOISE.sub(" ", source_text or "")
    source = re.sub(r"\r\n?", "\n", source)
    source = re.sub(r"[ \t]+", " ", source)
    section_start = re.search(r"Ficam acrescidos", source, flags=re.IGNORECASE)
    if not section_start:
        return []
    section_end = re.search(
        r"(?m)^\s*Art\.?\s*3[^\r\n]{0,8}Os arts\.",
        source[section_start.end():],
        flags=re.IGNORECASE,
    )
    if not section_end:
        return []
    body = source[section_start.end():section_start.end() + section_end.start()]
    body = body.strip().strip("“”\"'")
    numbers = ("133-A", "133-B", "133-C", "133-D", "133-E")
    starts = []
    for number in numbers:
        matches = list(re.finditer(
            rf"(?<![A-Za-z])[“\"']?Art\.?\s*{re.escape(number)}\s*\.",
            body,
        ))
        if len(matches) != 1:
            return []
        starts.append(matches[0].start())
    if starts != sorted(starts):
        return []

    provisions = []
    for index, number in enumerate(numbers):
        start = starts[index]
        end = starts[index + 1] if index + 1 < len(starts) else len(body)
        text = re.sub(r"\s+", " ", body[start:end]).strip().strip("“”\"'")
        text = re.sub(r"[”\"']+$", "", text).strip()
        if not text or _OMISSION.search(text):
            return []
        provisions.append({
            "article_number": number,
            "status": "candidate_added",
            "text": text,
            "reason": "A LC 271/2025, Art. 2º, acrescenta este dispositivo ao CTM e transcreve seu texto.",
        })
    return provisions


def lc271_effects_summary() -> dict:
    """Structured effects expressly stated by LC 271/2025, Art. 2–6."""
    return {
        "additions": ["133-A", "133-B", "133-C", "133-D", "133-E"],
        "express_repeals": [
            "Lei nº 3.882/1989, Art. 66, § 11",
            "Lei nº 3.882/1989, Art. 68, § 1º",
            "Lei Complementar nº 141/2014, Art. 23, incisos XV, XVI, XVII, XVIII, XIX, XX, XXI, XXII e XXIV",
        ],
        "one_time_provision": "Remissão parcial da Taxa de Lixo referente ao exercício de 2025 (Art. 4º).",
        "effective_date_rule": "Art. 6º prevê vigência na data da publicação.",
        "scope_note": (
            "As revogações e inclusões são eventos expressos no texto promulgado; "
            "esta síntese não atesta alterações posteriores nem vigência atual."
        ),
    }
