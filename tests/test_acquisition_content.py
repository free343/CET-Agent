from __future__ import annotations

from app.domain.acquisition import EnglishCandidate, build_cloze_question


def test_irregular_fling_form_is_hidden_and_has_four_choices() -> None:
    target = EnglishCandidate(1, "fling", "v. 扔", 100)
    candidates = [
        target,
        EnglishCandidate(2, "bring", "v. 带来", 99),
        EnglishCandidate(3, "swing", "v. 摇摆", 98),
        EnglishCandidate(4, "cling", "v. 粘住", 97),
    ]
    question = build_cloze_question(
        target,
        "She flung her bag onto the sofa.",
        candidates,
    )
    assert question is not None
    assert "fling" not in question.text.casefold()
    assert any(
        option.text == "flung" and option.is_correct for option in question.options
    )
