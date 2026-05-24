"""Validator and backfill tests."""

import pytest

from quran_irab.validate import (
    _strip_prepended_basmala,
    load_canonical,
    validate_and_backfill,
)


class TestBasmalaStripping:
    def test_fatiha_ayah_1_keeps_basmala(self):
        # Surah 1's ayah 1 IS the basmala — must not be stripped
        text = "بسم الله الرحمن الرحيم"
        assert _strip_prepended_basmala(1, 1, text) == text

    def test_at_tawba_has_no_basmala(self):
        # At-Tawba (surah 9) is the one surah without basmala — don't try to strip
        text = "براءة من الله ورسوله"
        assert _strip_prepended_basmala(9, 1, text) == text

    def test_baqarah_ayah_1_strips_basmala_prefix(self):
        text = "بسم الله الرحمن الرحيم الم"
        assert _strip_prepended_basmala(2, 1, text) == "الم"

    def test_non_ayah_1_untouched(self):
        # Only ayah 1 of each surah has the prepended basmala issue
        text = "اللهم اغفر لي"
        assert _strip_prepended_basmala(2, 5, text) == text


class TestCanonicalLoading:
    def test_loads_6236_ayat(self):
        canonical = load_canonical()
        assert len(canonical) == 6236

    def test_has_all_surahs(self):
        canonical = load_canonical()
        surahs = {s for s, _ in canonical}
        assert surahs == set(range(1, 115))


class TestValidateAndBackfill:
    def test_perfect_match_no_backfill(self):
        groups = [{
            "surah": 1, "surah_name": "الفاتحة",
            "ayah_start": 1, "ayah_end": 1,
            "ayat": [{"num": 1, "text": "بسم الله الرحمن الرحيم"}],
            "sections": {}, "footnotes": [], "source_pages": [],
        }]
        canonical = {(1, 1): "بسم الله الرحمن الرحيم"}
        # Use a partial canonical so we don't backfill the other 6235 ayat
        augmented, report = validate_and_backfill(groups, canonical=canonical)
        assert report.matched == 1
        assert len(report.mismatched) == 0
        assert len(report.backfilled) == 0
        assert len(augmented) == 1

    def test_missing_ayah_is_backfilled(self):
        groups = [{
            "surah": 1, "surah_name": "الفاتحة",
            "ayah_start": 1, "ayah_end": 1,
            "ayat": [{"num": 1, "text": "بسم الله الرحمن الرحيم"}],
            "sections": {}, "footnotes": [], "source_pages": [],
        }]
        canonical = {
            (1, 1): "بسم الله الرحمن الرحيم",
            (1, 2): "الحمد لله رب العالمين",
        }
        augmented, report = validate_and_backfill(groups, canonical=canonical)
        assert report.matched == 1
        assert len(report.backfilled) == 1
        assert report.backfilled[0] == (1, 2)
        # A new backfill group was appended
        assert len(augmented) == 2
        backfill = augmented[1]
        assert backfill.get("backfilled") is True
        assert backfill["ayat"][0]["text"] == "الحمد لله رب العالمين"

    def test_script_variant_matches_loosely(self):
        # The الجدول Hafs spelling vs Tanzil simple-clean — different but same ayah
        groups = [{
            "surah": 2, "surah_name": "البقرة",
            "ayah_start": 14, "ayah_end": 14,
            "ayat": [{"num": 14, "text": "وَإِذَا لَقُوا الَّذِينَ آمَنُوا قَالُوا آمَنَّا"}],
            "sections": {}, "footnotes": [], "source_pages": [],
        }]
        canonical = {(2, 14): "وإذا لقوا الذين آمنوا قالوا آمنا"}
        _, report = validate_and_backfill(groups, canonical=canonical)
        assert report.matched == 1
