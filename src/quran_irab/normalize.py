"""Arabic text normalization — used by both indexer and search-input layer.

The canonical Quran exists in two scripts:
  - Hafs standard (e.g. الجدول): full alif, no dagger alif. الْعالَمِينَ
  - Uthmani (e.g. Tanzil):       dagger alif represents some unwritten alifs. الْعَٰلَمِينَ

We normalize both into one canonical form for matching: insert a full alif for every
dagger alif before stripping tashkeel, then unify hamza/alif/ya/ta-marbuta variants.
"""

from __future__ import annotations

import re

# All Arabic diacritics + Quranic marks + tatweel that we strip during normalization.
# NOTE: dagger alif (U+0670) is intentionally NOT in this set — it's replaced with a
# full alif first (see normalize_ar), so it carries its "letter" before being removed.
_TASHKEEL_RE = re.compile(
    "[ً-ٟ"   # fathatan..wavy-hamza-below + small letters
    "ٓ"           # MADDAH ABOVE
    "ٔ"           # HAMZA ABOVE (when standalone — handled by alif map otherwise)
    "ٕ"           # HAMZA BELOW
    "ٖ-ٟ"
    "ۖ-ۭ"    # Quranic annotation signs (small high seen, sajda, etc.)
    "ـ"           # tatweel
    "]"
)
_ZW_RE = re.compile(r"[​-‏‪-‮⁦-⁩﻿]")
_QURAN_QUOTES_RE = re.compile(r"[{}«»\"]")
_WHITESPACE_RE = re.compile(r"\s+")

_DAGGER_ALIF = "ٰ"  # ٰ — replace with full alif before stripping diacritics
_ALIF_VARIANTS = str.maketrans("أإآٱ", "اااا")
_YA_VARIANTS = str.maketrans("ىئ", "يء")
_TA_MARBUTA = str.maketrans("ة", "ه")


def strip_tashkeel(text: str) -> str:
    """Remove diacritics, tatweel, and Quranic marks (but NOT dagger alif)."""
    return _TASHKEEL_RE.sub("", text)


def strip_zero_width(text: str) -> str:
    """Remove zero-width joiners, BOMs, bidi marks."""
    return _ZW_RE.sub("", text)


def normalize_ar(text: str) -> str:
    """
    Canonical form for indexing and search-input matching.
    Loses information — use only for matching, not display.

    Dagger alif (Uthmani convention) is converted to a full alif so that
    e.g. كِتَٰبَ (Uthmani) and كِتابَ (standard) collapse to the same form.
    """
    text = strip_zero_width(text)
    text = text.replace(_DAGGER_ALIF, "ا")
    text = strip_tashkeel(text)
    text = text.translate(_ALIF_VARIANTS)
    text = text.translate(_YA_VARIANTS)
    text = text.translate(_TA_MARBUTA)
    text = _QURAN_QUOTES_RE.sub("", text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()


def clean_display(text: str) -> str:
    """Light cleanup that preserves tashkeel and original letterforms."""
    text = strip_zero_width(text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()


_HAMZA_BEARERS = str.maketrans("ؤئ", "وي")  # drop the hamza on و and ي bearers


def loose_match_normalize(text: str) -> str:
    """
    Aggressive normalization for cross-tradition validation only.
    DO NOT use for FTS5 indexing — it loses meaningful distinctions.

    Collapses Hafs Ottoman script (الجدول) and Tanzil simple-clean differences:
      ؤ → و  (drop waw-hamza)
      ئ → ي  (drop yaa-hamza)
      ء → (drop standalone hamza)
      ا → (drop ALL alifs, including those introduced by my dagger-alif handler)
    Then strips tashkeel, ya/ta variants, and whitespace.
    """
    text = normalize_ar(text)
    text = text.translate(_HAMZA_BEARERS)
    text = text.replace("ء", "")
    text = text.replace("ا", "")
    # Equivalent emphatic-letter variants used inconsistently across script traditions
    text = text.replace("ص", "س").replace("ض", "د").replace("ط", "ت").replace("ظ", "ذ")
    # Strip ALL whitespace — word-boundary disagreements (e.g. بعدما vs بعد ما) are not
    # meaningful for "is this the same ayah?" validation
    text = _WHITESPACE_RE.sub("", text)
    return text
