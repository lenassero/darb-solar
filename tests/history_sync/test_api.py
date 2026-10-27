"""Tests for ``darb_solar.history_sync.api``."""

from __future__ import annotations

from typing import Any

import pytest
import requests
from pytest_mock import MockerFixture, MockType

from darb_solar.db.models import Device
from darb_solar.fusionsolar import HISTORY_MAX_WINDOW_MS, DeviceHistoryKpiResponse
from darb_solar.history_sync import api

HOUR_MS = 60 * 60 * 1000
RECORD_A = {"collectTime": 1, "dataItems": {"active_power": 1.0}}
RECORD_B = {"collectTime": 2, "dataItems": {"active_power": 2.0}}


@pytest.fixture
def sleep_mock(mocker: MockerFixture) -> MockType:
    """Patch ``time.sleep`` as used by the API module.

    Parameters
    ----------
    mocker : pytest_mock.MockerFixture
        The ``pytest-mock`` fixture.

    Returns
    -------
    pytest_mock.MockType
        Patched ``sleep`` that returns immediately.
    """
    return mocker.patch.object(api.time, "sleep")


@pytest.mark.parametrize(
    ("start_ms", "end_ms", "expected"),
    [
        pytest.param(10, 10, [], id="empty-range"),
        pytest.param(20, 10, [], id="inverted-range"),
        pytest.param(0, HOUR_MS, [(0, HOUR_MS)], id="short-range"),
        pytest.param(
            0,
            HISTORY_MAX_WINDOW_MS,
            [(0, HISTORY_MAX_WINDOW_MS)],
            id="exactly-24h",
        ),
        pytest.param(
            0,
            HISTORY_MAX_WINDOW_MS + HOUR_MS,
            [
                (0, HISTORY_MAX_WINDOW_MS),
                (HISTORY_MAX_WINDOW_MS, HISTORY_MAX_WINDOW_MS + HOUR_MS),
            ],
            id="25h-is-split",
        ),
        pytest.param(
            5,
            5 + 2 * HISTORY_MAX_WINDOW_MS + 1,
            [
                (5, 5 + HISTORY_MAX_WINDOW_MS),
                (5 + HISTORY_MAX_WINDOW_MS, 5 + 2 * HISTORY_MAX_WINDOW_MS),
                (5 + 2 * HISTORY_MAX_WINDOW_MS, 5 + 2 * HISTORY_MAX_WINDOW_MS + 1),
            ],
            id="three-chunks",
        ),
    ],
)
def test_history_ms_chunks(
    start_ms: int,
    end_ms: int,
    expected: list[tuple[int, int]],
) -> None:
    """Ranges are split into contiguous chunks of at most 24 hours."""
    assert api._history_ms_chunks(start_ms, end_ms) == expected


def test_history_ms_chunks_honors_custom_max_window() -> None:
    """A custom `max_window_ms` changes the chunk size."""
    assert api._history_ms_chunks(0, 10, max_window_ms=4) == [(0, 4), (4, 8), (8, 10)]


def test_fetch_station_returns_matching_station(
    fusionsolar_session: MockType,
) -> None:
    """The station with the requested plant code is returned."""
    stations = [
        {"plantCode": "NE=1", "plantName": "First"},
        {"plantCode": "NE=2", "plantName": "Second"},
    ]
    fusionsolar_session.client.list_stations.return_value = {"list": stations}

    assert api._fetch_station(fusionsolar_session, "NE=2") == stations[1]
    fusionsolar_session.client.list_stations.assert_called_once_with(page_no=1)


@pytest.mark.parametrize("payload", [{"list": [{"plantCode": "NE=1"}]}, {}])
def test_fetch_station_raises_when_plant_is_missing(
    fusionsolar_session: MockType,
    payload: dict[str, Any],
) -> None:
    """A plant absent from ``list_stations`` raises ``ValueError``."""
    fusionsolar_session.client.list_stations.return_value = payload

    with pytest.raises(ValueError, match="'NE=2' was not found"):
        api._fetch_station(fusionsolar_session, "NE=2")


def test_fetch_chunk_returns_records_without_retry(
    fusionsolar_session: MockType,
    inverter: Device,
    sleep_mock: MockType,
) -> None:
    """A successful call logs in if needed and returns the records."""
    fusionsolar_session.client.get_device_history.return_value = (
        DeviceHistoryKpiResponse(records=[RECORD_A])
    )

    records = api._fetch_device_history_chunk(
        fusionsolar_session,
        inverter,
        start_ms=100,
        end_ms=200,
    )

    assert records == [RECORD_A]
    fusionsolar_session.ensure_logged_in.assert_called_once_with()
    fusionsolar_session.client.get_device_history.assert_called_once_with(
        inverter.dev_dn,
        inverter.dev_type_id,
        100,
        200,
    )
    sleep_mock.assert_not_called()


@pytest.mark.parametrize(
    "transient_error",
    [requests.exceptions.Timeout, requests.exceptions.ConnectionError],
)
def test_fetch_chunk_retries_transient_error_then_succeeds(
    fusionsolar_session: MockType,
    inverter: Device,
    sleep_mock: MockType,
    transient_error: type[requests.exceptions.RequestException],
) -> None:
    """A transient error is retried after the first backoff delay."""
    fusionsolar_session.client.get_device_history.side_effect = [
        transient_error("network down"),
        DeviceHistoryKpiResponse(records=[RECORD_A]),
    ]

    records = api._fetch_device_history_chunk(
        fusionsolar_session,
        inverter,
        start_ms=100,
        end_ms=200,
    )

    assert records == [RECORD_A]
    sleep_mock.assert_called_once_with(5.0)
    assert fusionsolar_session.ensure_logged_in.call_count == 2


def test_fetch_chunk_uses_increasing_backoff(
    fusionsolar_session: MockType,
    inverter: Device,
    sleep_mock: MockType,
) -> None:
    """Successive transient errors wait 5s then 15s."""
    fusionsolar_session.client.get_device_history.side_effect = [
        requests.exceptions.Timeout(),
        requests.exceptions.ConnectionError(),
        DeviceHistoryKpiResponse(records=[RECORD_B]),
    ]

    records = api._fetch_device_history_chunk(
        fusionsolar_session,
        inverter,
        start_ms=100,
        end_ms=200,
    )

    assert records == [RECORD_B]
    assert sleep_mock.call_args_list == [((5.0,),), ((15.0,),)]


def test_fetch_chunk_reraises_after_retries_are_exhausted(
    fusionsolar_session: MockType,
    inverter: Device,
    sleep_mock: MockType,
) -> None:
    """The last transient error propagates after two retries."""
    fusionsolar_session.client.get_device_history.side_effect = (
        requests.exceptions.Timeout("still down")
    )

    with pytest.raises(requests.exceptions.Timeout, match="still down"):
        api._fetch_device_history_chunk(
            fusionsolar_session,
            inverter,
            start_ms=100,
            end_ms=200,
        )

    assert fusionsolar_session.client.get_device_history.call_count == 3
    assert sleep_mock.call_count == 2


def test_fetch_chunk_does_not_retry_other_errors(
    fusionsolar_session: MockType,
    inverter: Device,
    sleep_mock: MockType,
) -> None:
    """Errors other than timeouts and connection errors propagate at once."""
    fusionsolar_session.client.get_device_history.side_effect = ValueError("bad")

    with pytest.raises(ValueError, match="bad"):
        api._fetch_device_history_chunk(
            fusionsolar_session,
            inverter,
            start_ms=100,
            end_ms=200,
        )

    fusionsolar_session.client.get_device_history.assert_called_once()
    sleep_mock.assert_not_called()


def test_fetch_history_uses_single_call_for_24h_window(
    fusionsolar_session: MockType,
    inverter: Device,
    mocker: MockerFixture,
) -> None:
    """A window within the API limit triggers exactly one chunk fetch."""
    chunk_mock = mocker.patch.object(
        api,
        "_fetch_device_history_chunk",
        return_value=[RECORD_A],
    )

    records = api._fetch_device_history(
        fusionsolar_session,
        inverter,
        start_ms=0,
        end_ms=HISTORY_MAX_WINDOW_MS,
    )

    assert records == [RECORD_A]
    chunk_mock.assert_called_once_with(
        fusionsolar_session,
        inverter,
        start_ms=0,
        end_ms=HISTORY_MAX_WINDOW_MS,
    )


def test_fetch_history_splits_25h_window_and_concatenates_records(
    fusionsolar_session: MockType,
    inverter: Device,
    mocker: MockerFixture,
) -> None:
    """A 25h window is fetched in two chunks and the records concatenated."""
    chunk_mock = mocker.patch.object(
        api,
        "_fetch_device_history_chunk",
        side_effect=[[RECORD_A], [RECORD_B]],
    )
    end_ms = HISTORY_MAX_WINDOW_MS + HOUR_MS

    records = api._fetch_device_history(
        fusionsolar_session,
        inverter,
        start_ms=0,
        end_ms=end_ms,
    )

    assert records == [RECORD_A, RECORD_B]
    assert chunk_mock.call_args_list == [
        mocker.call(
            fusionsolar_session,
            inverter,
            start_ms=0,
            end_ms=HISTORY_MAX_WINDOW_MS,
        ),
        mocker.call(
            fusionsolar_session,
            inverter,
            start_ms=HISTORY_MAX_WINDOW_MS,
            end_ms=end_ms,
        ),
    ]


def test_fetch_history_returns_empty_list_for_empty_range(
    fusionsolar_session: MockType,
    inverter: Device,
    mocker: MockerFixture,
) -> None:
    """An empty range fetches nothing."""
    chunk_mock = mocker.patch.object(api, "_fetch_device_history_chunk")

    assert (
        api._fetch_device_history(
            fusionsolar_session,
            inverter,
            start_ms=10,
            end_ms=10,
        )
        == []
    )
    chunk_mock.assert_not_called()
