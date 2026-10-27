"""Tests for ``darb_solar.history_sync.session``."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pytest_mock import MockerFixture, MockType

from darb_solar.fusionsolar import DEFAULT_BASE_URL, FusionSolarClient
from darb_solar.history_sync import session as session_module
from darb_solar.history_sync.session import FusionSolarSession, login_fusionsolar

USERNAME = "api-user"
SYSTEM_CODE = "api-secret"


@pytest.fixture
def client(mocker: MockerFixture) -> MockType:
    """Return a mock FusionSolar client with a stored XSRF token.

    Parameters
    ----------
    mocker : pytest_mock.MockerFixture
        The ``pytest-mock`` fixture.

    Returns
    -------
    pytest_mock.MockType
        Mock ``FusionSolarClient`` whose ``xsrf_token`` is set.
    """
    mock_client = mocker.MagicMock(spec=FusionSolarClient)
    mock_client.xsrf_token = "token"
    return mock_client


def _make_session(client: MockType, *, age: timedelta) -> FusionSolarSession:
    """Build a session whose last login was `age` ago.

    Parameters
    ----------
    client : pytest_mock.MockType
        Mock client wrapped by the session.
    age : datetime.timedelta
        Time elapsed since the simulated last login.

    Returns
    -------
    FusionSolarSession
        Session under test.
    """
    return FusionSolarSession(
        client=client,
        username=USERNAME,
        system_code=SYSTEM_CODE,
        logged_in_at=datetime.now(timezone.utc) - age,
    )


@pytest.fixture
def clean_credentials_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """Remove FusionSolar environment variables for the test.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        The built-in ``monkeypatch`` fixture.

    Returns
    -------
    pytest.MonkeyPatch
        Fixture allowing the test to set variables again.
    """
    for name in (
        "FUSIONSOLAR_USERNAME",
        "FUSIONSOLAR_SYSTEM_CODE",
        "FUSIONSOLAR_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.fixture
def client_class_mock(mocker: MockerFixture) -> MockType:
    """Patch ``FusionSolarClient`` in the session module.

    Parameters
    ----------
    mocker : pytest_mock.MockerFixture
        The ``pytest-mock`` fixture.

    Returns
    -------
    pytest_mock.MockType
        Patched class; its return value is the client instance.
    """
    return mocker.patch.object(session_module, "FusionSolarClient")


def test_constructor_registers_force_login_hook(client: MockType) -> None:
    """The client re-authenticates through the session before each post."""
    session = _make_session(client, age=timedelta(0))

    client.set_before_authenticated_post.assert_called_once_with(session.force_login)


def test_ensure_logged_in_keeps_fresh_token(client: MockType) -> None:
    """A recent login with a stored token does not re-authenticate."""
    session = _make_session(client, age=timedelta(minutes=5))

    session.ensure_logged_in()

    client.login.assert_not_called()


def test_ensure_logged_in_refreshes_stale_token(client: MockType) -> None:
    """A login older than 25 minutes triggers a refresh."""
    session = _make_session(client, age=timedelta(minutes=26))

    session.ensure_logged_in()

    client.login.assert_called_once_with(USERNAME, SYSTEM_CODE)


def test_ensure_logged_in_logs_in_without_token(client: MockType) -> None:
    """A missing XSRF token triggers a login even for a recent session."""
    client.xsrf_token = None
    session = _make_session(client, age=timedelta(minutes=1))

    session.ensure_logged_in()

    client.login.assert_called_once_with(USERNAME, SYSTEM_CODE)


def test_force_login_resets_login_timestamp(client: MockType) -> None:
    """``force_login`` authenticates and records the new login time."""
    session = _make_session(client, age=timedelta(hours=2))
    before = datetime.now(timezone.utc)

    session.force_login()

    client.login.assert_called_once_with(USERNAME, SYSTEM_CODE)
    assert session.logged_in_at >= before


def test_login_fusionsolar_prefers_arguments_over_environment(
    clean_credentials_env: pytest.MonkeyPatch,
    client_class_mock: MockType,
) -> None:
    """Explicit arguments take precedence over environment variables."""
    clean_credentials_env.setenv("FUSIONSOLAR_USERNAME", "env-user")
    clean_credentials_env.setenv("FUSIONSOLAR_SYSTEM_CODE", "env-code")
    clean_credentials_env.setenv("FUSIONSOLAR_BASE_URL", "https://env.example")

    session = login_fusionsolar(
        username=USERNAME,
        system_code=SYSTEM_CODE,
        base_url="https://arg.example",
    )

    client_class_mock.assert_called_once_with(base_url="https://arg.example")
    client = client_class_mock.return_value
    client.login.assert_called_once_with(USERNAME, SYSTEM_CODE)
    assert session.client is client
    assert session.username == USERNAME
    assert session.system_code == SYSTEM_CODE


def test_login_fusionsolar_reads_environment(
    clean_credentials_env: pytest.MonkeyPatch,
    client_class_mock: MockType,
) -> None:
    """Credentials and base URL fall back to the environment."""
    clean_credentials_env.setenv("FUSIONSOLAR_USERNAME", "env-user")
    clean_credentials_env.setenv("FUSIONSOLAR_SYSTEM_CODE", "env-code")
    clean_credentials_env.setenv("FUSIONSOLAR_BASE_URL", "https://env.example")

    login_fusionsolar()

    client_class_mock.assert_called_once_with(base_url="https://env.example")
    client_class_mock.return_value.login.assert_called_once_with(
        "env-user",
        "env-code",
    )


def test_login_fusionsolar_defaults_base_url(
    clean_credentials_env: pytest.MonkeyPatch,
    client_class_mock: MockType,
) -> None:
    """Without argument or variable, the client default host is used."""
    login_fusionsolar(username=USERNAME, system_code=SYSTEM_CODE)

    client_class_mock.assert_called_once_with(base_url=DEFAULT_BASE_URL)


def test_login_fusionsolar_stamps_login_time(
    clean_credentials_env: pytest.MonkeyPatch,
    client_class_mock: MockType,
) -> None:
    """The returned session is marked as freshly logged in."""
    before = datetime.now(timezone.utc)

    session = login_fusionsolar(username=USERNAME, system_code=SYSTEM_CODE)

    assert session.logged_in_at >= before


@pytest.mark.parametrize(
    ("username", "system_code"),
    [(None, SYSTEM_CODE), (USERNAME, None), (None, None), ("", SYSTEM_CODE)],
)
def test_login_fusionsolar_requires_credentials(
    clean_credentials_env: pytest.MonkeyPatch,
    client_class_mock: MockType,
    username: str | None,
    system_code: str | None,
) -> None:
    """Missing credentials raise before any client is created."""
    with pytest.raises(ValueError, match="credentials are required"):
        login_fusionsolar(username=username, system_code=system_code)

    client_class_mock.assert_not_called()
