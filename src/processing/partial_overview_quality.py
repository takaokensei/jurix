"""Conservative editorial checks for generated partial norm overviews."""

from __future__ import annotations

import re

_GENERIC_LEGAL_WORDS = frozenset(
    {
        "a", "ao", "aos", "art", "artigo", "as", "com", "da", "das", "de",
        "do", "dos", "e", "em", "essa", "esse", "esta", "este", "na", "nas",
        "no", "nos", "o", "os", "para", "pela", "pelas", "pelo", "pelos",
        "por", "que", "se", "um", "uma", "lei", "norma", "decreto",
        "complementar", "municipio", "natal",
    }
)
_CAPITALIZED_SENTENCE_START = r"(?:(?:\*\*|__|\*|_)\s*)?[A-ZÁÉÍÓÚÂÊÔÃÕÇ]"
_SENTENCE_BOUNDARY = (
    r"(?<=[!?])\s+|"
    rf"(?<=\.)\s+(?={_CAPITALIZED_SENTENCE_START})|"
    rf"(?<=\]\])\s+(?={_CAPITALIZED_SENTENCE_START})|[\r\n]+"
)


def has_repeated_citation_marker(answer: str) -> bool:
    """Reject citing the same device in separate claims of a partial overview.

    A partial overview is intentionally limited to one concise claim per
    sampled device. Some providers duplicate a citation marker within one
    sentence; that does not create a second claim and should not invalidate an
    otherwise grounded answer. Other answer modes do not use this check.
    """
    text = str(answer or "")
    seen: set[str] = set()
    for sentence in re.split(_SENTENCE_BOUNDARY, text):
        markers = re.findall(r"\[\[(\d+)\]\]", sentence)
        unique_in_sentence = set(markers)
        if seen & unique_in_sentence:
            return True
        seen.update(unique_in_sentence)
    return False


def has_redundant_content_phrase(answer: str) -> bool:
    """Detect close repetition within a sentence and repeated topics across sentences.

    The check is intentionally narrow: it ignores generic legal labels and
    only rejects close exact repeats. Across sentences, it requires a repeated
    four-word sequence of substantive terms so ordinary legal vocabulary does
    not make separate claims look redundant.
    """
    text = re.sub(r"\[\[\d+\]\]", " ", str(answer or ""))
    seen_across_sentences: set[tuple[str, str, str, str]] = set()
    for sentence in re.split(_SENTENCE_BOUNDARY, text):
        words = [word.casefold() for word in re.findall(r"[^\W_]+", sentence)]
        content_words = [
            word for word in words
            if word not in _GENERIC_LEGAL_WORDS and len(word) >= 4
        ]
        sentence_phrases = [
            tuple(content_words[index : index + 4])
            for index in range(len(content_words) - 3)
        ]
        if (
            len(sentence_phrases) != len(set(sentence_phrases))
            or set(sentence_phrases) & seen_across_sentences
        ):
            return True
        seen_across_sentences.update(sentence_phrases)

        seen: dict[tuple[str, str], int] = {}
        for index in range(len(words) - 1):
            phrase = (words[index], words[index + 1])
            if any(word in _GENERIC_LEGAL_WORDS or len(word) < 4 for word in phrase):
                continue
            previous_index = seen.get(phrase)
            if previous_index is not None and index - previous_index <= 16:
                return True
            seen[phrase] = index
    return False
