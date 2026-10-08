"""Guard: no credential-like literals committed in the source package."""
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[2] / "antler_seo"

# Substrings that would indicate a leaked key/secret in source.
FORBIDDEN = [
    "-----BEGIN PRIVATE KEY-----",
    "-----BEGIN RSA PRIVATE KEY-----",
    '"private_key"',
    "service_account.json contents",
]


def _py_files():
    return list(PACKAGE.rglob("*.py"))


def test_source_files_exist():
    assert _py_files(), "expected to find antler_seo source files"


def test_no_private_keys_in_source():
    offenders = []
    for path in _py_files():
        text = path.read_text(encoding="utf-8")
        for needle in FORBIDDEN:
            if needle in text:
                offenders.append(f"{path}: {needle!r}")
    assert not offenders, f"possible secret(s) in source: {offenders}"
