"""Tests for ``darb_solar.db.connection``."""

from __future__ import annotations

import pytest
from pytest_mock import MockerFixture, MockType

from darb_solar.db import connection

URL_A = "postgresql+psycopg://user:secret@db-a:5432/darb"
URL_B = "postgresql+psycopg://user:secret@db-b:5432/darb"


@pytest.fixture
def create_engine_mock(mocker: MockerFixture) -> MockType:
    """Patch ``create_engine`` so that every call returns a distinct mock.

    Parameters
    ----------
    mocker : pytest_mock.MockerFixture
        The ``pytest-mock`` fixture.

    Returns
    -------
    pytest_mock.MockType
        Patched ``create_engine``.
    """
    return mocker.patch.object(
        connection,
        "create_engine",
        side_effect=lambda *args, **kwargs: mocker.MagicMock(name="engine"),
    )


@pytest.fixture
def sessionmaker_mock(mocker: MockerFixture) -> MockType:
    """Patch ``sessionmaker`` so that every call returns a distinct factory.

    Parameters
    ----------
    mocker : pytest_mock.MockerFixture
        The ``pytest-mock`` fixture.

    Returns
    -------
    pytest_mock.MockType
        Patched ``sessionmaker``.
    """
    return mocker.patch.object(
        connection,
        "sessionmaker",
        side_effect=lambda *args, **kwargs: mocker.MagicMock(name="factory"),
    )


@pytest.mark.parametrize(
    ("database_url", "expected"),
    [
        (
            "postgresql://user:pw@host:5432/db",
            "postgresql+psycopg://user:pw@host:5432/db",
        ),
        (
            "postgresql+psycopg://user:pw@host:5432/db",
            "postgresql+psycopg://user:pw@host:5432/db",
        ),
        ("sqlite:///darb.db", "sqlite:///darb.db"),
    ],
)
def test_normalize_database_url(database_url: str, expected: str) -> None:
    """Only the plain ``postgresql://`` scheme is rewritten to psycopg3."""
    assert connection.normalize_database_url(database_url) == expected


def test_normalize_database_url_rewrites_only_the_scheme() -> None:
    """A ``postgresql://`` substring later in the URL is left untouched."""
    url = "postgresql://user:pw@host/db?target=postgresql://other"

    assert connection.normalize_database_url(url) == (
        "postgresql+psycopg://user:pw@host/db?target=postgresql://other"
    )


@pytest.mark.parametrize(
    ("database_url", "expected"),
    [
        (
            "postgresql+psycopg://user:secret@host:5432/db",
            "postgresql+psycopg://***:***@host:5432/db",
        ),
        (
            "postgresql+psycopg://user:p@ss@host:5432/db",
            "postgresql+psycopg://***:***@host:5432/db",
        ),
        (
            "postgresql+psycopg://host:5432/db",
            "postgresql+psycopg://host:5432/db",
        ),
    ],
)
def test_redact_database_url(database_url: str, expected: str) -> None:
    """Credentials are masked and URLs without credentials are unchanged."""
    assert connection.redact_database_url(database_url) == expected


def test_resolve_database_url_prefers_argument(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit URL wins over the environment variable and is normalized."""
    monkeypatch.setenv("DARB_SOLAR_DATABASE_URL", URL_B)

    resolved = connection.resolve_database_url("postgresql://user:pw@arg:5432/db")

    assert resolved == "postgresql+psycopg://user:pw@arg:5432/db"


def test_resolve_database_url_uses_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without an argument, ``DARB_SOLAR_DATABASE_URL`` is used and normalized."""
    monkeypatch.setenv("DARB_SOLAR_DATABASE_URL", "postgresql://u:p@env:5432/db")

    assert connection.resolve_database_url() == "postgresql+psycopg://u:p@env:5432/db"


def test_resolve_database_url_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without an argument or environment variable, the default URL is used."""
    monkeypatch.delenv("DARB_SOLAR_DATABASE_URL", raising=False)

    assert connection.resolve_database_url() == connection.DEFAULT_DATABASE_URL


def test_get_engine_configures_pooling(
    create_engine_mock: MockType,
    sessionmaker_mock: MockType,
) -> None:
    """The engine is created with pre-ping and early connection recycling."""
    engine = connection.get_engine(URL_A)

    create_engine_mock.assert_called_once_with(
        URL_A,
        pool_pre_ping=True,
        pool_recycle=280,
    )
    sessionmaker_mock.assert_called_once_with(bind=engine)


def test_get_engine_caches_per_url(
    create_engine_mock: MockType,
    sessionmaker_mock: MockType,
) -> None:
    """The same URL yields the cached engine, a new URL a new engine."""
    first = connection.get_engine(URL_A)
    second = connection.get_engine(URL_A)
    other = connection.get_engine(URL_B)

    assert first is second
    assert other is not first
    assert create_engine_mock.call_count == 2
    assert set(connection._engines) == {URL_A, URL_B}


def test_get_engine_caches_by_normalized_url(
    create_engine_mock: MockType,
    sessionmaker_mock: MockType,
) -> None:
    """``postgresql://`` and ``postgresql+psycopg://`` share one engine."""
    plain = connection.get_engine("postgresql://user:secret@db-a:5432/darb")
    dialect = connection.get_engine(URL_A)

    assert plain is dialect
    create_engine_mock.assert_called_once()


def test_get_session_factory_reuses_cached_factory(
    create_engine_mock: MockType,
    sessionmaker_mock: MockType,
) -> None:
    """Repeated lookups return the factory created alongside the engine."""
    first = connection._get_session_factory(URL_A)
    second = connection._get_session_factory(URL_A)

    assert first is second
    sessionmaker_mock.assert_called_once()


def test_get_session_commits_and_closes_on_success(
    create_engine_mock: MockType,
    sessionmaker_mock: MockType,
) -> None:
    """A clean exit commits, never rolls back, and closes the session."""
    with connection.get_session(URL_A) as session:
        pass

    session.commit.assert_called_once_with()
    session.rollback.assert_not_called()
    session.close.assert_called_once_with()


def test_get_session_rolls_back_and_reraises_on_error(
    create_engine_mock: MockType,
    sessionmaker_mock: MockType,
) -> None:
    """An exception rolls back, is re-raised, and the session is closed."""
    session = None
    with pytest.raises(RuntimeError, match="boom"):
        with connection.get_session(URL_A) as session:
            raise RuntimeError("boom")

    session.commit.assert_not_called()
    session.rollback.assert_called_once_with()
    session.close.assert_called_once_with()


def test_get_session_uses_resolved_url(
    create_engine_mock: MockType,
    sessionmaker_mock: MockType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without an argument, the session comes from the environment URL."""
    monkeypatch.setenv("DARB_SOLAR_DATABASE_URL", URL_B)

    with connection.get_session():
        pass

    create_engine_mock.assert_called_once_with(
        URL_B,
        pool_pre_ping=True,
        pool_recycle=280,
    )
