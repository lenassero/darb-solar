"""Huawei FusionSolar northbound API client."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from collections.abc import Callable
from typing import Any, ClassVar

import requests
from loguru import logger

DEFAULT_BASE_URL = "https://eu5.fusionsolar.huawei.com"

# Inverter: 1 (string inverter) or 38 (residential inverter).
INVERTER_DEV_TYPE_IDS = frozenset({1, 38})
# Meter / power sensor: 47. Grid meter (17) is used on some installs.
METER_DEV_TYPE_IDS = frozenset({47})
GRID_METER_DEV_TYPE_ID = 17

_LOGIN_PATH = "/thirdData/login"
_STATIONS_PATH = "/thirdData/stations"
_DEV_LIST_PATH = "/thirdData/getDevList"
_DEV_REAL_KPI_PATH = "/thirdData/getDevRealKpi"
_DEVICE_HISTORY_PATH = "/rest/openapi/pvms/nbi/v1/device/history"

_HISTORY_MAX_WINDOW_MS = 24 * 60 * 60 * 1000
# One inverter + one meter: 1/60/10 + 1/60/10 = 0.0033… calls/s → 300 s between calls.
_HISTORY_CALLS_PER_SECOND = 2 / 600
_HISTORY_MIN_INTERVAL_SECONDS = 1 / _HISTORY_CALLS_PER_SECOND

_RATE_LIMIT_RETRY_BUFFER_SECONDS = 1.0
_MAX_FAILCODE_407_RETRIES = 2
_SESSION_EXPIRED_FAIL_CODE = 305
_MAX_FAILCODE_305_RETRIES = 2
_SECONDS_PER_DAY = 86_400


@dataclass(frozen=True)
class _RateLimitRule:
    """Sliding-window call cap for a rate-limit scope."""

    max_calls: int
    window_seconds: float


@dataclass(frozen=True)
class DeviceRealtimeKpiResponse:
    """Realtime device KPI payload plus response metadata."""

    devices: list[dict[str, Any]]
    current_time_ms: int | None
    params: dict[str, Any]


@dataclass(frozen=True)
class DeviceHistoryKpiResponse:
    """Historical 5-minute device KPI rows."""

    records: list[dict[str, Any]]


@dataclass(frozen=True)
class EnergyBalance:
    """PV production, grid export, and consumption derived from live kW readings."""

    pv_production_kw: float
    grid_export_kw: float
    consumption_kw: float


# Documented limits — "Flow Control Using the API Account" (https://support.huawei.com/enterprise/en/doc/EDOC1100544235/b71c4d05/flow-control-using-the-api-account?idPath=258788303|258788491|258789989|23205712|21608721)
# and "Authentication API" (https://support.huawei.com/enterprise/en/doc/EDOC1100544235/9676f1cf/authentication-api?idPath=258788303|258788491|258789989|23205712|21608721).
# Daily list caps assume one plant (Roundup(1/100) = 1).
# Real time device data assumes one device per type (Roundup(1/100) = 1).
# Historical device data assumes one inverter and one meter (see
# ``_HISTORY_MIN_INTERVAL_SECONDS``).
_RATE_LIMIT_RULES: dict[str, _RateLimitRule] = {
    _LOGIN_PATH: _RateLimitRule(max_calls=5, window_seconds=600),
    _STATIONS_PATH: _RateLimitRule(max_calls=34, window_seconds=_SECONDS_PER_DAY),
    _DEV_LIST_PATH: _RateLimitRule(max_calls=25, window_seconds=_SECONDS_PER_DAY),
    _DEV_REAL_KPI_PATH: _RateLimitRule(max_calls=1, window_seconds=300),
    _DEVICE_HISTORY_PATH: _RateLimitRule(
        max_calls=1,
        window_seconds=_HISTORY_MIN_INTERVAL_SECONDS,
    ),
}

class FusionSolarError(Exception):
    """Raised when the FusionSolar API returns ``success: false``."""

    # Huawei documents many errors only via ``failCode``; ``message`` is often null.
    KNOWN_FAIL_CODES: ClassVar[dict[int, str]] = {
        1: "The task is partially successful.",
        2: "The task fails.",
        305: "You are not online and need to log in again.",
        401: "You do not have the related data API permission.",
        407: "The API access frequency is too high.",
        429: (
            "The total number of calls to this API exceeds the system-level limit; "
            "wait before retrying."
        ),
    }

    def __init__(
        self,
        message: str,
        *,
        fail_code: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        detail = message
        if fail_code is not None:
            detail = f"{message} (failCode={fail_code})"
        super().__init__(detail)
        self.fail_code = fail_code
        self.message = message
        self.payload = payload

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> FusionSolarError:
        """Build an error from a FusionSolar JSON response body."""
        fail_code = cls.fail_code_from_payload(payload)
        message = cls._message_from_payload(payload, fail_code=fail_code)
        return cls(message, fail_code=fail_code, payload=payload)

    @classmethod
    def fail_code_from_payload(cls, payload: dict[str, Any]) -> int | None:
        """Return ``failCode`` from a response body as an integer when possible."""
        return cls._normalize_fail_code(payload.get("failCode"))

    @staticmethod
    def _normalize_fail_code(fail_code: Any) -> int | None:
        """Return ``failCode`` as an integer when possible."""
        if fail_code is None:
            return None
        try:
            return int(fail_code)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _message_field(payload: dict[str, Any]) -> str | None:
        """Return a non-empty ``message`` value from ``payload``."""
        value = payload.get("message")
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        return text

    @classmethod
    def _known_fail_code_message(cls, fail_code: int | None) -> str | None:
        """Return the documented message for a ``failCode``, if known."""
        if fail_code is None:
            return None
        return cls.KNOWN_FAIL_CODES.get(fail_code)

    @staticmethod
    def _error_data_message(data: Any) -> str | None:
        """Return the API error string carried in ``data`` on failed requests."""
        if not isinstance(data, str):
            return None
        text = data.strip()
        if not text:
            return None
        return text

    @classmethod
    def _message_from_payload(
        cls,
        payload: dict[str, Any],
        *,
        fail_code: int | None,
    ) -> str:
        """Resolve a human-readable error message from an API response body."""
        message = cls._message_field(payload)
        if message is not None:
            return message

        data_message = cls._error_data_message(payload.get("data"))
        if data_message is not None:
            return data_message

        fail_code_message = cls._known_fail_code_message(fail_code)
        if fail_code_message is not None:
            return fail_code_message

        if fail_code is not None:
            return f"FusionSolar API request failed (failCode={fail_code})"
        return "FusionSolar API request failed"


class FusionSolarClient:
    """Thin client for the FusionSolar SmartPVMS northbound API."""

    def __init__(self, base_url: str = DEFAULT_BASE_URL) -> None:
        """Create a client for the given FusionSolar management system host.

        Parameters
        ----------
        base_url : str, optional
            API base URL, for example ``https://eu5.fusionsolar.huawei.com``.
        """
        self.base_url = base_url.rstrip("/")
        self._xsrf_token: str | None = None
        self._call_histories: dict[str, deque[float]] = {}
        self._last_response_headers: dict[str, str] = {}
        self._before_authenticated_post: Callable[[], None] | None = None

    def set_before_authenticated_post(
        self,
        callback: Callable[[], None] | None,
    ) -> None:
        """Register a hook invoked before authenticated POSTs when needed.

        Parameters
        ----------
        callback : callable or None
            Called after a proactive rate-limit wait and on failCode 305 retries.
            Pass ``None`` to clear the hook.
        """
        self._before_authenticated_post = callback

    @property
    def xsrf_token(self) -> str | None:
        """Current XSRF token, or ``None`` before ``login`` succeeds."""
        return self._xsrf_token

    def login(self, user_name: str, system_code: str) -> str:
        """Authenticate and store the XSRF token from the response headers.

        Parameters
        ----------
        user_name : str
            API account name.
        system_code : str
            API account password.

        Returns
        -------
        str
            XSRF token valid for 30 minutes.

        Raises
        ------
        FusionSolarError
            If login fails or the response omits an XSRF token.
        """
        payload = self._post(
            _LOGIN_PATH,
            {"userName": user_name, "systemCode": system_code},
            authenticated=False,
        )
        token = self._extract_xsrf_token()
        if token is None:
            if payload.get("success", False):
                fail_code = FusionSolarError.fail_code_from_payload(payload)
                raise FusionSolarError(
                    "missing xsrf-token header",
                    fail_code=fail_code,
                    payload=payload,
                )
            raise FusionSolarError.from_payload(payload)
        self._xsrf_token = token
        return token

    def list_stations(self, page_no: int = 1) -> dict[str, Any]:
        """Return the paginated plant list.

        Parameters
        ----------
        page_no : int, optional
            Page number of results (up to 100 plants per page).

        Returns
        -------
        dict[str, Any]
            API ``data`` object with ``list``, ``total``, and pagination fields.
        """
        return self._post_data(
            _STATIONS_PATH,
            {"pageNo": page_no},
        )

    def list_devices(self, station_codes: str) -> list[dict[str, Any]]:
        """Return devices for one or more comma-separated plant IDs.

        Parameters
        ----------
        station_codes : str
            Plant IDs from ``plantCode``, for example ``"NE=182468888"``.

        Returns
        -------
        list[dict[str, Any]]
            Device records including ``id``, ``devName``, and ``devTypeId``.
        """
        return self._post_data(
            _DEV_LIST_PATH,
            {"stationCodes": station_codes},
        )

    def get_device_real_kpi(
        self,
        dev_ids: str | int,
        dev_type_id: str | int,
    ) -> DeviceRealtimeKpiResponse:
        """Return realtime KPI snapshots for the given devices.

        Parameters
        ----------
        dev_ids : str or int
            Device ID or comma-separated IDs from ``list_devices``.
        dev_type_id : str or int
            Device type ID, for example ``47`` for a power sensor.

        Returns
        -------
        DeviceRealtimeKpiResponse
            Device rows in ``devices`` and ``params.currentTime`` as
            ``current_time_ms``.
        """
        payload = self._post(
            _DEV_REAL_KPI_PATH,
            {
                "devIds": str(dev_ids),
                "devTypeId": str(dev_type_id),
            },
        )
        params = payload.get("params")
        if not isinstance(params, dict):
            params = {}
        devices = payload.get("data")
        if not isinstance(devices, list):
            devices = []
        return DeviceRealtimeKpiResponse(
            devices=devices,
            current_time_ms=_current_time_ms(params),
            params=params,
        )

    def get_device_history(
        self,
        dev_dn: str,
        dev_type_id: int | str,
        start_time_ms: int,
        end_time_ms: int,
    ) -> DeviceHistoryKpiResponse:
        """Return 5-minute historical KPI rows for one device.

        The API accepts at most one device and a 24-hour window per call.

        Parameters
        ----------
        dev_dn : str
            Device DN from ``devDn`` in ``list_devices``.
        dev_type_id : str or int
            Device type ID, for example ``47`` for a power sensor.
        start_time_ms : int
            Start timestamp in milliseconds (inclusive).
        end_time_ms : int
            End timestamp in milliseconds.
        """
        if start_time_ms >= end_time_ms:
            raise ValueError("start_time_ms must be less than end_time_ms")
        window_ms = end_time_ms - start_time_ms
        if window_ms > _HISTORY_MAX_WINDOW_MS:
            raise ValueError("Time range exceeds 24 hours")
        payload = self._post(
            _DEVICE_HISTORY_PATH,
            {
                "devDn": dev_dn,
                "devTypeId": int(dev_type_id),
                "startTime": start_time_ms,
                "endTime": end_time_ms,
            },
        )
        records = payload.get("data")
        if not isinstance(records, list):
            records = []
        return DeviceHistoryKpiResponse(records=records)

    @staticmethod
    def compute_energy_balance(
        inverter_kw: float,
        meter_kw: float,
    ) -> EnergyBalance:
        """Derive PV production, grid export, and consumption from live kW values.

        Parameters
        ----------
        inverter_kw : float
            Inverter ``active_power`` in kW.
        meter_kw : float
            Meter ``active_power`` in kW (positive when exporting to the grid).

        Returns
        -------
        EnergyBalance
            ``consumption_kw`` is ``inverter_kw - meter_kw``.
        """
        consumption_kw = inverter_kw - meter_kw
        grid_export_kw = meter_kw if meter_kw > 0 else 0.0
        return EnergyBalance(
            pv_production_kw=inverter_kw,
            grid_export_kw=grid_export_kw,
            consumption_kw=consumption_kw,
        )

    def _rate_limit_scopes(self, path: str, body: dict[str, Any]) -> list[str]:
        if path == _DEV_REAL_KPI_PATH:
            return [f"{path}:{body['devTypeId']}"]
        return [path]

    def _history_for_scope(self, scope: str) -> deque[float]:
        history = self._call_histories.get(scope)
        if history is None:
            history = deque()
            self._call_histories[scope] = history
        return history

    @staticmethod
    def _prune_history(
        history: deque[float],
        window_seconds: float,
        now: float,
    ) -> None:
        while history and now - history[0] >= window_seconds:
            history.popleft()

    def _rule_for_scope(self, scope: str) -> _RateLimitRule:
        if scope.startswith(f"{_DEV_REAL_KPI_PATH}:"):
            return _RATE_LIMIT_RULES[_DEV_REAL_KPI_PATH]
        return _RATE_LIMIT_RULES[scope]

    def _seconds_until_scope_ready(
        self,
        scope: str,
        rule: _RateLimitRule,
        now: float,
    ) -> float:
        """Return seconds to sleep before ``scope`` accepts another call."""
        history = self._history_for_scope(scope)
        self._prune_history(history, rule.window_seconds, now)
        if len(history) < rule.max_calls:
            return 0.0
        return max(
            rule.window_seconds
            - (now - history[0])
            + _RATE_LIMIT_RETRY_BUFFER_SECONDS,
            0.0,
        )

    def _wait_for_scope(
        self,
        scope: str,
        rule: _RateLimitRule,
        now: float,
    ) -> tuple[float, float]:
        """Block until ``scope`` is under its rate limit.

        Returns
        -------
        tuple[float, float]
            Monotonic timestamp and total seconds slept.
        """
        waited_seconds = 0.0
        while True:
            sleep_for = self._seconds_until_scope_ready(scope, rule, now)
            if sleep_for <= 0:
                return now, waited_seconds
            logger.info(f"Rate limit: waiting {sleep_for:.1f}s for scope {scope}")
            time.sleep(sleep_for)
            waited_seconds += sleep_for
            now = time.monotonic()

    def _enforce_rate_limits(self, scopes: list[str]) -> float:
        """Sleep until all ``scopes`` are under their rate limits.

        Returns
        -------
        float
            Total seconds slept.
        """
        now = time.monotonic()
        waited_seconds = 0.0
        for scope in scopes:
            now, scope_wait = self._wait_for_scope(
                scope,
                self._rule_for_scope(scope),
                now,
            )
            waited_seconds += scope_wait
        return waited_seconds

    def _record_scope_call(self, scopes: list[str]) -> None:
        now = time.monotonic()
        for scope in scopes:
            self._history_for_scope(scope).append(now)

    def _mark_scopes_at_capacity(self, scopes: list[str]) -> None:
        """Reset scopes to full capacity after a server-side 407."""
        now = time.monotonic()
        for scope in scopes:
            rule = self._rule_for_scope(scope)
            history = self._history_for_scope(scope)
            history.clear()
            for _ in range(rule.max_calls):
                history.append(now)

    def _reauthenticate_before_post(self, *, authenticated: bool) -> None:
        """Run the pre-POST hook after idle periods or session expiry."""
        if not authenticated or self._before_authenticated_post is None:
            return
        self._before_authenticated_post()

    def _post(
        self,
        path: str,
        body: dict[str, Any],
        *,
        authenticated: bool = True,
    ) -> dict[str, Any]:
        """POST to a FusionSolar endpoint and return the full success body."""
        scopes = self._rate_limit_scopes(path, body)
        max_failcode_407_retries = _MAX_FAILCODE_407_RETRIES
        failcode_407_retries_done = 0
        failcode_305_retries_remaining = _MAX_FAILCODE_305_RETRIES
        posts_on_rate_limit = max_failcode_407_retries + 1
        # failCode 305 retries reuse the current rate-limit pass; failCode 407
        # retries advance to the next pass after waiting.
        while failcode_407_retries_done <= max_failcode_407_retries:
            post_number = failcode_407_retries_done + 1
            logger.info(
                f"POST {path} rate-limit pass {post_number}/{posts_on_rate_limit}"
            )
            waited_seconds = self._enforce_rate_limits(scopes)
            if waited_seconds > 0:
                logger.info(
                    f"POST {path} rate-limit pass {post_number}/"
                    f"{posts_on_rate_limit}: waited {waited_seconds:.1f}s "
                    f"proactively to stay within API rate limits and avoid "
                    f"failCode 407"
                )
                # Huawei marks API accounts offline after ~5 min without a data
                # call, even while the documented 30-minute XSRF-TOKEN is valid.
                # Re-login after a rate-limit sleep so the POST is not rejected
                # with failCode 305.
                self._reauthenticate_before_post(authenticated=authenticated)

            headers = {"Content-Type": "application/json"}
            if authenticated:
                if self._xsrf_token is None:
                    raise FusionSolarError("login required before calling data APIs")
                headers["xsrf-token"] = self._xsrf_token

            response = requests.post(
                f"{self.base_url}{path}",
                json=body,
                headers=headers,
                timeout=30,
            )
            response.raise_for_status()
            self._last_response_headers = dict(response.headers)

            payload = response.json()
            if payload.get("success", False):
                self._record_scope_call(scopes)
                logger.success(
                    f"POST {path} rate-limit pass {post_number}/"
                    f"{posts_on_rate_limit} succeeded"
                )
                return payload

            fail_code = FusionSolarError.fail_code_from_payload(payload)
            if (
                fail_code == _SESSION_EXPIRED_FAIL_CODE
                and failcode_305_retries_remaining > 0
            ):
                failcode_305_retries_remaining -= 1
                logger.warning(
                    f"POST {path} rate-limit pass {post_number}/"
                    f"{posts_on_rate_limit} returned failCode=305, "
                    f"re-authenticating "
                    f"({failcode_305_retries_remaining} session retries left)"
                )
                self._reauthenticate_before_post(authenticated=authenticated)
                continue
            if fail_code == 407 and failcode_407_retries_done < max_failcode_407_retries:
                logger.warning(
                    f"POST {path} rate-limit pass {post_number}/"
                    f"{posts_on_rate_limit} returned failCode=407, "
                    f"retrying after rate limit wait"
                )
                self._mark_scopes_at_capacity(scopes)
                rate_limit_wait_seconds = self._enforce_rate_limits(scopes)
                logger.info(
                    f"POST {path} rate-limit pass {post_number}/"
                    f"{posts_on_rate_limit}: failCode 407 backoff wait "
                    f"{rate_limit_wait_seconds:.1f}s"
                )
                failcode_407_retries_done += 1
                continue
            raise FusionSolarError.from_payload(payload)

        raise FusionSolarError("FusionSolar API request failed after retries")

    def _post_data(
        self,
        path: str,
        body: dict[str, Any],
        *,
        authenticated: bool = True,
    ) -> Any:
        """POST and return only the ``data`` field from the success body."""
        return self._post(path, body, authenticated=authenticated).get("data")

    def _extract_xsrf_token(self) -> str | None:
        for header_name, header_value in self._last_response_headers.items():
            if header_name.lower() == "xsrf-token":
                return header_value
        return None


def _current_time_ms(params: dict[str, Any]) -> int | None:
    """Return ``currentTime`` from a response ``params`` object."""
    value = params.get("currentTime")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def device_type_id(device: dict[str, Any]) -> int:
    """Return ``devTypeId`` as an integer."""
    return int(device["devTypeId"])


def device_dn(device: dict[str, Any]) -> str:
    """Return ``devDn`` used by the historical device data API."""
    return str(device["devDn"])


def filter_devices_by_type(
    devices: list[dict[str, Any]],
    dev_type_ids: frozenset[int],
) -> list[dict[str, Any]]:
    """Keep devices whose ``devTypeId`` is in ``dev_type_ids``."""
    return [
        device
        for device in devices
        if device_type_id(device) in dev_type_ids
    ]


def filter_inverters(devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return string and residential inverters from a device list."""
    return filter_devices_by_type(devices, INVERTER_DEV_TYPE_IDS)


def filter_meters(devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return power-sensor meters from a device list."""
    return filter_devices_by_type(devices, METER_DEV_TYPE_IDS)


def active_power_kw(
    data_items: dict[str, Any],
    dev_type_id: int,
    *,
    field: str = "active_power",
) -> float:
    """Return ``active_power`` from KPI fields in kW.

    Power sensors (``47``) and grid meters (``17``) report watts; inverters use
    kilowatts. Works for realtime ``dataItemMap`` and historical ``dataItems``.
    """
    power = float(data_items[field])
    if dev_type_id in METER_DEV_TYPE_IDS or dev_type_id == GRID_METER_DEV_TYPE_ID:
        return power / 1000.0
    return power


def active_power_kw_from_history_record(
    record: dict[str, Any],
    dev_type_id: int | str,
) -> float:
    """Return ``active_power`` in kW from one historical KPI row."""
    data_items = record.get("dataItems")
    if not isinstance(data_items, dict):
        raise ValueError("Historical record is missing dataItems")
    return active_power_kw(data_items, int(dev_type_id))


def active_power_kw_from_realtime_kpi(
    kpi_rows: list[dict[str, Any]] | DeviceRealtimeKpiResponse,
    dev_id: int | str,
    dev_type_id: int | str,
) -> float:
    """Return ``active_power`` in kW from the realtime KPI row for ``dev_id``."""
    rows = (
        kpi_rows.devices
        if isinstance(kpi_rows, DeviceRealtimeKpiResponse)
        else kpi_rows
    )
    for row in rows:
        if int(row["devId"]) == int(dev_id):
            return active_power_kw(row["dataItemMap"], int(dev_type_id))
    raise ValueError(f"No KPI row for device {dev_id}")
