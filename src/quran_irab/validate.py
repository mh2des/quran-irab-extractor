"""
Validate extracted ayah text against canonical Tanzil/Uthmani reference,
and backfill any missing ayat with canonical text (no i'rab).

A Quran reference app cannot ship with incorrect or missing ayat.
This module is the foundation: every ayah position is either matched
exactly (after normalization) or backfilled with canonical text.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from .normalize import loose_match_normalize, normalize_ar
from .surahs import CANONICAL_AYAH_COUNTS, CANONICAL_NAMES

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
# simple-clean: no diacritics, no dagger alif — designed for matching
CANONICAL_MATCH_PATH = DATA_DIR / "quran-simple-clean.json"
# uthmani: full diacritics, used for display
CANONICAL_DISPLAY_PATH = DATA_DIR / "quran-uthmani.json"

# This source prepends basmala to ayah 1 of every surah; the الجدول source does not.
# We strip the basmala prefix from canonical ayah 1 of all surahs except Al-Fatiha
# (whose ayah 1 IS the basmala) and At-Tawba (which has no basmala).
_BASMALA_VARIANTS = (
    "بسم الله الرحمن الرحيم",
)


@dataclass
class Mismatch:
    surah: int
    ayah: int
    extracted: str
    canonical: str
    extracted_norm: str
    canonical_norm: str

    def to_dict(self) -> dict:
        return {
            "surah": self.surah,
            "ayah": self.ayah,
            "extracted": self.extracted,
            "canonical": self.canonical,
            "extracted_norm": self.extracted_norm,
            "canonical_norm": self.canonical_norm,
        }


@dataclass
class ValidationReport:
    total_expected: int = 6236
    matched: int = 0
    mismatched: list[Mismatch] = field(default_factory=list)
    backfilled: list[tuple[int, int]] = field(default_factory=list)  # (surah, ayah)
    duplicate_emissions: list[tuple[int, int]] = field(default_factory=list)

    @property
    def coverage(self) -> float:
        return self.matched / self.total_expected if self.total_expected else 0.0


def _strip_prepended_basmala(surah: int, ayah: int, text: str) -> str:
    """alquran.cloud prepends basmala to ayah 1 of every surah; the الجدول source
    does not. Strip it for matching/backfill purposes except for Al-Fatiha (1:1
    IS the basmala) and At-Tawba (which has no basmala)."""
    if ayah != 1 or surah in (1, 9):
        return text
    for prefix in _BASMALA_VARIANTS:
        if text.startswith(prefix):
            return text[len(prefix):].lstrip()
    return text


def load_canonical(path: Path = CANONICAL_MATCH_PATH) -> dict[tuple[int, int], str]:
    """Load canonical text keyed by (surah, ayah), with basmala prefix normalized."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    out: dict[tuple[int, int], str] = {}
    for key, text in raw.items():
        s_str, a_str = key.split(":")
        s, a = int(s_str), int(a_str)
        # Strip BOM
        text = text.lstrip("﻿").strip()
        out[(s, a)] = _strip_prepended_basmala(s, a, text)
    return out


def validate_and_backfill(
    groups: list[dict],
    canonical: dict[tuple[int, int], str] | None = None,
) -> tuple[list[dict], ValidationReport]:
    """
    Walk the extracted groups, validate against canonical Quran, backfill missing ayat.

    Returns the augmented groups (original groups untouched + backfill groups appended)
    and a ValidationReport.
    """
    if canonical is None:
        canonical = load_canonical()

    report = ValidationReport()
    emitted: set[tuple[int, int]] = set()

    # First pass: validate everything we extracted
    for g in groups:
        s = g["surah"]
        for a in g["ayat"]:
            ayah_id = (s, a["num"])
            extracted = a["text"]
            cref = canonical.get(ayah_id)
            if cref is None:
                # We extracted an ayah that doesn't exist canonically — should never happen
                report.mismatched.append(Mismatch(
                    surah=s, ayah=a["num"],
                    extracted=extracted, canonical="",
                    extracted_norm=normalize_ar(extracted),
                    canonical_norm="",
                ))
                continue

            if ayah_id in emitted:
                report.duplicate_emissions.append(ayah_id)
                continue
            emitted.add(ayah_id)

            ext_norm = normalize_ar(extracted)
            can_norm = normalize_ar(cref)
            if ext_norm == can_norm:
                report.matched += 1
            elif loose_match_normalize(extracted) == loose_match_normalize(cref):
                # Hafs Ottoman vs Tanzil simplified — same ayah, different tradition
                report.matched += 1
            else:
                report.mismatched.append(Mismatch(
                    surah=s, ayah=a["num"],
                    extracted=extracted, canonical=cref,
                    extracted_norm=ext_norm, canonical_norm=can_norm,
                ))

    # Second pass: backfill any canonical ayah we never emitted
    backfill_groups: list[dict] = []
    for (s, a), text in sorted(canonical.items()):
        if (s, a) in emitted:
            continue
        backfill_groups.append({
            "surah": s,
            "surah_name": CANONICAL_NAMES.get(s, f"سورة {s}"),
            "ayah_start": a,
            "ayah_end": a,
            "ayat": [{"num": a, "text": text, "text_normalized": normalize_ar(text)}],
            "sections": {},
            "footnotes": [],
            "source_pages": [],
            "backfilled": True,
        })
        report.backfilled.append((s, a))

    return groups + backfill_groups, report


def iter_jsonl(path: Path) -> Iterator[dict]:
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)
