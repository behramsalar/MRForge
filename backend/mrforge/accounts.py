"""Researcher profiles: who is working, so people can follow and resume their own work.

This is NOT a login. A profile is a name that a person picks on a computer they share with
others; MRForge tags what they start with it and shows "my recent work". Anyone can pick any
profile, so it must not be used to protect data (docs/DECISIONS.md).

It is built so that real accounts can be added later without redoing it: profiles live in one
app-level store (not inside a workspace), every action stores the profile name, and the API
finds the current researcher in exactly one place (``api.app.current_researcher``). A login
would add a password hash to this table and replace that one function with a session check.
"""

from __future__ import annotations

import re
import threading
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import DateTime, Engine, String, create_engine, func, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from mrforge.config import config_path
from mrforge.errors import StepError

NAME_RULE = re.compile(r"[^\W_][\w .'\-]{0,58}[\w.]|[^\W_]", re.UNICODE)


def _now() -> datetime:
    return datetime.now(UTC)


class AccountsBase(DeclarativeBase):
    pass


class Researcher(AccountsBase):
    __tablename__ = "researcher"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    created: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # A later login system adds the password hash here (nothing else needs to change).


_engines: dict[Path, Engine] = {}
_lock = threading.Lock()


def accounts_db_path() -> Path:
    """Next to the app settings (``MRFORGE_CONFIG`` moves both, which tests rely on)."""
    return config_path().parent / "researchers.sqlite"


def _engine() -> Engine:
    path = accounts_db_path()
    with _lock:
        engine = _engines.get(path)
        if engine is None:
            path.parent.mkdir(parents=True, exist_ok=True)
            engine = create_engine(f"sqlite:///{path}", connect_args={"timeout": 30})
            AccountsBase.metadata.create_all(engine)
            _engines[path] = engine
        return engine


def _session() -> Session:
    return Session(_engine(), expire_on_commit=False)


def list_researchers() -> list[Researcher]:
    with _session() as s:
        return list(s.scalars(select(Researcher).order_by(func.lower(Researcher.name))))


def get_researcher(researcher_id: int) -> Researcher | None:
    with _session() as s:
        return s.get(Researcher, researcher_id)


def create_researcher(name: str) -> Researcher:
    clean = " ".join(name.split())
    if not NAME_RULE.fullmatch(clean):
        raise StepError(
            code="BAD_NAME",
            message="That name cannot be used.",
            probable_cause="Names can use letters, digits, spaces, dots, dashes and apostrophes, "
            "up to 60 characters.",
            suggested_action="Type your name again, for example 'Jane Smith'.",
        )
    with _session() as s, s.begin():
        taken = s.scalar(select(Researcher).where(func.lower(Researcher.name) == clean.lower()))
        if taken is not None:
            raise StepError(
                code="NAME_TAKEN",
                message=f"There is already a researcher called {taken.name}.",
                probable_cause="Names are compared without regard to upper or lower case.",
                suggested_action="Pick that name from the list, or add something to yours.",
            )
        researcher = Researcher(name=clean)
        s.add(researcher)
        s.flush()
        return researcher


def touch(researcher_id: int) -> None:
    """Remember when this researcher was last active."""
    with _session() as s, s.begin():
        row = s.get(Researcher, researcher_id)
        if row is not None:
            row.last_seen = datetime.now(UTC)
