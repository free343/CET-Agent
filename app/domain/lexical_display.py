"""Deterministic learner-facing labels for lexical relation metadata."""

_PART_OF_SPEECH_LABELS = {
    "a": "adj.",
    "a.": "adj.",
    "adj": "adj.",
    "adj.": "adj.",
    "adjective": "adj.",
    "adv": "adv.",
    "adv.": "adv.",
    "adverb": "adv.",
    "art": "art.",
    "art.": "art.",
    "article": "art.",
    "aux": "aux.",
    "aux.": "aux.",
    "auxiliary": "aux.",
    "conj": "conj.",
    "conj.": "conj.",
    "conjunction": "conj.",
    "det": "det.",
    "det.": "det.",
    "determiner": "det.",
    "interj": "interj.",
    "interj.": "interj.",
    "interjection": "interj.",
    "n": "n.",
    "n.": "n.",
    "noun": "n.",
    "num": "num.",
    "num.": "num.",
    "numeral": "num.",
    "prep": "prep.",
    "prep.": "prep.",
    "preposition": "prep.",
    "pron": "pron.",
    "pron.": "pron.",
    "pronoun": "pron.",
    "r": "adv.",
    "r.": "adv.",
    "v": "v.",
    "v.": "v.",
    "verb": "v.",
    "vi": "v.",
    "vi.": "v.",
    "vt": "v.",
    "vt.": "v.",
}


def format_part_of_speech(value: str) -> str:
    """Return a compact, stable label without changing stored source data."""
    normalized = " ".join(value.split()).casefold()
    return _PART_OF_SPEECH_LABELS.get(normalized, value.strip())
