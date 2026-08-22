"""SQLAlchemy engine and transaction management."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Base


class DatabaseBusyError(RuntimeError):
    """Friendly boundary error for a temporarily locked SQLite database."""



class Database:
    def __init__(self, url: str, *, echo: bool = False) -> None:
        if url.startswith("sqlite:///"):
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(
            url,
            echo=echo,
            future=True,
            connect_args={"check_same_thread": False, "timeout": 15}
            if url.startswith("sqlite")
            else {},
        )
        if url.startswith("sqlite"):
            self._configure_sqlite(self.engine)
        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            expire_on_commit=False,
            class_=Session,
        )

    @staticmethod
    def _configure_sqlite(engine: Engine) -> None:
        @event.listens_for(engine, "connect")
        def set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    def create_tables(self) -> None:
        Base.metadata.create_all(self.engine)

    def begin_serialized_write(self, db_session: Session) -> None:
        """Acquire SQLite's write reservation before reading mutable state.

        SQLite ignores ``SELECT ... FOR UPDATE``. ``BEGIN IMMEDIATE`` makes a
        competing writer wait before it reads the old learning state, avoiding
        a lost update when two application windows submit at the same time.
        """
        if self.engine.dialect.name == "sqlite":
            db_session.execute(text("BEGIN IMMEDIATE"))

    @contextmanager
    def session(self) -> Iterator[Session]:
        db_session = self.session_factory()
        try:
            yield db_session
            db_session.commit()
        except OperationalError as exc:
            db_session.rollback()
            message = str(exc).lower()
            if "locked" in message or "busy" in message:
                raise DatabaseBusyError("本地学习数据库正忙，请稍后重试。") from exc
            raise
        except Exception:
            db_session.rollback()
            raise
        finally:
            db_session.close()

    def dispose(self) -> None:
        self.engine.dispose()
