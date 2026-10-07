# Antler Foods SEO Automation

An independent automation system that reads structured SEO page content and
creates/populates SEO pages in the Antler Foods CMS.

> This is a brand-new, standalone project. It is **not** derived from, and shares
> no code with, any other automation. UI-specific logic for the Antler CMS is
> implemented only after a dedicated UI investigation phase.

## Status

**Phase 1 — Foundation.** Project scaffolding, configuration, dependencies and
logging are in place. Input parsing, validation and browser automation are added
in later phases.

## Project layout

```
antler_seo/              # application package
  config.py              # configuration loading & validation
  logging_setup.py       # UTF-8 file + console logging
  models.py              # data models (Phase 2)
  input/                 # input pipelines → List[SEOPage] (Phase 2)
    base.py              # InputSource interface
    local_document.py    # local structured-document parser (MVP)
  validation/
    validator.py         # model + pre-flight validation (Phase 2)
  automation/            # browser automation (Phase 3+)
    browser.py           # Playwright lifecycle
    selectors.py         # central selector registry (Phase 4 — Antler UI)
    waits.py             # event-driven waits + bounded retry (Phase 3)
    antler_cms.py        # Antler CMS actions (Phase 4 — Antler UI)
  orchestrator.py        # per-page + batch orchestration
  reporting.py           # console + run reports

tests/                   # unit / integration tests + fixtures
seo_files/               # local SEO input documents (contents gitignored)
logs/                    # run logs + error screenshots (gitignored)
cache/                   # reserved for future image cache (gitignored)
main.py                  # CLI entry point
```

## Setup

```bash
python -m venv venv
source venv/Scripts/activate      # Windows Git Bash
pip install -r requirements.txt
playwright install chromium
```

Then copy the environment template and fill in real values:

```bash
cp .env.example .env
# edit .env — never commit it
```

### Required environment variables

| Variable          | Description                                   |
| ----------------- | --------------------------------------------- |
| `ANTLER_EMAIL`    | Antler CMS login email                        |
| `ANTLER_PASSWORD` | Antler CMS login password                     |
| `ANTLER_BASE_URL` | Antler CMS base URL (`http(s)://…`)           |

Optional: `ANTLER_HEADLESS`, `ANTLER_TIMEOUT`, `ANTLER_SLOW_MO`,
`ANTLER_SEO_DIR`, `ANTLER_LOGS_DIR` (see `.env.example`).

## Running

```bash
python main.py
```

In Phase 1 this loads configuration and initialises logging to verify the
foundation.

## Testing

```bash
pytest
```

## Security

Secrets are never committed. `.env`, tokens and credential files are
git-ignored; `.env.example` contains placeholders only.
