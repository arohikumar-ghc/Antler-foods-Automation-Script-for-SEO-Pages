"""Unit tests for Google service-account auth loading (no network)."""
import pytest

from antler_seo.config import ENV_GOOGLE_SA_KEY_FILE, ENV_GOOGLE_SHEET_URL
from antler_seo.input.google_auth import (
    DEFAULT_SCOPES,
    GoogleCredentialsError,
    load_service_account_credentials,
)


def test_env_name_constants_exist():
    assert ENV_GOOGLE_SA_KEY_FILE == "ANTLER_GOOGLE_SA_KEY_FILE"
    assert ENV_GOOGLE_SHEET_URL == "ANTLER_GOOGLE_SHEET_URL"


def test_default_scopes_are_readonly():
    assert all(s.endswith(".readonly") for s in DEFAULT_SCOPES)
    assert any("spreadsheets" in s for s in DEFAULT_SCOPES)
    assert any("documents" in s for s in DEFAULT_SCOPES)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_key_path_raises(value):
    with pytest.raises(GoogleCredentialsError):
        load_service_account_credentials(value)


def test_nonexistent_key_file_raises(tmp_path):
    missing = tmp_path / "no_such_key.json"
    with pytest.raises(GoogleCredentialsError) as exc:
        load_service_account_credentials(str(missing))
    assert "not found" in str(exc.value)
