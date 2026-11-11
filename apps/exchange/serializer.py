"""Canonical JSON text for a stored Test Document."""

from __future__ import annotations

import hashlib
import json

from .importer import import_document


def export_document(document: dict) -> str:
    """Canonical, human-readable JSON (fixed key order, ids and defaults filled in).

    Raises ValueError if the stored document is no longer valid.
    """
    result = import_document(document)
    if not result.ok:
        raise ValueError(result.report.as_text())
    return json.dumps(result.document, indent=2, ensure_ascii=False) + "\n"


def content_hash(document: dict) -> str:
    """sha256 of the document's canonical compact JSON (independent of key order)."""
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
