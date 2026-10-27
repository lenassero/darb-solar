"""Tests for ``darb_solar.fusionsolar``."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
import requests
from pytest_mock import MockerFixture, MockType

from darb_solar import fusionsolar
from darb_solar.fusionsolar import (
    HISTORY_MAX_WINDOW_MS,
    DeviceRealtimeKpiResponse,
    FusionSolarClient,
    FusionSolarError,
    active_power_kw,
    active_power_kw_from_history_record,
    active_power_kw_from_realtime_kpi,
    device_dn,
    device_type_id,
    filter_inverters,
    filter_meters,
)

BASE_URL = "https://fusionsolar.example.test"
XSRF_TOKEN = "xsrf-token-value"
START_MS = 1_780_000_000_000
STATIONS_URL = f"{BASE_URL}/thirdData/stations"
SECONDS_PER_DAY = 86_400
RATE_LIMIT_BUFFER_SECONDS = 1.0

FakeResponseFactory = Callable[..., MockType]


def _success(data: Any = None, **extra: Any) -> dict[str, Any]:
    """Return a successful FusionSolar response body.

    Parameters
    ----------
    data : Any, optional
        Value of the ``data`` field.
    **extra : Any
        Additional top-level fields, such as ``params``.

    Returns
    -------
    dict[str, Any]
        Response body with ``success`` set to true.
    """
    return {"success": True, "failCode": 0, "data": data, **extra}


def _failure(fail_code: int) -> dict[str, Any]:
    """Return a failed FusionSolar response body.

    Parameters
    ----------
    fail_code : int
        Value of the ``failCode`` field.

    Returns
    -------
    dict[str, Any]
        Response body with ``success`` set to false and no message.
    """
    return {"success": False, "failCode": fail_code, "data": None, "message": None}


@pytest.fixture
def fake_time(mocker: MockerFixture) -> MockType:
    """Replace the ``time`` module used by ``fusionsolar`` with a fake clock.

    ``sleep`` advances the value returned by ``monotonic`` instead of blocking.

    Parameters
    ----------
    mocker : pytest_mock.MockerFixture
        The ``pytest-mock`` fixture.

    Returns
    -------
    pytest_mock.MockType
        Autospecced ``time`` module whose ``sleep`` calls can be asserted.
    """
    clock = {"now": 1_000.0}

    def _sleep(seconds: float) -> None:
        clock["now"] += seconds

    fake = mocker.patch.object(fusionsolar, "time", autospec=True)
    fake.monotonic.side_effect = lambda: clock["now"]
    fake.sleep.side_effect = _sleep
    return fake


@pytest.fixture
def mock_post(mocker: MockerFixture, fake_time: MockType) -> MockType:
    """Patch ``requests.post`` as used by ``fusionsolar``.

    Parameters
    ----------
    mocker : pytest_mock.MockerFixture
        The ``pytest-mock`` fixture.
    fake_time : pytest_mock.MockType
        Fake clock, requested so no test can block on a real rate-limit sleep.

    Returns
    -------
    pytest_mock.MockType
        Autospecced ``requests.post``.
    """
    return mocker.patch("darb_solar.fusionsolar.requests.post", autospec=True)


@pytest.fixture
def client() -> FusionSolarClient:
    """Return a client that already holds an XSRF token.

    Returns
    -------
    FusionSolarClient
        Client pointed at ``BASE_URL`` with a trailing slash to strip.
    """
    fusionsolar_client = FusionSolarClient(f"{BASE_URL}/")
    fusionsolar_client._xsrf_token = XSRF_TOKEN
    return fusionsolar_client


@pytest.fixture
def hook(mocker: MockerFixture, client: FusionSolarClient) -> MockType:
    """Register a mock pre-POST hook on `client`.

    Parameters
    ----------
    mocker : pytest_mock.MockerFixture
        The ``pytest-mock`` fixture.
    client : FusionSolarClient
        Logged-in client fixture.

    Returns
    -------
    pytest_mock.MockType
        Hook passed to ``set_before_authenticated_post``.
    """
    callback = mocker.MagicMock()
    client.set_before_authenticated_post(callback)
    return callback


@pytest.mark.parametrize(
    ("payload", "expected_message", "expected_fail_code"),
    [
        pytest.param(
            {"message": " boom ", "data": "data error", "failCode": 407},
            "boom",
            407,
            id="message-first",
        ),
        pytest.param(
            {"message": "  ", "data": " data error ", "failCode": 407},
            "data error",
            407,
            id="data-string-when-message-blank",
        ),
        pytest.param(
            {"message": None, "data": {"detail": "x"}, "failCode": 401},
            FusionSolarError.KNOWN_FAIL_CODES[401],
            401,
            id="known-fail-code-when-data-not-string",
        ),
        pytest.param(
            {"data": "   ", "failCode": "305"},
            FusionSolarError.KNOWN_FAIL_CODES[305],
            305,
            id="string-fail-code-normalized",
        ),
        pytest.param(
            {"failCode": 99_999},
            "FusionSolar API request failed (failCode=99999)",
            99_999,
            id="unknown-fail-code",
        ),
        pytest.param(
            {"failCode": "not-a-number"},
            "FusionSolar API request failed",
            None,
            id="non-numeric-fail-code",
        ),
        pytest.param(
            {"failCode": [407]},
            "FusionSolar API request failed",
            None,
            id="non-scalar-fail-code",
        ),
        pytest.param({}, "FusionSolar API request failed", None, id="empty"),
    ],
)
def test_fusionsolar_error_from_payload(
    payload: dict[str, Any],
    expected_message: str,
    expected_fail_code: int | None,
) -> None:
    """Message precedence is message, data string, known failCode, then generic."""
    error = FusionSolarError.from_payload(payload)

    assert error.message == expected_message
    assert error.fail_code == expected_fail_code
    assert error.payload is payload


@pytest.mark.parametrize(
    ("fail_code", "expected_str"),
    [(None, "boom"), (407, "boom (failCode=407)")],
)
def test_fusionsolar_error_str_includes_fail_code(
    fail_code: int | None,
    expected_str: str,
) -> None:
    """The exception text appends ``failCode`` only when it is set."""
    assert str(FusionSolarError("boom", fail_code=fail_code)) == expected_str


def test_device_helpers_read_type_and_dn() -> None:
    """``devTypeId`` is cast to int and ``devDn`` to str."""
    device = {"devTypeId": "47", "devDn": "NE=1"}

    assert device_type_id(device) == 47
    assert device_dn(device) == "NE=1"


def test_filter_inverters_and_meters() -> None:
    """Devices are split by their ``devTypeId``."""
    devices = [
        {"id": 1, "devTypeId": 1},
        {"id": 2, "devTypeId": "38"},
        {"id": 3, "devTypeId": 47},
        {"id": 4, "devTypeId": 17},
        {"id": 5, "devTypeId": 10},
    ]

    assert [device["id"] for device in filter_inverters(devices)] == [1, 2]
    assert [device["id"] for device in filter_meters(devices)] == [3]


@pytest.mark.parametrize(
    ("dev_type_id", "expected_kw"),
    [(1, 1500.0), (38, 1500.0), (47, 1.5), (17, 1.5)],
)
def test_active_power_kw_converts_meter_watts(
    dev_type_id: int,
    expected_kw: float,
) -> None:
    """Power sensors and grid meters report watts; inverters report kW."""
    assert active_power_kw({"active_power": "1500"}, dev_type_id) == expected_kw


def test_active_power_kw_reads_custom_field() -> None:
    """The `field` argument selects another KPI key."""
    assert active_power_kw({"other_power": 2.5}, 1, field="other_power") == 2.5


def test_active_power_kw_from_history_record() -> None:
    """Historical rows are read from ``dataItems``."""
    record = {"collectTime": START_MS, "dataItems": {"active_power": -800}}

    assert active_power_kw_from_history_record(record, "47") == -0.8


@pytest.mark.parametrize(
    "record",
    [{"collectTime": START_MS}, {"dataItems": None}, {"dataItems": [1]}],
)
def test_active_power_kw_from_history_record_requires_data_items(
    record: dict[str, Any],
) -> None:
    """A missing or malformed ``dataItems`` raises."""
    with pytest.raises(ValueError, match="missing dataItems"):
        active_power_kw_from_history_record(record, 47)


@pytest.mark.parametrize("as_response", [False, True])
def test_active_power_kw_from_realtime_kpi(as_response: bool) -> None:
    """The row matching `dev_id` is used, from a list or a response object."""
    rows = [
        {"devId": 1, "dataItemMap": {"active_power": 100}},
        {"devId": "2", "dataItemMap": {"active_power": 2500}},
    ]
    kpi_rows: list[dict[str, Any]] | DeviceRealtimeKpiResponse = rows
    if as_response:
        kpi_rows = DeviceRealtimeKpiResponse(
            devices=rows,
            current_time_ms=None,
            params={},
        )

    assert active_power_kw_from_realtime_kpi(kpi_rows, 2, "47") == 2.5


def test_active_power_kw_from_realtime_kpi_requires_matching_row() -> None:
    """A device without a KPI row raises."""
    rows = [{"devId": 1, "dataItemMap": {"active_power": 100}}]

    with pytest.raises(ValueError, match="No KPI row for device 2"):
        active_power_kw_from_realtime_kpi(rows, 2, 47)


@pytest.mark.parametrize(
    ("meter_kw", "expected_export_kw", "expected_consumption_kw"),
    [
        pytest.param(1.5, 1.5, 2.5, id="exporting"),
        pytest.param(-2.0, 0.0, 6.0, id="importing"),
        pytest.param(0.0, 0.0, 4.0, id="balanced"),
    ],
)
def test_compute_energy_balance(
    meter_kw: float,
    expected_export_kw: float,
    expected_consumption_kw: float,
) -> None:
    """Positive meter power is export; consumption is inverter minus meter."""
    balance = FusionSolarClient.compute_energy_balance(4.0, meter_kw)

    assert balance.pv_production_kw == 4.0
    assert balance.grid_export_kw == expected_export_kw
    assert balance.consumption_kw == expected_consumption_kw


def test_client_strips_trailing_slash_and_starts_logged_out() -> None:
    """A new client normalizes its base URL and has no token."""
    fusionsolar_client = FusionSolarClient(f"{BASE_URL}/")

    assert fusionsolar_client.base_url == BASE_URL
    assert fusionsolar_client.xsrf_token is None


@pytest.mark.parametrize("header_name", ["xsrf-token", "XSRF-TOKEN"])
def test_login_stores_token(
    header_name: str,
    mock_post: MockType,
    fake_response: FakeResponseFactory,
) -> None:
    """Login posts credentials without a token and stores the response header."""
    fusionsolar_client = FusionSolarClient(BASE_URL)
    mock_post.return_value = fake_response(
        _success(),
        headers={header_name: XSRF_TOKEN},
    )

    assert fusionsolar_client.login("user", "secret") == XSRF_TOKEN
    assert fusionsolar_client.xsrf_token == XSRF_TOKEN
    mock_post.assert_called_once_with(
        f"{BASE_URL}/thirdData/login",
        json={"userName": "user", "systemCode": "secret"},
        headers={"Content-Type": "application/json"},
        timeout=30,
    )


def test_login_raises_on_success_without_token_header(
    mock_post: MockType,
    fake_response: FakeResponseFactory,
) -> None:
    """A successful body without an XSRF header is still a login failure."""
    fusionsolar_client = FusionSolarClient(BASE_URL)
    mock_post.return_value = fake_response(_success())

    with pytest.raises(FusionSolarError, match="missing xsrf-token header") as info:
        fusionsolar_client.login("user", "secret")

    assert info.value.fail_code == 0
    assert fusionsolar_client.xsrf_token is None


def test_login_raises_payload_error_on_failure_without_token_header(
    mocker: MockerFixture,
) -> None:
    """A failed body without an XSRF header raises the error from the payload."""
    fusionsolar_client = FusionSolarClient(BASE_URL)
    payload = {"success": False, "failCode": 20_001, "message": "bad credentials"}
    mocker.patch.object(fusionsolar_client, "_post", return_value=payload)

    with pytest.raises(FusionSolarError, match="bad credentials") as info:
        fusionsolar_client.login("user", "wrong")

    assert info.value.fail_code == 20_001
    assert info.value.payload is payload
    assert fusionsolar_client.xsrf_token is None


@pytest.mark.parametrize(
    "call_api",
    [
        pytest.param(lambda c: c.list_stations(), id="list_stations"),
        pytest.param(lambda c: c.list_devices("NE=1"), id="list_devices"),
        pytest.param(lambda c: c.get_device_real_kpi(1, 47), id="real_kpi"),
        pytest.param(
            lambda c: c.get_device_history("NE=1", 47, START_MS, START_MS + 1),
            id="history",
        ),
    ],
)
def test_data_apis_require_login(
    call_api: Callable[[FusionSolarClient], Any],
    mock_post: MockType,
) -> None:
    """Data APIs raise before any HTTP call when no token is stored."""
    with pytest.raises(FusionSolarError, match="login required"):
        call_api(FusionSolarClient(BASE_URL))

    mock_post.assert_not_called()


def test_list_stations_returns_data(
    client: FusionSolarClient,
    mock_post: MockType,
    fake_response: FakeResponseFactory,
) -> None:
    """The stations call sends the token and returns only ``data``."""
    data = {"list": [{"plantCode": "NE=1"}], "total": 1}
    mock_post.return_value = fake_response(_success(data))

    assert client.list_stations(page_no=2) == data
    mock_post.assert_called_once_with(
        STATIONS_URL,
        json={"pageNo": 2},
        headers={"Content-Type": "application/json", "xsrf-token": XSRF_TOKEN},
        timeout=30,
    )


def test_list_devices_returns_data(
    client: FusionSolarClient,
    mock_post: MockType,
    fake_response: FakeResponseFactory,
) -> None:
    """The device list call forwards the plant codes and returns ``data``."""
    devices = [{"id": 1, "devTypeId": 1}]
    mock_post.return_value = fake_response(_success(devices))

    assert client.list_devices("NE=1,NE=2") == devices
    assert mock_post.call_args.kwargs["json"] == {"stationCodes": "NE=1,NE=2"}


def test_get_device_real_kpi_parses_response(
    client: FusionSolarClient,
    mock_post: MockType,
    fake_response: FakeResponseFactory,
) -> None:
    """Device rows, params and ``currentTime`` are returned."""
    devices = [{"devId": 1, "dataItemMap": {"active_power": 100}}]
    params = {"currentTime": str(START_MS), "devIds": "1"}
    mock_post.return_value = fake_response(_success(devices, params=params))

    response = client.get_device_real_kpi(1, 47)

    assert response == DeviceRealtimeKpiResponse(
        devices=devices,
        current_time_ms=START_MS,
        params=params,
    )
    assert mock_post.call_args.kwargs["json"] == {"devIds": "1", "devTypeId": "47"}


@pytest.mark.parametrize(
    ("data", "params", "expected_params"),
    [
        pytest.param(None, None, {}, id="missing"),
        pytest.param("oops", ["oops"], {}, id="wrong-types"),
        pytest.param([], {"currentTime": "soon"}, {"currentTime": "soon"}, id="text"),
        pytest.param([], {"currentTime": [1]}, {"currentTime": [1]}, id="list"),
    ],
)
def test_get_device_real_kpi_falls_back_on_malformed_response(
    data: Any,
    params: Any,
    expected_params: dict[str, Any],
    client: FusionSolarClient,
    mock_post: MockType,
    fake_response: FakeResponseFactory,
) -> None:
    """Malformed ``data``, ``params`` or ``currentTime`` become empty values."""
    mock_post.return_value = fake_response(_success(data, params=params))

    response = client.get_device_real_kpi("1", "47")

    assert response.devices == []
    assert response.params == expected_params
    assert response.current_time_ms is None


@pytest.mark.parametrize(
    ("start_ms", "end_ms", "match"),
    [
        pytest.param(START_MS, START_MS, "less than", id="empty"),
        pytest.param(START_MS + 1, START_MS, "less than", id="reversed"),
        pytest.param(
            START_MS,
            START_MS + HISTORY_MAX_WINDOW_MS + 1,
            "exceeds 24 hours",
            id="too-long",
        ),
    ],
)
def test_get_device_history_validates_window(
    start_ms: int,
    end_ms: int,
    match: str,
    client: FusionSolarClient,
    mock_post: MockType,
) -> None:
    """Invalid windows raise before any HTTP call."""
    with pytest.raises(ValueError, match=match):
        client.get_device_history("NE=1", 47, start_ms, end_ms)

    mock_post.assert_not_called()


def test_get_device_history_returns_records(
    client: FusionSolarClient,
    mock_post: MockType,
    fake_response: FakeResponseFactory,
) -> None:
    """A full 24h window is accepted and ``devTypeId`` is sent as an int."""
    records = [{"collectTime": START_MS, "dataItems": {"active_power": 1.0}}]
    mock_post.return_value = fake_response(_success(records))
    end_ms = START_MS + HISTORY_MAX_WINDOW_MS

    response = client.get_device_history("NE=1", "47", START_MS, end_ms)

    assert response.records == records
    assert mock_post.call_args.kwargs["json"] == {
        "devDn": "NE=1",
        "devTypeId": 47,
        "startTime": START_MS,
        "endTime": end_ms,
    }


def test_get_device_history_falls_back_on_malformed_data(
    client: FusionSolarClient,
    mock_post: MockType,
    fake_response: FakeResponseFactory,
) -> None:
    """A non-list ``data`` field yields no records."""
    mock_post.return_value = fake_response(_success({"unexpected": True}))

    response = client.get_device_history("NE=1", 47, START_MS, START_MS + 1)

    assert response.records == []


def test_post_propagates_http_errors(
    client: FusionSolarClient,
    mock_post: MockType,
    fake_response: FakeResponseFactory,
) -> None:
    """HTTP status errors from ``raise_for_status`` are not swallowed."""
    mock_post.return_value = fake_response(
        http_error=requests.HTTPError("502 Bad Gateway")
    )

    with pytest.raises(requests.HTTPError, match="502"):
        client.list_stations()


def test_post_raises_non_retryable_fail_code_immediately(
    client: FusionSolarClient,
    hook: MockType,
    mock_post: MockType,
    fake_response: FakeResponseFactory,
    fake_time: MockType,
) -> None:
    """Fail codes other than 305 and 407 are raised without retrying."""
    mock_post.return_value = fake_response(_failure(401))

    with pytest.raises(FusionSolarError) as info:
        client.list_stations()

    assert info.value.fail_code == 401
    assert info.value.message == FusionSolarError.KNOWN_FAIL_CODES[401]
    mock_post.assert_called_once()
    hook.assert_not_called()
    fake_time.sleep.assert_not_called()


def test_post_reauthenticates_on_session_expiry(
    client: FusionSolarClient,
    hook: MockType,
    mock_post: MockType,
    fake_response: FakeResponseFactory,
    fake_time: MockType,
) -> None:
    """FailCode 305 runs the hook and retries without a rate-limit wait."""
    mock_post.side_effect = [
        fake_response(_failure(305)),
        fake_response(_success({"total": 0})),
    ]

    assert client.list_stations() == {"total": 0}
    assert mock_post.call_count == 2
    hook.assert_called_once_with()
    fake_time.sleep.assert_not_called()


def test_post_raises_after_session_retries_exhausted(
    client: FusionSolarClient,
    hook: MockType,
    mock_post: MockType,
    fake_response: FakeResponseFactory,
) -> None:
    """After two failCode 305 retries the third 305 is raised."""
    mock_post.side_effect = [fake_response(_failure(305)) for _ in range(3)]

    with pytest.raises(FusionSolarError) as info:
        client.list_stations()

    assert info.value.fail_code == 305
    assert mock_post.call_count == 3
    assert hook.call_count == 2


def test_post_backs_off_on_rate_limit_fail_code(
    client: FusionSolarClient,
    hook: MockType,
    mock_post: MockType,
    fake_response: FakeResponseFactory,
    fake_time: MockType,
) -> None:
    """FailCode 407 marks the scope full and waits out its window before retrying."""
    mock_post.side_effect = [
        fake_response(_failure(407)),
        fake_response(_success({"total": 0})),
    ]

    assert client.list_stations() == {"total": 0}
    assert mock_post.call_count == 2
    fake_time.sleep.assert_called_once_with(SECONDS_PER_DAY + RATE_LIMIT_BUFFER_SECONDS)
    hook.assert_not_called()


def test_post_raises_after_rate_limit_retries_exhausted(
    client: FusionSolarClient,
    mocker: MockerFixture,
    mock_post: MockType,
    fake_response: FakeResponseFactory,
    fake_time: MockType,
) -> None:
    """After two failCode 407 backoffs the third 407 is raised."""
    mock_post.side_effect = [fake_response(_failure(407)) for _ in range(3)]

    with pytest.raises(FusionSolarError) as info:
        client.list_stations()

    assert info.value.fail_code == 407
    assert mock_post.call_count == 3
    assert (
        fake_time.sleep.call_args_list
        == [mocker.call(SECONDS_PER_DAY + RATE_LIMIT_BUFFER_SECONDS)] * 2
    )


def test_post_waits_proactively_and_runs_hook(
    client: FusionSolarClient,
    hook: MockType,
    mock_post: MockType,
    fake_response: FakeResponseFactory,
    fake_time: MockType,
) -> None:
    """A second realtime KPI call within 300s waits, then re-authenticates."""
    mock_post.side_effect = [fake_response(_success([])) for _ in range(2)]

    client.get_device_real_kpi(1, 47)
    fake_time.sleep.assert_not_called()
    hook.assert_not_called()

    client.get_device_real_kpi(1, 47)
    fake_time.sleep.assert_called_once_with(300 + RATE_LIMIT_BUFFER_SECONDS)
    hook.assert_called_once_with()


def test_post_rate_limits_realtime_kpi_per_device_type(
    client: FusionSolarClient,
    hook: MockType,
    mock_post: MockType,
    fake_response: FakeResponseFactory,
    fake_time: MockType,
) -> None:
    """Realtime KPI calls for different ``devTypeId`` values use separate scopes."""
    mock_post.side_effect = [fake_response(_success([])) for _ in range(2)]

    client.get_device_real_kpi(1, 1)
    client.get_device_real_kpi(2, 47)

    fake_time.sleep.assert_not_called()
    hook.assert_not_called()


def test_post_skips_hook_for_unauthenticated_calls(
    hook: MockType,
    client: FusionSolarClient,
    mock_post: MockType,
    fake_response: FakeResponseFactory,
    fake_time: MockType,
) -> None:
    """The sixth login within 10 minutes waits but never runs the hook."""
    mock_post.side_effect = [
        fake_response(_success(), headers={"xsrf-token": XSRF_TOKEN}) for _ in range(6)
    ]

    for _ in range(6):
        client.login("user", "secret")

    fake_time.sleep.assert_called_once_with(600 + RATE_LIMIT_BUFFER_SECONDS)
    hook.assert_not_called()


def test_set_before_authenticated_post_clears_hook(
    client: FusionSolarClient,
    hook: MockType,
    mock_post: MockType,
    fake_response: FakeResponseFactory,
) -> None:
    """Passing ``None`` removes a registered hook."""
    client.set_before_authenticated_post(None)
    mock_post.side_effect = [
        fake_response(_failure(305)),
        fake_response(_success([])),
    ]

    client.list_devices("NE=1")

    hook.assert_not_called()
