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


def has_repeated_citation_marker(answer: str) -> bool:
    """Reject citing the same device more than once in a partial overview.

    A partial overview is intentionally limited to one concise claim per
    sampled device. Other answer modes may legitimately cite one provision
    more than once and do not use this check.
    """
    markers = re.findall(r"\[\[(\d+)\]\]", str(answer or ""))
    return len(markers) != len(set(markers))


def has_redundant_content_phrase(answer: str) -> bool:
    """Detect close repetition within a sentence and repeated topics across sentences.

    The check is intentionally narrow: it ignores generic legal labels and
    only rejects close exact repeats. Across sentences, it requires a repeated
    four-word sequence of substantive terms so ordinary legal vocabulary does
    not make separate claims look redundant.
    """
    text = re.sub(r"\[\[\d+\]\]", " ", str(answer or ""))
    sentence_boundary = r"(?<=[!?])\s+|(?<=\.)\s+(?=[A-ZÁÉÍÓÚÂÊÔÃÕÇ])|[\r\n]+"
    seen_across_sentences: set[tuple[str, str, str, str]] = set()
    for sentence in re.split(sentence_boundary, text):
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
