"""Golden tests for the assembler on Surah Al-Fatiha and the word-level filter.

These tests exercise the whole pipeline on a known surah whose structure
is hand-verified. They guard against regressions in:
  - section detection (الإعراب / الصرف / البلاغة / الفوائد)
  - canonical ayah numbering via trailing (N) extraction
  - word-level analysis extraction
  - sub-heading preservation inside sections
"""

import pytest

from quran_irab.assemble import (
    Assembler,
    _extract_words,
    _is_likely_word_token,
    split_irab_by_ayah,
)
from quran_irab.tokenize import (
    AyahMarker,
    PageBoundary,
    ParagraphBreak,
    TextChunk,
    TitleSection,
)


def make_fatiha_events():
    """Synthetic event stream for a minimal Al-Fatiha extraction."""
    return [
        PageBoundary(volume=1, page=27),
        TitleSection(text="سورة الفاتحة"),
        AyahMarker(num=1),
        TextChunk(text="{بِسْمِ اللهِ الرَّحْمنِ الرَّحِيمِ (1)}"),
        ParagraphBreak(),
        TitleSection(text="الإعراب:"),
        TextChunk(text="(بسم) جار ومجرور متعلق بمحذوف خبر. (الله) لفظ الجلالة مضاف إليه."),
        ParagraphBreak(),
        TitleSection(text="الصرف:"),
        TextChunk(text="(اسم) فيه إبدال، أصله سمو."),
        ParagraphBreak(),
        AyahMarker(num=2),
        TextChunk(text="{الْحَمْدُ لِلّهِ رَبِّ الْعالَمِينَ (2)}"),
        TitleSection(text="الإعراب:"),
        TextChunk(text="(الحمد) مبتدأ مرفوع. (لله) جار ومجرور."),
    ]


class TestAlFatihaAssembly:
    @pytest.fixture
    def groups(self):
        asm = Assembler()
        return asm.consume(make_fatiha_events())

    def test_two_groups_produced(self, groups):
        assert len(groups) == 2

    def test_surah_metadata(self, groups):
        for g in groups:
            assert g.surah == 1
            assert g.surah_name == "الفاتحة"

    def test_canonical_ayah_numbers(self, groups):
        assert [(a[0]) for a in groups[0].ayat] == [1]
        assert [(a[0]) for a in groups[1].ayat] == [2]

    def test_ayah_text_stripped_of_trailing_marker(self, groups):
        assert groups[0].ayat[0][1] == "بِسْمِ اللهِ الرَّحْمنِ الرَّحِيمِ"
        assert "(1)" not in groups[0].ayat[0][1]

    def test_irab_section_attached(self, groups):
        assert "irab" in groups[0].sections
        assert "جار ومجرور" in groups[0].sections["irab"].content

    def test_sarf_section_attached(self, groups):
        assert "sarf" in groups[0].sections
        assert "إبدال" in groups[0].sections["sarf"].content

    def test_word_level_analyses_extracted(self, groups):
        words = groups[0].sections["irab"].words
        assert len(words) >= 2
        assert words[0].token == "بسم"
        assert "جار ومجرور" in words[0].analysis


class TestMultiAyahBlock:
    """Source pattern: multiple aya-N markers, then ONE braced block with
    inline (N) per ayah. This was the biggest extraction bug — guard it."""

    def test_three_ayat_in_one_braced_block(self):
        events = [
            PageBoundary(volume=10, page=53),
            TitleSection(text="سورة الشعراء"),
            AyahMarker(num=2936),
            AyahMarker(num=2937),
            AyahMarker(num=2938),
            TextChunk(text=(
                "{إن نشأ ننزل عليهم من السماء آية فظلت أعناقهم لها خاضعين (4) "
                "وما يأتيهم من ذكر من الرحمن محدث (5) "
                "فقد كذبوا فسيأتيهم أنباؤا ما كانوا به يستهزؤون (6)}"
            )),
            TitleSection(text="الإعراب:"),
            TextChunk(text="(إن) حرف شرط (نشأ) فعل مضارع."),
        ]
        groups = Assembler().consume(events)
        assert len(groups) == 1
        assert [n for n, _ in groups[0].ayat] == [4, 5, 6]


class TestTrailingPunctuationNotAyah:
    """Guard against the bug where `{الم (1)،}` was emitting a phantom ayah 2."""

    def test_trailing_comma_does_not_create_ayah(self):
        events = [
            PageBoundary(volume=2, page=105),
            TitleSection(text="سورة آل عمران"),
            AyahMarker(num=294),
            TextChunk(text="{الم (1)،}"),
        ]
        groups = Assembler().consume(events)
        assert len(groups) == 1
        assert [n for n, _ in groups[0].ayat] == [1]


class TestSurahTransitionByCanonicalOne:
    """When `(1)` arrives and the previous surah already has ayat, that's a
    new-surah signal — even if the source has no `سورة X` title at the boundary."""

    def test_implicit_new_surah_on_canonical_one(self):
        events = [
            PageBoundary(volume=7, page=279),
            TitleSection(text="سورة النحل"),
            AyahMarker(num=1),
            TextChunk(text="{أَتَى أَمْرُ اللَّهِ فَلا تَسْتَعْجِلُوهُ (1)}"),
            TitleSection(text="الإعراب"),
            TextChunk(text="(أتى) فعل ماض."),
            # Pretend the next page is the start of Al-Isra but with NO surah title:
            PageBoundary(volume=8, page=5),
            AyahMarker(num=2030),
            TextChunk(text="{سُبْحَانَ الَّذِي أَسْرَى بِعَبْدِهِ لَيْلًا (1)}"),
        ]
        groups = Assembler().consume(events)
        # Two groups, with explicit surah ID assignment from starting_surah=1
        assert len(groups) == 2
        # Group 1 attached to the "سورة النحل" title (assembler's first advance → surah 1)
        assert groups[0].surah == 1
        assert groups[0].surah_name == "النحل"
        assert groups[0].ayat[0][0] == 1
        # Group 2 triggered by canonical (1) WITHOUT a سورة title — implicit advance
        assert groups[1].surah == 2
        assert groups[1].ayat[0][0] == 1


class TestWordLevelExtraction:
    """Polish item: the `(word) analysis` regex used to over-capture cross-
    references like `(انظر الآية 5)` and emit the same word multiple times
    when it appeared inside another word's analysis. Guard the fixes."""

    def test_rejects_cross_reference_tokens(self):
        assert not _is_likely_word_token("انظر الآية 5")
        assert not _is_likely_word_token("راجع الفائدة 3")
        assert not _is_likely_word_token("من سورة البقرة")
        assert not _is_likely_word_token("الآية 12")

    def test_rejects_pure_numeric_tokens(self):
        assert not _is_likely_word_token("1")
        assert not _is_likely_word_token("  15  ")

    def test_rejects_tiny_or_letterless_tokens(self):
        assert not _is_likely_word_token("ا")          # single letter
        assert not _is_likely_word_token("...")         # punctuation
        assert not _is_likely_word_token("")            # empty

    def test_accepts_real_word_tokens(self):
        assert _is_likely_word_token("بسم")
        assert _is_likely_word_token("الله")
        assert _is_likely_word_token("يؤمنون")
        assert _is_likely_word_token("إيّاك")
        # Short multi-word phrases ARE sometimes the parsed unit
        assert _is_likely_word_token("لا الناهية")

    def test_drops_consecutive_duplicate_tokens_only(self):
        # A consecutive duplicate is an artifact and is dropped; a NON-consecutive
        # repeat (legit re-parse within one ayah) is now KEPT, because inputs are
        # per-ayah segments where cross-ayah repetition no longer occurs.
        text = "(بسم) جار ومجرور (بسم) تكرار فوري (الله) لفظ الجلالة (بسم) إشارة لاحقة"
        tokens = [w.token for w in _extract_words(text)]
        assert tokens == ["بسم", "الله", "بسم"]

    def test_extracts_comma_attached_first_word(self):
        # "(أولاء)،اسم إشارة" — comma right after the paren, NO space. The old
        # regex required \s+ and silently dropped أولاء (the verse's first word).
        text = "(أولاء)،اسم إشارة مبني (الكاف) حرف خطاب"
        tokens = [w.token for w in _extract_words(text)]
        assert tokens == ["أولاء", "الكاف"]

    def test_strips_inline_per_ayah_subheadings(self):
        # In multi-ayah groups, الجدول inserts a bare "(5)" or "5 -" to mark the
        # start of an ayah's i'rab. Those must never be captured as words.
        text = "(إن) حرف شرط (5) (وما) عاطفة 6 - (الفاء) رابطة"
        tokens = [w.token for w in _extract_words(text)]
        assert tokens == ["إن", "وما", "الفاء"]


class TestSplitIrabByAyah:
    """The core fix for 'wrong i'rab for wrong ayah': a multi-ayah block is
    split into per-ayah segments using the source's N - / (N) markers."""

    def test_single_ayah_returns_whole(self):
        assert split_irab_by_ayah("(بسم) جار", 1, 1) == {1: "(بسم) جار"}

    def test_dash_markers(self):
        content = "(أ) ايه11 12 -(ب) ايه12 13 -(ج) ايه13"
        seg = split_irab_by_ayah(content, 11, 13)
        assert seg == {11: "(أ) ايه11", 12: "(ب) ايه12", 13: "(ج) ايه13"}

    def test_parenthesised_markers(self):
        content = "(أ) ايه4 (5)(ب) ايه5 (6)(ج) ايه6"
        seg = split_irab_by_ayah(content, 4, 6)
        assert seg == {4: "(أ) ايه4", 5: "(ب) ايه5", 6: "(ج) ايه6"}

    def test_shared_adjacent_markers(self):
        # "14 -15 -" means ayat 14 and 15 share the following text
        content = "(أ) ايه13بداية 14 -15 - (ب) مشترك 16 -(ج) ايه16"
        seg = split_irab_by_ayah(content, 13, 16)
        assert seg[14] == seg[15] == "(ب) مشترك"
        assert seg[13] == "(أ) ايه13بداية"
        assert seg[16] == "(ج) ايه16"

    def test_no_markers_returns_none(self):
        # Genuinely merged block — caller shares it across the group.
        assert split_irab_by_ayah("(أ) كلام بلا علامات", 3, 4) is None

    def test_ignores_out_of_range_and_non_monotonic(self):
        # "1 -" enumeration (out of group range) and a backwards number must not
        # trigger a false split.
        content = "(أ) نص 1 - تعداد ليس علامة آية"
        assert split_irab_by_ayah(content, 11, 16) is None
