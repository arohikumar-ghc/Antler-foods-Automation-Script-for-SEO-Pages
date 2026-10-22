"""
Google authentication for the cloud input layer (OAuth 2.0 installed-app flow).

This module is the single owner of Google authentication. The Sheet and Doc
modules consume the returned credentials; they never run their own OAuth flow.

Flow (see :func:`load_oauth_credentials`):
  * a cached ``token.json`` is reused when valid (no browser),
  * an expired token with a refresh token is refreshed and re-saved,
  * otherwise an installed-app OAuth flow runs (browser consent) using
    ``credentials.json`` and the result is saved to ``token.json``.

File paths come from configuration/environment; no credential values are ever
hard-coded. ``credentials.json`` / ``token.json`` are git-ignored and must never
be committed. Google libraries are imported lazily so importing this module (and
running the default, non-live test suite) does not require them or any network.

Scopes: Sheets is READ/WRITE (a later phase may write status back); Docs and
Drive are read-only. Sheet write-back is NOT implemented in this phase.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

from antler_seo.logging_setup import get_logger

logger = get_logger("input.google_auth")

# OAuth scopes. Sheets is intentionally read/write for future status write-back
# (not implemented yet); Docs and Drive are read-only.
OAUTH_SCOPES: tuple[str, ...] = (
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
)


class GoogleAuthError(Exception):
    """Raised when Google authentication cannot be completed."""


# Backward-compatible alias (previous service-account name).
GoogleCredentialsError = GoogleAuthError


def _save_credentials(creds, token_file: str) -> None:
    """Persist authorized user credentials to the token file (JSON)."""
    try:
        Path(token_file).write_text(creds.to_json(), encoding="utf-8")
        logger.info("Saved Google OAuth token to %s", token_file)
    except OSError as exc:
        raise GoogleAuthError(
            f"Could not write token file {token_file}: {exc}"
        ) from exc


def load_oauth_credentials(
    credentials_file: Optional[str],
    token_file: Optional[str],
    scopes: Sequence[str] = OAUTH_SCOPES,
    *,
    allow_interactive: bool = True,
):
    """Load Google OAuth user credentials, authorizing on first run.

    Resolution order:
      1. If ``token_file`` exists, load the cached credentials.
      2. If they are valid, reuse them (no browser).
      3. If they are expired and carry a refresh token, refresh and re-save.
      4. Otherwise run the installed-app OAuth flow (browser consent) using
         ``credentials_file`` and save the result to ``token_file``.

    Args:
        credentials_file: Path to the OAuth installed-app client config
            (``credentials.json``). Required when an interactive flow is needed.
        token_file: Path to the cached user token (``token.json``).
        scopes: OAuth scopes to request (defaults to :data:`OAUTH_SCOPES`).
        allow_interactive: When False, the browser flow is never launched; if
            valid cached credentials are unavailable a :class:`GoogleAuthError`
            is raised instead (useful for headless/non-interactive contexts and
            deterministic tests).

    Returns:
        A ``google.oauth2.credentials.Credentials`` instance.

    Raises:
        GoogleAuthError: If the Google libraries are missing, the client config
            is required but absent, an interactive flow is needed but disallowed,
            or authentication otherwise fails.
    """
    scopes = list(scopes)

    try:
        # Lazy imports: only needed when actually authenticating to Google.
        from google.oauth2.credentials import Credentials  # type: ignore
        from google.auth.transport.requests import Request  # type: ignore
    except Exception as exc:  # pragma: no cover - exercised when lib absent
        raise GoogleAuthError(
            "Google auth libraries are not installed. Install them with "
            "`pip install -r requirements.txt` (google-auth, "
            "google-auth-oauthlib, google-api-python-client)."
        ) from exc

    creds = None
    token_path = Path(token_file) if token_file else None

    # 1/2. Reuse a cached token when present.
    if token_path and token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), scopes)
            logger.info("Loaded cached Google OAuth token from %s", token_path)
        except Exception as exc:
            logger.warning(
                "Cached token %s is unusable (%s); will re-authorize",
                token_path,
                exc,
            )
            creds = None

    if creds and creds.valid:
        return creds

    # 3. Refresh an expired token when a refresh token is available.
    if creds and getattr(creds, "expired", False) and getattr(
        creds, "refresh_token", None
    ):
        try:
            creds.refresh(Request())
            _save_credentials(creds, str(token_path))
            logger.info("Refreshed expired Google OAuth token")
            return creds
        except Exception as exc:
            logger.warning(
                "Token refresh failed (%s); will re-authorize", exc
            )
            creds = None

    # 4. Fall back to the installed-app OAuth flow.
    if not allow_interactive:
        raise GoogleAuthError(
            "No valid cached Google credentials and interactive authorization "
            "is disabled. Provide a valid token file or allow the OAuth flow."
        )

    if not credentials_file or not str(credentials_file).strip():
        raise GoogleAuthError(
            "No OAuth client configuration configured. Set "
            "ANTLER_GOOGLE_CREDENTIALS_FILE to the path of your OAuth "
            "installed-app client JSON (see .env.example)."
        )
    if not Path(credentials_file).exists():
        raise GoogleAuthError(
            f"OAuth client configuration not found: {credentials_file}"
        )

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
    except Exception as exc:  # pragma: no cover - exercised when lib absent
        raise GoogleAuthError(
            "google-auth-oauthlib is not installed. Install it with "
            "`pip install -r requirements.txt`."
        ) from exc

    try:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(credentials_file), scopes
        )
        creds = flow.run_local_server(port=0)
    except Exception as exc:
        raise GoogleAuthError(
            f"OAuth authorization failed: {exc}"
        ) from exc

    if token_path:
        _save_credentials(creds, str(token_path))
    logger.info("Completed Google OAuth authorization")
    return creds
