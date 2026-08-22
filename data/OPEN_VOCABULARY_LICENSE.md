# CET-Agent open vocabulary data

`cet_vocabulary_open.csv` contains 4,598 transformed vocabulary records and is
distributed under the Creative Commons Attribution-ShareAlike 3.0 Unported
license (CC BY-SA 3.0):

<https://creativecommons.org/licenses/by-sa/3.0/>

## Attribution and sources

The artifact was generated from these pinned sources:

1. ECDICT at revision `bc015ed2e24a7abef49fc6dbbb7fe32c1dadaf8b`,
   Copyright (c) 2025 Linwei, MIT license. It supplies the headwords, CET tags,
   frequency ranks, phonetics, and Chinese meanings.
2. English-中文 (Zhōngwén) FreeDict+WikDict dictionary, version `2025.11.23`,
   maintained and published by Karl Bartel, CC BY-SA 3.0. Its source states
   that it was automatically created by WikDict from Wiktionary data via
   DBnary. It supplies independent headword, pronunciation, and bilingual-entry
   validation.

Exact URLs and cryptographic source hashes are recorded in
`cet_vocabulary_open.provenance.json`. The ECDICT MIT notice and FreeDict
attribution are also reproduced in the repository-level
`THIRD_PARTY_NOTICES.md`.

## Changes made by CET-Agent

CET-Agent intersected the CET-tagged ECDICT headwords with validated FreeDict
English-Chinese entries, removed phrases and entries without usable phonetics
or Chinese meanings, normalized whitespace and phonetic delimiters, assigned
the most inclusive CET level when duplicate tags existed, computed a bounded
frequency score from source ranks, excluded the 13 project-curated demo words,
sorted each level deterministically, and assigned an initial release delay of
at most 20 new words per level per day.

The generated artifact includes no example sentences from either source.
