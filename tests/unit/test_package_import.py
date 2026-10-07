"""Smoke test: the package imports without requiring a browser or Antler UI."""


def test_import_package():
    import antler_seo

    assert antler_seo.__version__


def test_import_core_modules():
    # Config and logging must import cleanly as part of the foundation.
    from antler_seo import config, logging_setup  # noqa: F401

    assert hasattr(config, "Config")
    assert hasattr(logging_setup, "setup_logging")
