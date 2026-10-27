"""Tests for ``darb_solar.env``."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from darb_solar import env

ENV_VAR_NAME = "DARB_SOLAR_TEST_ENV_VAR"


@pytest.fixture
def unset_env_var(monkeypatch: pytest.MonkeyPatch) -> str:
    """Return a variable name that is unset now and restored after the test.

    Setting the variable before deleting it registers its removal with
    ``monkeypatch``, so values loaded by ``load_dotenv`` do not leak.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        The built-in ``monkeypatch`` fixture.

    Returns
    -------
    str
        Name of the environment variable.
    """
    monkeypatch.setenv(ENV_VAR_NAME, "placeholder")
    monkeypatch.delenv(ENV_VAR_NAME)
    return ENV_VAR_NAME


def test_load_env_loads_existing_file(tmp_path: Path, unset_env_var: str) -> None:
    """An existing file is loaded into ``os.environ`` and its path returned."""
    env_path = tmp_path / ".env"
    env_path.write_text(f"{unset_env_var}=loaded\n")

    loaded_path = env.load_env(env_path)

    assert loaded_path == env_path.resolve()
    assert os.environ[unset_env_var] == "loaded"


def test_load_env_returns_none_for_missing_file(
    tmp_path: Path,
    unset_env_var: str,
) -> None:
    """A missing file is ignored and ``None`` returned."""
    assert env.load_env(tmp_path / "missing.env") is None
    assert unset_env_var not in os.environ


def test_load_env_defaults_to_project_env_path(
    tmp_path: Path,
    unset_env_var: str,
    mocker: MockerFixture,
) -> None:
    """Without `env_path`, ``DEFAULT_ENV_PATH`` is loaded."""
    default_path = tmp_path / ".env"
    default_path.write_text(f"{unset_env_var}=default\n")
    mocker.patch.object(env, "DEFAULT_ENV_PATH", default_path)

    assert env.load_env() == default_path.resolve()
    assert os.environ[unset_env_var] == "default"
