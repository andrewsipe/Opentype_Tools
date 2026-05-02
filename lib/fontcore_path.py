"""Locate the repo root that contains FontCore and add it to sys.path (once).

Entry points call :func:`ensure_fontcore_on_path` before importing ``FontCore`` or ``lib``.
Other ``lib`` modules may import this module to guarantee path setup when imported first
from tooling that did not bootstrap.
"""

from __future__ import annotations

import sys
from pathlib import Path

_done: Path | None = None


def ensure_fontcore_on_path(start: Path | None = None) -> Path:
    """Walk upward from ``start`` until ``FontCore`` exists; insert that dir on sys.path."""
    global _done
    origin = Path(start).resolve() if start is not None else Path(__file__).resolve().parent
    repo = origin
    while not (repo / "FontCore").exists() and repo.parent != repo:
        repo = repo.parent

    if _done == repo:
        return repo

    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))

    _done = repo
    return repo
