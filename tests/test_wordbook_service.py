from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.db.models import FavoriteWord
from app.services.review_service import ReviewService
from app.services.wordbook_service import WordbookService


def test_favorite_add_list_and_remove_are_idempotent(database, word_id) -> None:
    service = WordbookService(database)

    assert service.set_favorite(word_id, True).is_favorite is True
    assert service.set_favorite(word_id, True).is_favorite is True

    items = service.list_favorites()
    assert len(items) == 1
    assert items[0].word_id == word_id
    assert items[0].word == "adapt"
    assert items[0].meaning == "适应；改编"
    with database.session() as session:
        assert session.scalar(select(func.count(FavoriteWord.word_id))) == 1

    assert service.set_favorite(word_id, False).is_favorite is False
    assert service.set_favorite(word_id, False).is_favorite is False
    assert service.list_favorites() == []


def test_favorite_rejects_unknown_word_without_creating_a_row(database) -> None:
    service = WordbookService(database)

    with pytest.raises(LookupError):
        service.set_favorite(999_999, True)

    with database.session() as session:
        assert session.scalar(select(func.count(FavoriteWord.word_id))) == 0


def test_review_queue_reports_persisted_favorite_state(database, word_id) -> None:
    WordbookService(database).set_favorite(word_id, True)

    item = ReviewService(database).get_due_words()[0]

    assert item.word_id == word_id
    assert item.is_favorite is True
