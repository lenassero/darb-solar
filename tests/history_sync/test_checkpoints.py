"""Tests for ``darb_solar.history_sync.checkpoints``."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pytest_mock import MockerFixture, MockType

from darb_solar.db.models import SyncWindow
from darb_solar.db.types import SyncWindowCheckpointStatus
from darb_solar.history_sync import checkpoints

DEV_ID = "1000000001"
WINDOW_START = datetime(2026, 6, 1, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 6, 2, tzinfo=timezone.utc)
NOW = datetime(2026, 6, 3, 8, tzinfo=timezone.utc)


@pytest.fixture
def get_sync_window_mock(mocker: MockerFixture) -> MockType:
    """Patch ``get_sync_window`` as imported by the checkpoints module.

    Parameters
    ----------
    mocker : pytest_mock.MockerFixture
        The ``pytest-mock`` fixture.

    Returns
    -------
    pytest_mock.MockType
        Patched read helper.
    """
    return mocker.patch.object(checkpoints, "get_sync_window")


def test_should_skip_window_never_skips_without_resume(
    db_session: MockType,
    get_sync_window_mock: MockType,
) -> None:
    """With ``resume=False`` the checkpoint is not even consulted."""
    skip = checkpoints.should_skip_window(
        db_session,
        dev_id=DEV_ID,
        window_start=WINDOW_START,
        resume=False,
    )

    assert skip is False
    get_sync_window_mock.assert_not_called()


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (None, False),
        (SyncWindowCheckpointStatus.PENDING, False),
        (SyncWindowCheckpointStatus.FAILED, False),
        (SyncWindowCheckpointStatus.DONE, True),
    ],
)
def test_should_skip_window_only_skips_done_checkpoints(
    db_session: MockType,
    get_sync_window_mock: MockType,
    status: SyncWindowCheckpointStatus | None,
    expected: bool,
) -> None:
    """With ``resume=True`` only a ``done`` checkpoint is skipped."""
    get_sync_window_mock.return_value = (
        None
        if status is None
        else SyncWindow(dev_id=DEV_ID, window_start=WINDOW_START, status=status)
    )

    skip = checkpoints.should_skip_window(
        db_session,
        dev_id=DEV_ID,
        window_start=WINDOW_START,
        resume=True,
    )

    assert skip is expected
    get_sync_window_mock.assert_called_once_with(db_session, DEV_ID, WINDOW_START)


@pytest.mark.parametrize(
    ("status", "error_message"),
    [
        (SyncWindowCheckpointStatus.PENDING, None),
        (SyncWindowCheckpointStatus.FAILED, "boom"),
    ],
)
def test_persist_sync_window_upserts_checkpoint(
    db_session: MockType,
    mocker: MockerFixture,
    status: SyncWindowCheckpointStatus,
    error_message: str | None,
) -> None:
    """A ``SyncWindow`` stamped with the current time is upserted."""
    upsert_mock = mocker.patch.object(checkpoints, "upsert_sync_window")
    mocker.patch.object(checkpoints, "utc_now", return_value=NOW)

    checkpoints.persist_sync_window(
        db_session,
        dev_id=DEV_ID,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
        status=status,
        error_message=error_message,
    )

    upsert_mock.assert_called_once_with(db_session, mocker.ANY)
    window = upsert_mock.call_args.args[1]
    assert isinstance(window, SyncWindow)
    assert window.dev_id == DEV_ID
    assert window.window_start == WINDOW_START
    assert window.window_end == WINDOW_END
    assert window.status == status
    assert window.error_message == error_message
    assert window.updated_at == NOW
