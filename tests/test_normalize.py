"""Arabic normalization — covers tashkeel, dagger alif, hamza variants, and
cross-tradition matching."""

from quran_irab.normalize import (
    clean_display,
    loose_match_normalize,
    normalize_ar,
    strip_tashkeel,
)


class TestStripTashkeel:
    def test_basic_diacritics(self):
        assert strip_tashkeel("بِسْمِ اللَّهِ") == "بسم الله"

    def test_tanween(self):
        assert strip_tashkeel("كِتَابٌ") == "كتاب"

    def test_tatweel(self):
        assert strip_tashkeel("مـحـمـد") == "محمد"

    def test_quranic_marks(self):
        # ۚ ۛ ۖ are Quranic pause/annotation marks
        assert strip_tashkeel("الله ۚ لا") == "الله  لا"


class TestNormalizeAr:
    def test_alif_variants(self):
        assert normalize_ar("أحمد") == "احمد"
        assert normalize_ar("إبراهيم") == "ابراهيم"
        assert normalize_ar("آدم") == "ادم"

    def test_ya_variants(self):
        assert normalize_ar("على") == "علي"
        assert normalize_ar("شيء") == "شيء"  # already canonical

    def test_ta_marbuta(self):
        assert normalize_ar("صلاة") == "صلاه"

    def test_dagger_alif_to_alif(self):
        # Uthmani: العَٰلَمِينَ should match standard العالمين
        uthmani = "العَٰلَمِينَ"
        standard = "العالمين"
        assert normalize_ar(uthmani) == normalize_ar(standard)

    def test_normalize_strips_tashkeel(self):
        std = "بِسْمِ اللهِ الرَّحْمنِ الرَّحِيمِ"
        assert normalize_ar(std) == "بسم الله الرحمن الرحيم"

    def test_dagger_alif_becomes_full_alif(self):
        # Uthmani text where dagger alif stands in for an unwritten alif
        assert normalize_ar("الرَّحْمَٰنِ") == "الرحمان"
        # ...meaning Uthmani vs Hafs forms differ by ONE letter (alif) here.
        # Cross-tradition matching requires loose_match_normalize — see below.

    def test_strips_curly_braces(self):
        assert normalize_ar("{الحمد}") == "الحمد"

    def test_collapses_whitespace(self):
        assert normalize_ar("الحمد   لله    رب") == "الحمد لله رب"


class TestLooseMatchNormalize:
    def test_hamza_bearer_variants(self):
        # يؤمنون vs يءومنون (alquran.cloud sometimes uses the latter)
        assert loose_match_normalize("يؤمنون") == loose_match_normalize("يءومنون")

    def test_word_boundary_disagreement(self):
        # Hafs writes بعدما as two words, Tanzil as one
        assert loose_match_normalize("بعد ما سمعه") == loose_match_normalize("بعدما سمعه")

    def test_emphatic_letter_variants(self):
        # ويبصط vs ويبسط — both are valid readings
        assert loose_match_normalize("ويبصط") == loose_match_normalize("ويبسط")

    def test_dagger_alif_cross_tradition(self):
        # Uthmani الرَّحْمَٰنِ and Hafs الرَّحْمنِ ARE the same word in two scripts;
        # only the loose-match normalizer treats them as equal (drops alif).
        assert loose_match_normalize("الرَّحْمَٰنِ") == loose_match_normalize("الرَّحْمنِ")


class TestCleanDisplay:
    def test_preserves_tashkeel(self):
        text = "بِسْمِ اللَّهِ"
        assert clean_display(text) == text

    def test_strips_bom(self):
        assert clean_display("﻿بسم") == "بسم"
