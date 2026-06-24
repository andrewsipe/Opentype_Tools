"""Load curated OpenType policy reference data (labels, conflicts)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, List

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@lru_cache(maxsize=1)
def feature_registry() -> Dict[str, str]:
    path = _DATA_DIR / "feature_registry.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def feature_conflicts() -> Dict[str, List[str]]:
    path = _DATA_DIR / "feature_conflicts.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def feature_label(tag: str, *, fallback: str | None = None) -> str:
    """Human-readable feature label (registry, ss/cv patterns, or fallback)."""
    reg = feature_registry()
    if tag in reg:
        return reg[tag]
    if tag.startswith("ss") and len(tag) == 4 and tag[2:].isdigit():
        num = int(tag[2:])
        if 1 <= num <= 20:
            return f"Stylistic Set {num:02d}"
    if tag.startswith("cv") and len(tag) == 4 and tag[2:].isdigit():
        num = int(tag[2:])
        if 1 <= num <= 99:
            return f"Character Variant {num:02d}"
    if fallback:
        return fallback
    return tag


def installed_conflict_for(
    tag: str,
    installed_tags: set[str],
    *,
    populated_only: bool = True,
    installed_features: Dict | None = None,
) -> str | None:
    """Return an installed feature tag that conflicts with ``tag``, if any."""
    for other in feature_conflicts().get(tag, []):
        if other not in installed_tags:
            continue
        if populated_only and installed_features is not None:
            detail = installed_features.get(other)
            if detail is not None and not detail.populated:
                continue
        return other
    return None
