"""Environment helpers for darb-solar."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"


def load_env(env_path: Path | None = None) -> Path | None:
    """Load variables from a ``.env`` file into ``os.environ``.

    Parameters
    ----------
    env_path : Path or None, optional
        Path to the env file. Defaults to ``PROJECT_ROOT / ".env"``.

    Returns
    -------
    Path or None
        Resolved path that was loaded, or ``None`` if the file does not exist.
    """
    path = (env_path or DEFAULT_ENV_PATH).resolve()
    if not path.is_file():
        return None
    load_dotenv(path)
    return path
