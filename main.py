"""
Antler Foods SEO Automation — command-line entry point.

Phase 1 scope: wire configuration loading and logging so the foundation can be
run and verified end to end. Input parsing, validation and browser automation
are added in later phases and are intentionally not invoked here yet.
"""
from __future__ import annotations

import sys

from antler_seo import __version__
from antler_seo.config import Config, ConfigError
from antler_seo.logging_setup import setup_logging


def main(argv: list[str] | None = None) -> int:
    """Load configuration, initialise logging, and report readiness.

    Returns a process exit code (0 on success, non-zero on configuration error).
    """
    print(f"Antler Foods SEO Automation v{__version__}")
    print("=" * 72)

    try:
        config = Config.from_env()
    except ConfigError as exc:
        print(f"\nConfiguration error:\n{exc}")
        print("\nSee .env.example for the required variables.")
        return 1

    logger = setup_logging(log_dir=config.logs_dir)
    logger.info("Configuration loaded: %s", config.redacted())
    logger.info("Foundation ready. Later phases will add parsing, validation "
                "and Antler UI automation.")

    print("\nFoundation OK. Configuration loaded and logging initialised.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
