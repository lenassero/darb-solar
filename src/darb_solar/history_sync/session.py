"""FusionSolar authentication session."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from darb_solar.fusionsolar import DEFAULT_BASE_URL, FusionSolarClient

_TOKEN_REFRESH_AFTER = timedelta(minutes=25)


@dataclass
class FusionSolarSession:
    """Authenticated client with proactive token refresh."""

    client: FusionSolarClient
    username: str
    system_code: str
    logged_in_at: datetime

    def __post_init__(self) -> None:
        self.client.set_before_authenticated_post(self.force_login)

    def ensure_logged_in(self) -> None:
        """Re-authenticate when the XSRF token is close to expiring."""
        age = datetime.now(timezone.utc) - self.logged_in_at
        if age < _TOKEN_REFRESH_AFTER and self.client.xsrf_token is not None:
            return
        self.force_login()

    def force_login(self) -> None:
        """Authenticate and reset the login timestamp."""
        self.client.login(self.username, self.system_code)
        self.logged_in_at = datetime.now(timezone.utc)


def login_fusionsolar(
    *,
    username: str | None = None,
    system_code: str | None = None,
    base_url: str | None = None,
) -> FusionSolarSession:
    """Authenticate against FusionSolar using environment variables.

    Parameters
    ----------
    username : str or None, optional
        API account name. Defaults to ``FUSIONSOLAR_USERNAME``.
    system_code : str or None, optional
        API account password. Defaults to ``FUSIONSOLAR_SYSTEM_CODE``.
    base_url : str or None, optional
        API host. Defaults to ``FUSIONSOLAR_BASE_URL`` or the client default.

    Returns
    -------
    FusionSolarSession
        Authenticated session wrapper.

    Raises
    ------
    ValueError
        If required credentials are missing.
    """
    resolved_username = username or os.environ.get("FUSIONSOLAR_USERNAME")
    resolved_system_code = system_code or os.environ.get("FUSIONSOLAR_SYSTEM_CODE")
    if not resolved_username or not resolved_system_code:
        raise ValueError(
            "FusionSolar credentials are required; set FUSIONSOLAR_USERNAME and "
            "FUSIONSOLAR_SYSTEM_CODE."
        )

    resolved_base_url = (
        base_url
        or os.environ.get("FUSIONSOLAR_BASE_URL")
        or DEFAULT_BASE_URL
    )
    client = FusionSolarClient(base_url=resolved_base_url)
    session = FusionSolarSession(
        client=client,
        username=resolved_username,
        system_code=resolved_system_code,
        logged_in_at=datetime.min.replace(tzinfo=timezone.utc),
    )
    session.force_login()
    return session
