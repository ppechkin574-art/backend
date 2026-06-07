"""Aima ЕНТ question-generator CLI tool (standalone, API-based).

Ingest a textbook chapter -> generate ЕНТ MCQ drafts with Claude -> verify
-> (optional) dedup -> POST as DRAFTS to the backend /admin/question-drafts API.

This package is intentionally decoupled from the backend app: it talks to the
backend over HTTP and does not import the heavy app/models. See README.md.
"""

__version__ = "0.1.0"
