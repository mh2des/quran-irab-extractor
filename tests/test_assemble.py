"""Golden tests for the assembler on Surah Al-Fatiha.

These tests exercise the whole pipeline on a known surah whose structure
is hand-verified. They guard against regressions in:
  - section detection (الإعراب / الصرف / البلاغة / الفوائد)
  - canonical ayah numbering via trailing (N) extraction
  - word-level analysis extraction
  - sub-heading preservation inside sections
"""

import pytest

from quran_irab.assemble import Assembler
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
