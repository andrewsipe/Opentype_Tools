"""OpenType feature detection and generation policy registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Literal, Optional, Tuple

from .policy_data import feature_label

from fontTools.ttLib import TTFont

from .feature_generation import FeatureCodeGenerator
from .models import ConnectTier, InstalledFeatureDetail

FeatureKind = Literal["single", "ligature", "frac", "stylistic_set"]


@dataclass(frozen=True)
class LigatureGlyphPolicyEntry:
    """Reference row for inferring ligature components from encoding or glyph naming.

    Underscore-separated names (``f_f``, ``g_h``, ``f_f_i``) are handled separately
    in :mod:`detection` and are not listed here.
    """

    components: Tuple[str, ...]
    tier: Literal["liga", "dlig"] = "liga"
    glyph_names: Tuple[str, ...] = ()
    codepoints: Tuple[int, ...] = ()


# Unicode Alphabetic Presentation Forms (U+FB00–U+FB06) + common legacy glyph names.
# Tier follows Glyphs-style defaults: fi/fl/ff → liga; ornamental pairs → dlig.
LIGATURE_GLYPH_POLICY: Tuple[LigatureGlyphPolicyEntry, ...] = (
    LigatureGlyphPolicyEntry(("f", "f"), glyph_names=("ff",), codepoints=(0xFB00,)),
    LigatureGlyphPolicyEntry(("f", "i"), glyph_names=("fi",), codepoints=(0xFB01,)),
    LigatureGlyphPolicyEntry(("f", "l"), glyph_names=("fl",), codepoints=(0xFB02,)),
    LigatureGlyphPolicyEntry(("f", "f", "i"), glyph_names=("ffi",), codepoints=(0xFB03,)),
    LigatureGlyphPolicyEntry(("f", "f", "l"), glyph_names=("ffl",), codepoints=(0xFB04,)),
    LigatureGlyphPolicyEntry(("s", "t"), "dlig", glyph_names=("st",), codepoints=(0xFB06,)),
)

STANDARD_LIGA_COMPONENTS = frozenset(
    entry.components for entry in LIGATURE_GLYPH_POLICY if entry.tier == "liga"
)

LIGATURE_TIER_BY_COMPONENTS: Dict[Tuple[str, ...], str] = {
    entry.components: entry.tier for entry in LIGATURE_GLYPH_POLICY
}


def ligature_tier_for_glyph(glyph_name: str, components: Tuple[str, ...]) -> str:
    """Route a detected ligature to ``liga`` or ``dlig`` (Glyphs-style defaults)."""
    lower = glyph_name.lower()
    if lower.endswith(".dlig"):
        return "dlig"
    if lower.endswith(".liga"):
        return "liga"
    tier = LIGATURE_TIER_BY_COMPONENTS.get(components)
    if tier:
        return tier
    if components in STANDARD_LIGA_COMPONENTS:
        return "liga"
    base = glyph_name.split(".")[0]
    if "_" in base:
        return "dlig"
    return "liga"

# U+FB05 ﬅ (long s + t) — first glyph name varies by font; resolved at detection time.
LONG_S_T_LIGATURE_CODEPOINT = 0xFB05
LONG_S_T_FIRST_GLYPH_NAMES: Tuple[str, ...] = ("longs", "f_long", "s.long")


def _build_ligature_policy_lookups() -> Tuple[
    Dict[int, Tuple[str, ...]], Dict[str, Tuple[str, ...]]
]:
    by_codepoint: Dict[int, Tuple[str, ...]] = {}
    by_glyph_name: Dict[str, Tuple[str, ...]] = {}
    for entry in LIGATURE_GLYPH_POLICY:
        for cp in entry.codepoints:
            by_codepoint[cp] = entry.components
        for name in entry.glyph_names:
            by_glyph_name[name.lower()] = entry.components
    return by_codepoint, by_glyph_name


LIGATURE_CODEPOINT_COMPONENTS, LIGATURE_GLYPH_NAME_COMPONENTS = (
    _build_ligature_policy_lookups()
)

AALT_EXCLUDE_TAGS = frozenset({"aalt"})

AALT_PREFERRED_ORDER: Tuple[str, ...] = (
    "liga",
    "dlig",
    "hlig",
    "clig",
    "rlig",
    "salt",
    "swsh",
    "calt",
    "smcp",
    "c2sc",
    "onum",
    "lnum",
    "tnum",
    "pnum",
    "sups",
    "subs",
    "ordn",
    "frac",
    "zero",
    "case",
    "titl",
    "hist",
    "numr",
    "dnom",
    "sinf",
)


def _aalt_sort_key(tag: str) -> Tuple[int, int, str]:
    if tag.startswith("ss") and len(tag) == 4 and tag[2:].isdigit():
        return (1, int(tag[2:]), tag)
    if tag.startswith("cv") and len(tag) == 4 and tag[2:].isdigit():
        return (2, int(tag[2:]), tag)
    try:
        return (0, AALT_PREFERRED_ORDER.index(tag), tag)
    except ValueError:
        return (3, 0, tag)


def aalt_source_tags(
    installed: Dict[str, InstalledFeatureDetail],
) -> List[str]:
    """Populated GSUB features to reference from ``aalt``, ordered by policy."""
    candidates = [
        tag
        for tag, detail in installed.items()
        if detail.table == "GSUB"
        and detail.populated
        and tag not in AALT_EXCLUDE_TAGS
    ]
    return sorted(candidates, key=_aalt_sort_key)


@dataclass(frozen=True)
class FeaturePolicyEntry:
    tag: str
    label: str
    kind: FeatureKind
    connect_tier: ConnectTier
    patterns: Tuple[str, ...] = ()
    generator: Optional[Callable[..., str]] = None


def _single_gen(tag: str) -> Callable[[List[Tuple[str, str]]], str]:
    def _gen(pairs: List[Tuple[str, str]]) -> str:
        method = getattr(FeatureCodeGenerator, f"generate_{tag}_feature", None)
        if method is None:
            return FeatureCodeGenerator.generate_substitution_feature(tag, pairs)
        return method(pairs)

    return _gen


# Glyphs-compatible figure suffixes (.osf, .lf, .tf, …) included alongside existing patterns.
FIGURE_VARIANT_SUFFIXES: Dict[str, Tuple[str, ...]] = {
    "onum": (".oldstyle", ".onum", ".osf", ".tosf"),
    "lnum": (".lining", ".lnum", ".lf"),
    "tnum": (".tabular", ".tnum", ".tf"),
    "pnum": (".proportional", ".pnum"),
}

SINGLE_FEATURES: Tuple[FeaturePolicyEntry, ...] = (
    FeaturePolicyEntry(
        "smcp",
        feature_label("smcp", fallback="Small Caps"),
        "single",
        ConnectTier.SIMPLE,
        (".sc", ".smallcap", ".smcp"),
    ),
    FeaturePolicyEntry(
        "onum",
        feature_label("onum", fallback="Oldstyle Figures"),
        "single",
        ConnectTier.SIMPLE,
        FIGURE_VARIANT_SUFFIXES["onum"],
    ),
    FeaturePolicyEntry(
        "lnum",
        feature_label("lnum", fallback="Lining Figures"),
        "single",
        ConnectTier.SIMPLE,
        FIGURE_VARIANT_SUFFIXES["lnum"],
    ),
    FeaturePolicyEntry(
        "tnum",
        feature_label("tnum", fallback="Tabular Figures"),
        "single",
        ConnectTier.SIMPLE,
        FIGURE_VARIANT_SUFFIXES["tnum"],
    ),
    FeaturePolicyEntry(
        "pnum",
        feature_label("pnum", fallback="Proportional Figures"),
        "single",
        ConnectTier.SIMPLE,
        FIGURE_VARIANT_SUFFIXES["pnum"],
    ),
    FeaturePolicyEntry("swsh", "Swashes", "single", ConnectTier.SIMPLE, (".swsh", ".swash")),
    FeaturePolicyEntry("calt", "Contextual Alternates", "single", ConnectTier.SIMPLE, (".calt",)),
    FeaturePolicyEntry("sups", "Superscripts", "single", ConnectTier.SIMPLE, (".superior", ".sups")),
    FeaturePolicyEntry("subs", "Subscripts", "single", ConnectTier.SIMPLE, (".inferior", ".subs")),
    FeaturePolicyEntry("ordn", "Ordinals", "single", ConnectTier.CONTEXTUAL, (".ordn",)),
    FeaturePolicyEntry("c2sc", "Caps to Small Caps", "single", ConnectTier.SIMPLE, (".c2sc",)),
    FeaturePolicyEntry("salt", "Stylistic Alternates", "single", ConnectTier.SIMPLE, (".alt", ".alt01", ".alt02")),
    FeaturePolicyEntry("zero", "Slashed Zero", "single", ConnectTier.SIMPLE, (".slash", ".zero")),
    FeaturePolicyEntry("case", "Case-Sensitive Forms", "single", ConnectTier.CONTEXTUAL, (".case",)),
    FeaturePolicyEntry("titl", "Titling Alternates", "single", ConnectTier.SIMPLE, (".titling", ".titl")),
    FeaturePolicyEntry("numr", "Numerators", "single", ConnectTier.SIMPLE, (".numr",)),
    FeaturePolicyEntry("dnom", "Denominators", "single", ConnectTier.SIMPLE, (".dnom",)),
    FeaturePolicyEntry("sinf", "Scientific Inferiors", "single", ConnectTier.SIMPLE, (".sinf",)),
    FeaturePolicyEntry("hist", "Historical Forms", "single", ConnectTier.SIMPLE, (".hist",)),
)

LIGATURE_FEATURES: Tuple[FeaturePolicyEntry, ...] = (
    FeaturePolicyEntry(
        "liga",
        feature_label("liga", fallback="Standard Ligatures"),
        "ligature",
        ConnectTier.LIGATURE,
    ),
    FeaturePolicyEntry(
        "dlig",
        feature_label("dlig", fallback="Discretionary Ligatures"),
        "ligature",
        ConnectTier.LIGATURE,
    ),
)

FRAC_FEATURE = FeaturePolicyEntry(
    "frac",
    feature_label("frac", fallback="Fractions"),
    "frac",
    ConnectTier.CONTEXTUAL,
    (".numerator", ".denominator", ".numr", ".dnom"),
)


def all_policy_entries() -> List[FeaturePolicyEntry]:
    return list(SINGLE_FEATURES) + list(LIGATURE_FEATURES) + [FRAC_FEATURE]


def policy_by_tag() -> Dict[str, FeaturePolicyEntry]:
    return {e.tag: e for e in all_policy_entries()}


def naming_policy_tags() -> frozenset[str]:
    """GSUB tags the glyph-naming scan matrix knows how to evaluate."""
    tags = {e.tag for e in all_policy_entries()}
    tags.update(f"ss{n:02d}" for n in range(1, 21))
    return frozenset(tags)


def detect_single_pairs(
    glyph_order: set[str], patterns: Tuple[str, ...]
) -> List[Tuple[str, str]]:
    pairs: List[Tuple[str, str]] = []
    for glyph_name in sorted(glyph_order):
        for pattern in patterns:
            if glyph_name.endswith(pattern):
                base = glyph_name[: -len(pattern)]
                if base in glyph_order:
                    pairs.append((base, glyph_name))
                    break
    return pairs


def detect_frac_parts(
    glyph_order: set[str], patterns: Tuple[str, ...]
) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str]]]:
    numerators: List[Tuple[str, str]] = []
    denominators: List[Tuple[str, str]] = []
    for glyph_name in sorted(glyph_order):
        for pattern in patterns:
            if not glyph_name.endswith(pattern):
                continue
            base = glyph_name[: -len(pattern)]
            if base not in glyph_order:
                continue
            if "numerator" in pattern or pattern == ".numr":
                numerators.append((base, glyph_name))
            elif "denominator" in pattern or pattern == ".dnom":
                denominators.append((base, glyph_name))
            break
    return numerators, denominators


def generate_feature_fea(
    entry: FeaturePolicyEntry,
    *,
    pairs: Optional[List[Tuple[str, str]]] = None,
    ligatures: Optional[List[Tuple[List[str], str]]] = None,
    numerators: Optional[List[Tuple[str, str]]] = None,
    denominators: Optional[List[Tuple[str, str]]] = None,
    font: Optional[TTFont] = None,
) -> str:
    """Generate FEA block for a policy entry."""
    if entry.kind == "ligature":
        ligs = ligatures or []
        if entry.tag == "dlig":
            return FeatureCodeGenerator.generate_dlig_feature(ligs)
        return FeatureCodeGenerator.generate_liga_feature(ligs)

    if entry.kind == "frac":
        return FeatureCodeGenerator.generate_frac_feature(
            numerators or [], denominators or [], font  # type: ignore[arg-type]
        )

    pairs = pairs or []
    if entry.tag == "ordn":
        return FeatureCodeGenerator.generate_ordn_feature(pairs, font)
    if entry.tag == "case":
        return FeatureCodeGenerator.generate_case_feature(pairs, font)

    gen = _single_gen(entry.tag)
    return gen(pairs)
