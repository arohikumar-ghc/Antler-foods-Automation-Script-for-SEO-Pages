"""Unit tests for Google OAuth installed-app auth loading (no network).

The Google libraries are imported lazily inside load_oauth_credentials, so we
inject fakes via sys.modules before calling it. No real credentials, tokens,
Sheet IDs, or secrets appear here.
"""
import sys
import types

import pytest

from antler_seo.config import (
    ENV_GOOGLE_CREDENTIALS_FILE,
    ENV_GOOGLE_SHEET_URL,
    ENV_GOOGLE_TOKEN_FILE,
)
from antler_seo.input.google_auth import (
    GoogleAuthError,
    GoogleCredentialsError,
    OAUTH_SCOPES,
    load_oauth_credentials,
)


class FakeCreds:
    """Stand-in for google.oauth2.credentials.Credentials."""

    def __init__(self, valid=True, expired=False, refresh_token=None, label="cached"):
        self.valid = valid
        self.expired = expired
        self.refresh_token = refresh_token
        self.label = label
        self.refreshed = False

    def refresh(self, request):
        self.refreshed = True
        self.valid = True
        self.expired = False

    def to_json(self):
        return '{"token": "fake", "label": "%s"}' % self.label


class _Recorder:
    """Tracks whether the OAuth browser flow was launched."""

    def __init__(self):
        self.flow_launched = False
        self.from_file_called_with = None


def _install_fake_google(monkeypatch, recorder, *, cached=None, flow_result=None):
    """Inject fake google modules used by load_oauth_credentials.

    cached: FakeCreds returned by Credentials.from_authorized_user_file, or an
            Exception instance to raise (simulating an unusable token).
    flow_result: FakeCreds returned by the installed-app flow.
    """
    oauth2_creds_mod = types.ModuleType("google.oauth2.credentials")

    class FakeCredentials:
        @staticmethod
        def from_authorized_user_file(path, scopes):
            if isinstance(cached, Exception):
                raise cached
            if cached is None:
                raise AssertionError("from_authorized_user_file called unexpectedly")
            return cached

    oauth2_creds_mod.Credentials = FakeCredentials

    requests_mod = types.ModuleType("google.auth.transport.requests")

    class FakeRequest:
        pass

    requests_mod.Request = FakeRequest

    flow_mod = types.ModuleType("google_auth_oauthlib.flow")

    class FakeInstalledAppFlow:
        def __init__(self):
            self._scopes = None

        @classmethod
        def from_client_secrets_file(cls, path, scopes):
            recorder.from_file_called_with = (path, list(scopes))
            inst = cls()
            inst._scopes = list(scopes)
            return inst

        def run_local_server(self, port=0):
            recorder.flow_launched = True
            return flow_result

    flow_mod.InstalledAppFlow = FakeInstalledAppFlow

    monkeypatch.setitem(sys.modules, "google.oauth2.credentials", oauth2_creds_mod)
    monkeypatch.setitem(sys.modules, "google.auth.transport.requests", requests_mod)
    monkeypatch.setitem(sys.modules, "google_auth_oauthlib.flow", flow_mod)


def test_env_name_constants_exist():
    assert ENV_GOOGLE_CREDENTIALS_FILE == "ANTLER_GOOGLE_CREDENTIALS_FILE"
    assert ENV_GOOGLE_TOKEN_FILE == "ANTLER_GOOGLE_TOKEN_FILE"
    assert ENV_GOOGLE_SHEET_URL == "ANTLER_GOOGLE_SHEET_URL"


def test_scopes_exact():
    assert OAUTH_SCOPES == (
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/documents.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    )
    assert OAUTH_SCOPES[0].endswith("/spreadsheets")
    assert OAUTH_SCOPES[1].endswith(".readonly")
    assert OAUTH_SCOPES[2].endswith(".readonly")


def test_google_credentials_error_is_alias():
    assert GoogleCredentialsError is GoogleAuthError


def test_valid_token_reused_without_browser(monkeypatch, tmp_path):
    token = tmp_path / "token.json"
    token.write_text("{}", encoding="utf-8")
    recorder = _Recorder()
    cached = FakeCreds(valid=True)
    _install_fake_google(monkeypatch, recorder, cached=cached)

    creds = load_oauth_credentials("credentials.json", str(token))

    assert creds is cached
    assert recorder.flow_launched is False


def test_missing_token_triggers_flow_and_saves(monkeypatch, tmp_path):
    token = tmp_path / "token.json"
    creds_file = tmp_path / "credentials.json"
    creds_file.write_text("{}", encoding="utf-8")
    recorder = _Recorder()
    new_creds = FakeCreds(valid=True, label="new")
    _install_fake_google(monkeypatch, recorder, cached=None, flow_result=new_creds)

    creds = load_oauth_credentials(str(creds_file), str(token))

    assert creds is new_creds
    assert recorder.flow_launched is True
    assert recorder.from_file_called_with[1] == list(OAUTH_SCOPES)
    assert token.exists()
    assert "new" in token.read_text(encoding="utf-8")


def test_expired_token_refreshes_and_persists(monkeypatch, tmp_path):
    token = tmp_path / "token.json"
    token.write_text("{}", encoding="utf-8")
    recorder = _Recorder()
    cached = FakeCreds(valid=False, expired=True, refresh_token="r", label="refreshed")
    _install_fake_google(monkeypatch, recorder, cached=cached)

    creds = load_oauth_credentials("credentials.json", str(token))

    assert creds is cached
    assert cached.refreshed is True
    assert recorder.flow_launched is False
    assert "refreshed" in token.read_text(encoding="utf-8")


def test_unusable_cached_token_falls_back_to_flow(monkeypatch, tmp_path):
    token = tmp_path / "token.json"
    token.write_text("garbage", encoding="utf-8")
    creds_file = tmp_path / "credentials.json"
    creds_file.write_text("{}", encoding="utf-8")
    recorder = _Recorder()
    new_creds = FakeCreds(valid=True, label="reauth")
    _install_fake_google(
        monkeypatch, recorder, cached=ValueError("corrupt token"), flow_result=new_creds
    )

    creds = load_oauth_credentials(str(creds_file), str(token))

    assert creds is new_creds
    assert recorder.flow_launched is True


def test_expired_without_refresh_token_falls_back_to_flow(monkeypatch, tmp_path):
    token = tmp_path / "token.json"
    token.write_text("{}", encoding="utf-8")
    creds_file = tmp_path / "credentials.json"
    creds_file.write_text("{}", encoding="utf-8")
    recorder = _Recorder()
    cached = FakeCreds(valid=False, expired=True, refresh_token=None)
    new_creds = FakeCreds(valid=True, label="reauth")
    _install_fake_google(monkeypatch, recorder, cached=cached, flow_result=new_creds)

    creds = load_oauth_credentials(str(creds_file), str(token))

    assert creds is new_creds
    assert recorder.flow_launched is True


def test_missing_client_config_raises(monkeypatch, tmp_path):
    token = tmp_path / "token.json"
    missing_creds = tmp_path / "credentials.json"
    recorder = _Recorder()
    _install_fake_google(monkeypatch, recorder, cached=None)

    with pytest.raises(GoogleAuthError) as exc:
        load_oauth_credentials(str(missing_creds), str(token))
    assert "not found" in str(exc.value)
    assert recorder.flow_launched is False


def test_empty_client_config_path_raises(monkeypatch, tmp_path):
    token = tmp_path / "token.json"
    recorder = _Recorder()
    _install_fake_google(monkeypatch, recorder, cached=None)

    with pytest.raises(GoogleAuthError):
        load_oauth_credentials("", str(token))
    assert recorder.flow_launched is False


def test_non_interactive_without_valid_token_raises(monkeypatch, tmp_path):
    token = tmp_path / "token.json"
    creds_file = tmp_path / "credentials.json"
    creds_file.write_text("{}", encoding="utf-8")
    recorder = _Recorder()
    _install_fake_google(monkeypatch, recorder, cached=None)

    with pytest.raises(GoogleAuthError):
        load_oauth_credentials(str(creds_file), str(token), allow_interactive=False)
    assert recorder.flow_launched is False


def test_no_service_account_in_production_auth_module():
    import inspect
    import antler_seo.input.google_auth as mod

    src = inspect.getsource(mod)
    assert "service_account" not in src
    assert "from_service_account_file" not in src


def test_no_secrets_in_this_test_file():
    with open(__file__, encoding="utf-8") as fh:
        text = fh.read()
    # Build the forbidden markers from parts so the literals never appear in
    # this file (which would make the check match itself).
    real_sheet_id_prefix = "18dV" + "aguR"
    private_key_marker = "BEGIN PRIVATE" + " KEY"
    real_password = "Admin" + "@123"
    assert real_sheet_id_prefix not in text
    assert private_key_marker not in text
    assert real_password not in text
