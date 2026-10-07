"""Input pipelines: turn an authored source into ``List[SEOPage]``.

All pipelines implement the common ``InputSource`` interface so additional
sources (e.g. a future Google Sheet/Doc/Drive pipeline) can be added without
forking the model or the orchestrator.
"""
