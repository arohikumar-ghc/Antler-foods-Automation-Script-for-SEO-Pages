"""
Antler Foods SEO Automation.

An independent automation system that reads structured SEO page content and
creates/populates SEO pages in the Antler Foods CMS.

This package is intentionally organised so that Antler-UI-specific logic lives
only in ``antler_seo.automation`` (populated during the UI investigation phase).
Everything else is UI-agnostic business logic.

Importing this package must never require a browser or any Antler UI knowledge,
so submodules are not imported here eagerly.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
