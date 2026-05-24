"""
Stage 2: events → Ayah objects.

The HTML is structured per-page; each ayah (or group of consecutive ayat sharing one
i'rab block) is followed by section titles (الإعراب / الصرف / البلاغة / الفوائد).

Grouping rule: consecutive AyahMarkers with NO section title between them form one
group. A SECTION title opens a section attached to the group. A subsequent
AyahMarker after any section content closes the group and starts a new one.

Word-level analysis is extracted from الإعراب sections by matching the
`(word) analysis` pattern that الجدول uses consistently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from .normalize import clean_display, normalize_ar
from .surahs import CANONICAL_AYAH_COUNTS, CANONICAL_NAMES
from .tokenize import (
    AyahMarker,
    Event,
    FootnoteRef,
    FootnoteText,
    PageBoundary,
    ParagraphBreak,
    TextChunk,
    TitleSection,
)

# Canonical section names → stable keys
SECTION_KEYS = {
    "الإعراب": "irab",
    "الإعراب:": "irab",
    "الصرف": "sarf",
    "الصرف:": "sarf",
    "البلاغة": "balagha",
    "البلاغة:": "balagha",
    "الفوائد": "fawaid",
    "الفوائد:": "fawaid",
    "المفردات اللغوية": "mufradat",
    "المفردات اللغوية:": "mufradat",
}

_SURAH_TITLE_RE = re.compile(r"^\s*سورة\s+")
_AYAH_TEXT_RE = re.compile(r"\{(.*?)\}", re.DOTALL)
# Capture trailing (N) — the canonical ayah number within its surah
_AYAH_NUM_AT_END_RE = re.compile(r"\s*\(\s*(\d+)\s*\)\s*$")
# Split a multi-ayah braced block on (N) boundaries — each ayah's text ends with (N)
_AYAH_SPLIT_RE = re.compile(r"\s*\(\s*(\d+)\s*\)\s*")
_WORD_ANALYSIS_RE = re.compile(
    r"\(([^()\n]{1,60}?)\)\s+([^(]+?)(?=\([^()]{1,60}\)\s+|$)",
    re.DOTALL,
)
_ARABIC_LETTERS_RE = re.compile(r"[ا-يآ-غ]")


def _has_arabic_letters(text: str) -> bool:
    """True if the string contains at least one Arabic letter (filters punctuation-only)."""
    return bool(_ARABIC_LETTERS_RE.search(text))


# --- Output dataclasses ------------------------------------------------------


@dataclass
class WordAnalysis:
    position: int
    token: str
    analysis: str


@dataclass
class IrabSection:
    key: str  # 'irab' | 'sarf' | 'balagha' | 'fawaid' | 'mufradat'
    content: str  # rich text with [N] footnote markers and ### subheadings
    words: list[WordAnalysis] = field(default_factory=list)


@dataclass
class Footnote:
    marker: str
    text: str


@dataclass
class AyahGroup:
    surah: int
    surah_name: str
    ayah_start: int
    ayah_end: int
    ayat: list[tuple[int, str]]  # (ayah_num, ayah_text)
    sections: dict[str, IrabSection] = field(default_factory=dict)
    footnotes: list[Footnote] = field(default_factory=list)
    source_pages: list[tuple[int, int]] = field(default_factory=list)  # (volume, page)

    def to_dict(self) -> dict:
        return {
            "surah": self.surah,
            "surah_name": self.surah_name,
            "ayah_start": self.ayah_start,
            "ayah_end": self.ayah_end,
            "ayat": [
                {
                    "num": n,
                    "text": t,
                    "text_normalized": normalize_ar(t),
                }
                for n, t in self.ayat
            ],
            "sections": {
                k: {
                    "content": s.content,
                    "content_normalized": normalize_ar(s.content),
                    "words": [
                        {"position": w.position, "token": w.token, "analysis": w.analysis}
                        for w in s.words
                    ],
                }
                for k, s in self.sections.items()
            },
            "footnotes": [{"marker": f.marker, "text": f.text} for f in self.footnotes],
            "source_pages": [{"volume": v, "page": p} for v, p in self.source_pages],
        }


# --- Assembler ---------------------------------------------------------------


class Assembler:
    def __init__(self, starting_surah: int = 1):
        self._next_surah_id = starting_surah
        self._surah: int | None = None
        self._surah_name: str = ""
        self._last_canonical_in_surah: int = 0
        self._group: AyahGroup | None = None
        self._section_key: str | None = None
        self._section_buf: list[str] = []
        # Queue of AyahMarkers that fired; drained when their {text} arrives.
        # Multiple markers can stack when consecutive ayat share one i'rab block,
        # in which case the source bundles them as `{text_K (K) text_K+1 (K+1) ...}`.
        self._pending_marker_ids: list[int] = []
        self._current_volume: int = 0
        self._current_page: int = 0
        self._pending_footnote_refs: list[str] = []
        # (volume, page, marker) → text — keyed by volume so cross-volume pages don't collide
        self._footnote_pool: dict[tuple[int, int, str], str] = {}
        self._groups: list[AyahGroup] = []
        # Warnings collected during assembly for the stats command
        self.warnings: list[str] = []

    # --- public API ---

    def consume(self, events: Iterable[Event]) -> list[AyahGroup]:
        for ev in events:
            self._dispatch(ev)
        self._finish_group()
        self._resolve_footnotes()
        return self._groups

    # --- event dispatch ---

    def _dispatch(self, ev: Event) -> None:
        if isinstance(ev, PageBoundary):
            self._current_volume = ev.volume
            self._current_page = ev.page
            return

        if isinstance(ev, TitleSection):
            self._on_title(ev.text)
            return

        if isinstance(ev, AyahMarker):
            self._on_ayah_marker(ev.num)
            return

        if isinstance(ev, TextChunk):
            self._on_text(ev.text)
            return

        if isinstance(ev, ParagraphBreak):
            if self._group is not None and self._section_key is not None and self._section_buf:
                if not self._section_buf[-1].endswith("\n"):
                    self._section_buf.append("\n\n")
            return

        if isinstance(ev, FootnoteRef):
            if self._group is not None and self._section_key is not None:
                self._section_buf.append(f"[{ev.marker}]")
            if self._group is not None:
                self._pending_footnote_refs.append(ev.marker)
            return

        if isinstance(ev, FootnoteText):
            self._footnote_pool[(self._current_volume, ev.page, ev.marker)] = ev.text
            return

    # --- handlers ---

    def _on_title(self, raw_text: str) -> None:
        text = clean_display(raw_text).rstrip(":").strip()
        if _SURAH_TITLE_RE.match(raw_text):
            self._finish_group()
            name = _SURAH_TITLE_RE.sub("", raw_text).strip().rstrip(":").strip()
            self._advance_surah(explicit_name=name)
            return

        canonical = SECTION_KEYS.get(text) or SECTION_KEYS.get(text + ":")
        if canonical and self._group is not None:
            self._close_section()
            self._section_key = canonical
            self._section_buf = []
            return

        # Sub-heading inside a section (e.g. "البسملة:") — embed as subheading
        if self._group is not None and self._section_key is not None:
            self._section_buf.append(f"\n### {text}\n")

    def _on_ayah_marker(self, num: int) -> None:
        # Defer: only commit once we see the ayah text (with canonical (N)).
        self._pending_marker_ids.append(num)

    def _on_text(self, text: str) -> None:
        if not text or text.isspace():
            return

        if self._pending_marker_ids:
            m = _AYAH_TEXT_RE.search(text)
            if m:
                self._commit_pending_block(m.group(1).strip())
                rest = text[m.end():].strip()
                if rest:
                    self._append_to_section(rest)
                return
            # Wait — the ayah text hasn't arrived yet (whitespace, etc.)
            return

        self._append_to_section(text)

    def _commit_pending_block(self, raw_inner: str) -> None:
        """
        Parse a `{...}` block that may contain one OR multiple ayat.
        Format examples:
          single:   "بسم الله الرحمن الرحيم (1)"
          multiple: "خلق الإنسان من نطفة ... (4) والأنعام خلقها لكم ... (5) ..."
          trailing punctuation: "الم (1)،"  — comma after the (N) is NOT a new ayah
        Splits on `(N)` boundaries and commits each ayah in order. Anything
        after the LAST (N) is trailing noise — not a new ayah.
        """
        parts = _AYAH_SPLIT_RE.split(raw_inner)
        # parts is alternating [text, num, text, num, ...]; may start with empty text.
        # Note: only `text` segments IMMEDIATELY FOLLOWED by a num count as ayah text.
        # A trailing text segment with no following num is punctuation/noise.
        ayat: list[tuple[int, str]] = []
        i = 0
        while i + 1 < len(parts):
            text_part = parts[i].strip()
            num = int(parts[i + 1])
            if _has_arabic_letters(text_part):
                ayat.append((num, text_part))
            i += 2

        if not ayat:
            self._pending_marker_ids.clear()
            return

        for canonical_n, ayah_text in ayat:
            self._commit_single_ayah(canonical_n, ayah_text)
        # Clear pending markers — extras are typically empty-span artifacts where
        # multiple consecutive `<span id="aya-N">` markers point to the same braced block.
        self._pending_marker_ids.clear()

    def _commit_single_ayah(self, canonical_n: int | None, ayah_text: str) -> None:
        # Detect new surah: canonical (N) == 1 AND we already have ayat in current surah
        if (
            canonical_n == 1
            and self._surah is not None
            and self._last_canonical_in_surah > 0
        ):
            self._finish_group()
            self._advance_surah()

        # First ayah ever — start surah 1 if not already
        if self._surah is None:
            self._advance_surah()

        # If the current group already has a started section, this ayah opens a new group
        if self._group is not None and self._section_key is not None:
            self._finish_group()

        if self._group is None:
            self._group = AyahGroup(
                surah=self._surah,
                surah_name=self._surah_name,
                ayah_start=canonical_n or 0,
                ayah_end=canonical_n or 0,
                ayat=[],
                source_pages=[(self._current_volume, self._current_page)]
                              if self._current_page else [],
            )

        if canonical_n is None:
            canonical_n = (self._last_canonical_in_surah or 0) + 1
            self.warnings.append(
                f"surah {self._surah} ayah {canonical_n}: missing (N) — inferred from sequence "
                f"(vol={self._current_volume}, page={self._current_page})"
            )

        if canonical_n != self._last_canonical_in_surah + 1 and canonical_n != 1:
            self.warnings.append(
                f"surah {self._surah}: ayah jumped {self._last_canonical_in_surah} -> {canonical_n}"
            )

        self._group.ayat.append((canonical_n, ayah_text))
        self._group.ayah_end = canonical_n
        if self._group.ayah_start == 0:
            self._group.ayah_start = canonical_n
        self._last_canonical_in_surah = canonical_n

        cur = (self._current_volume, self._current_page)
        if self._current_page and cur not in self._group.source_pages:
            self._group.source_pages.append(cur)

    def _advance_surah(self, explicit_name: str | None = None) -> None:
        """Assign the next surah ID; use canonical name unless source provided one."""
        sid = self._next_surah_id
        self._surah = sid
        self._next_surah_id += 1
        self._surah_name = explicit_name or CANONICAL_NAMES.get(sid, f"سورة {sid}")
        self._last_canonical_in_surah = 0

    def _append_to_section(self, text: str) -> None:
        if self._group is None or self._section_key is None:
            return
        self._section_buf.append(text)

    # --- lifecycle ---

    def _close_section(self) -> None:
        if self._group is None or self._section_key is None:
            return
        content = _join_section(self._section_buf)
        if content:
            section = IrabSection(key=self._section_key, content=content)
            if self._section_key == "irab":
                section.words = _extract_words(content)
            self._group.sections[self._section_key] = section
        self._section_key = None
        self._section_buf = []

    def _finish_group(self) -> None:
        if self._group is None:
            return
        self._close_section()
        # Drop groups with no content (e.g. orphan markers in intros)
        if self._group.ayat and any(t for _, t in self._group.ayat):
            self._groups.append(self._group)
        self._group = None

    def _resolve_footnotes(self) -> None:
        # Best-effort: walk groups, attach footnotes by (volume, page) + marker.
        for group in self._groups:
            seen: set[tuple[int, int, str]] = set()
            for vol_page in group.source_pages:
                vol, pg = vol_page
                for (fvol, fpg, marker), text in self._footnote_pool.items():
                    if (fvol, fpg) == (vol, pg) and (fvol, fpg, marker) not in seen:
                        group.footnotes.append(Footnote(marker=marker, text=text))
                        seen.add((fvol, fpg, marker))


def _join_section(parts: list[str]) -> str:
    if not parts:
        return ""
    joined = "".join(parts)
    # Collapse runs of blank lines to at most one
    joined = re.sub(r"\n{3,}", "\n\n", joined)
    return joined.strip()


def _extract_words(irab_content: str) -> list[WordAnalysis]:
    """
    Extract (word) analysis pairs from an i'rab block.
    The first parenthesized item at the start of each analysis sentence is the
    word being parsed; what follows up to the next (word) is its analysis.
    """
    words: list[WordAnalysis] = []
    position = 0
    # Drop footnote-marker spans like [1], [2] so they don't confuse the regex
    cleaned = re.sub(r"\[\d+\]", " ", irab_content)
    for m in _WORD_ANALYSIS_RE.finditer(cleaned):
        token = clean_display(m.group(1))
        analysis = clean_display(m.group(2))
        if not analysis or len(token) > 60:
            continue
        words.append(WordAnalysis(position=position, token=token, analysis=analysis))
        position += 1
    return words
