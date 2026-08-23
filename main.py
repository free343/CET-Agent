"""CET-Agent desktop entry point."""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from app.ai.factory import (
    create_advanced_llm_provider,
    create_embedding_provider,
    create_llm_provider,
)
from app.bootstrap import initialize_database
from app.config import settings
from app.services.acquisition_service import AcquisitionService
from app.services.ai_service import AIService
from app.services.analysis_service import AnalysisService
from app.services.learning_aid_feedback_service import LearningAidFeedbackService
from app.services.learning_service import LearningService
from app.services.mastery_service import MasteryService
from app.services.practice_service import PracticeService
from app.services.reminder_service import ReminderService
from app.services.review_service import ReviewService
from app.services.wordbook_service import WordbookService
from app.ui.main_window import MainWindow

logger = logging.getLogger(__name__)


def run(*, smoke_test: bool = False) -> int:
    application = QApplication.instance() or QApplication(sys.argv)
    application.setApplicationName("CET-Agent")
    database = None
    try:
        database = initialize_database()
        llm_provider = create_llm_provider(settings)
        advanced_provider = create_advanced_llm_provider(settings)
        ai_service = AIService(database, llm_provider, advanced_provider)
        embedding_provider = create_embedding_provider(settings, database)
        review_service = ReviewService(database, settings.study_level)
        wordbook_service = WordbookService(database)
        acquisition_service = AcquisitionService(database, settings.study_level)
        mastery_service = MasteryService(database)
        window = MainWindow(
            LearningService(database, settings.study_level),
            review_service,
            AnalysisService(database, embedding_provider),
            ai_service,
            ReminderService(review_service, settings),
            wordbook_service,
            LearningAidFeedbackService(database),
            PracticeService(database, settings.study_level),
            settings,
            acquisition_service,
            mastery_service,
        )
        window.show()
        if smoke_test:
            # Exercise the real close path so page/reminder workers finish
            # before the event loop exits and the Database is disposed.
            QTimer.singleShot(250, window.close)
        return application.exec()
    except Exception:
        logger.exception("Application startup failed")
        if application and not smoke_test:
            QMessageBox.critical(
                None,
                "CET-Agent",
                "应用启动失败，请查看日志了解详细信息。",
            )
        return 1
    finally:
        if database is not None:
            database.dispose()


if __name__ == "__main__":
    raise SystemExit(run(smoke_test="--smoke-test" in sys.argv))
