"""
Google authentication for the cloud input layer (service-account only).

Loads read-only Google credentials from a service-account JSON key whose path
comes from configuration/environment — never hard-coded, never committed. The
Google libraries are imported lazily so importing this module (and running the
default test suite) does not require them.

Setup (see ``.env.example``): create a service account, enable the Sheets and
Docs APIs, share the control-panel Sheet and each restaurant's Doc with the
service account's email, and point ``ANTLER_GOOGLE_SA_KEY_FILE`` at the key.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Sequence

from antler_seo.logging_setup import get_logger

logger = get_logger("input.google_auth")

# Read-only scopes: this layer never writes to Google (writeback is a later,
# separate phase).
DEFAULT_SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
)


class GoogleCredentialsError(Exception):
    """Raised when Google credentials cannot be loaded."""


def load_service_account_credentials(
    key_file: Optional[str],
    scopes: Sequence[str] = DEFAULT_SCOPES,
):
    """Load service-account credentials from a JSON key file.

    Args:
        key_file: Path to the service-account JSON key. Required.
        scopes: OAuth scopes to request (defaults to read-only Sheets/Docs/Drive).

    Returns:
        A ``google.oauth2.service_account.Credentials`` instance.

    Raises:
        GoogleCredentialsError: If the path is missing/empty, the file does not
            exist, the Google library is not installed, or the key is invalid.
    """
    if not key_file or not str(key_file).strip():
        raise GoogleCredentialsError(
            "No service-account key file configured. Set "
            "ANTLER_GOOGLE_SA_KEY_FILE to the path of your service-account JSON "
            "key (see .env.example)."
        )

    path = Path(key_file)
    if not path.exists():
        raise GoogleCredentialsError(
            f"Service-account key file not found: {path}"
        )

    try:
        # Lazy import: only required when actually authenticating to Google.
        from google.oauth2 import service_account  # type: ignore
    except Exception as exc:  # pragma: no cover - exercised when lib absent
        raise GoogleCredentialsError(
            "Google auth libraries are not installed. Install them with "
            "`pip install -r requirements.txt` (google-auth, "
            "google-api-python-client)."
        ) from exc

    try:
        creds = service_account.Credentials.from_service_account_file(
            str(path), scopes=list(scopes)
        )
    except Exception as exc:
        raise GoogleCredentialsError(
            f"Could not load service-account credentials from {path}: {exc}"
        ) from exc

    logger.info("Loaded Google service-account credentials from %s", path)
    return creds
