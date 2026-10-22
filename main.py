"""
Antler Foods SEO Automation — command-line entry point.

Thin CLI over the existing orchestrator: it parses arguments and forwards to
``antler_seo.orchestrator.run_from_config`` — no orchestration logic lives here.

Safety: publishing and Google Sheet write-back are OFF unless explicitly
requested with ``--publish`` / ``--write-back``.
"""
from __future__ import annotations

import argparse
import sys

from antler_seo import __version__
from antler_seo.config import Config, ConfigError
from antler_seo.logging_setup import setup_logging


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="antler-seo",
        description="Create Antler SEO pages from the Google Sheet -> Doc pipeline.",
    )
    p.add_argument(
        "--restaurant", action="append", default=None, metavar="NAME",
        help="Restrict to this restaurant (repeatable). Default: all pending rows.",
    )
    pages = p.add_mutually_exclusive_group()
    pages.add_argument(
        "--all-pages", action="store_true",
        help="Process all pages in each restaurant's document (default).",
    )
    pages.add_argument(
        "--max-pages", type=int, default=None, metavar="N",
        help="Process at most N pages per restaurant (a subset run is never "
             "marked Completed).",
    )
    p.add_argument(
        "--allow-content-mismatch", action="store_true",
        help="Allow pages whose content does not reference the restaurant "
             "(use only for authorized test restaurants).",
    )
    p.add_argument(
        "--publish", action="store_true",
        help="Publish pages after creation (default: create drafts only).",
    )
    # Write-back is ON by default for the normal full-batch command; opt out
    # with --no-write-back (e.g. a dry run or single-restaurant test).
    wb = p.add_mutually_exclusive_group()
    wb.add_argument(
        "--write-back", dest="write_back", action="store_true", default=True,
        help="Write results (created count / elapsed / notes) to Sheet columns "
             "E:G for every attempted restaurant (DEFAULT ON).",
    )
    wb.add_argument(
        "--no-write-back", dest="write_back", action="store_false",
        help="Do NOT write anything back to the Google Sheet (dry run).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    print(f"Antler Foods SEO Automation v{__version__}")
    print("=" * 72)

    parser = _build_parser()
    args = parser.parse_args(argv)

    # Argument validation.
    if args.max_pages is not None:
        if args.all_pages:
            parser.error("--max-pages and --all-pages are mutually exclusive")
        if args.max_pages < 1:
            parser.error("--max-pages must be a positive integer (>= 1)")

    try:
        config = Config.from_env()
    except ConfigError as exc:
        print(f"\nConfiguration error:\n{exc}")
        print("\nSee .env.example for the required variables.")
        return 1

    logger = setup_logging(log_dir=config.logs_dir)
    logger.info("Configuration loaded: %s", config.redacted())

    if not config.google_sheet_url:
        print("\nNo ANTLER_GOOGLE_SHEET_URL configured; nothing to run.")
        return 1

    # Lazy import so a missing browser/Google stack can't break `--help`.
    from antler_seo.orchestrator import run_from_config

    print("\nRun configuration:")
    print(f"  Restaurants:         {args.restaurant or 'ALL pending'}")
    print(f"  Max pages:           {args.max_pages if args.max_pages else 'all'}")
    print(f"  Allow mismatch:      {args.allow_content_mismatch}")
    print(f"  Publish:             {args.publish}")
    print(f"  Write-back to Sheet: {args.write_back}")
    print("")

    results = run_from_config(
        config,
        publish=args.publish,
        write_back=args.write_back,
        max_pages=args.max_pages,
        restaurants=args.restaurant,
        allow_content_mismatch=args.allow_content_mismatch,
    )

    # Per-page results + per-restaurant summary. The summary reports the outcome
    # of the creation workflow (success/partial/failed/skipped) as computed by
    # the orchestrator; it does NOT independently re-verify Draft status.
    print("\n" + "=" * 72)
    print("RESULTS (creation-workflow outcome)")
    print("=" * 72)
    tot = {"success": 0, "partial": 0, "failed": 0, "skipped": 0, "pages": 0}
    restaurant_errors = 0
    for res in results:
        print("\n" + res.console_summary())
        print(f"  Completed(write-back value): {res.completed_value()} "
              f"| is_complete={res.is_complete}")
        tot["success"] += res.success
        tot["partial"] += res.partial
        tot["failed"] += res.failed
        tot["skipped"] += res.skipped
        tot["pages"] += res.total
        if res.errors:
            restaurant_errors += len(res.errors)

    print("\n" + "-" * 72)
    print(f"Restaurants processed: {len(results)}")
    print(f"Pages: total={tot['pages']} success={tot['success']} "
          f"partial={tot['partial']} failed={tot['failed']} "
          f"skipped={tot['skipped']}")
    print(f"Restaurant-level errors: {restaurant_errors}")
    if args.publish:
        print("Note: --publish was set; created pages were published.")
    else:
        print("Note: pages created as drafts (publish disabled).")

    # Non-zero exit if anything failed or was partial, or if any restaurant had
    # a restaurant-level error (e.g. content mismatch, subset run, input error).
    ok = (
        tot["failed"] == 0
        and tot["partial"] == 0
        and restaurant_errors == 0
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
