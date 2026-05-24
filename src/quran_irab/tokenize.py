"""
Stage 1: HTML → flat event stream.

Walks `<div class='PageText'>` blocks in document order and emits Events:
  PageBoundary    — start of a new printed page
  TitleSection    — `<span data-type='title'>` (surah header or section header)
  AyahMarker      — `<span id='aya-N'>`
  ParagraphBreak  — `</p>` boundary (used to segment running text)
  TextChunk       — Arabic text content inside the current paragraph
  FootnoteRef     — superscript marker inside running text
  FootnoteText    — a footnote at the bottom of a page

Downstream consumers turn this into Ayah objects (see assemble.py).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from bs4 import BeautifulSoup, NavigableString, Tag

from .normalize import clean_display

_PAGE_NUM_RE = re.compile(r"\(\s*ص\s*:\s*(\d+)\s*\)")
_VOLUME_RE = re.compile(r"جـ\s*(\d+)")
_AYA_ID_RE = re.compile(r"aya-(\d+)")


# --- Event types -------------------------------------------------------------


@dataclass
class Event:
    pass


@dataclass
class PageBoundary(Event):
    volume: int
    page: int


@dataclass
class TitleSection(Event):
    text: str


@dataclass
class AyahMarker(Event):
    num: int


@dataclass
class ParagraphBreak(Event):
    pass


@dataclass
class TextChunk(Event):
    text: str


@dataclass
class FootnoteRef(Event):
    marker: str


@dataclass
class FootnoteText(Event):
    marker: str
    text: str
    page: int


# --- Tokenizer ---------------------------------------------------------------


def tokenize_file(path: Path) -> Iterator[Event]:
    """Yield events for one volume HTML file."""
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "lxml")

    for page_div in soup.find_all("div", class_="PageText"):
        yield from _tokenize_page(page_div)


def _tokenize_page(page_div: Tag) -> Iterator[Event]:
    head = page_div.find("div", class_="PageHead")
    volume, page = _parse_page_head(head) if head else (0, 0)
    yield PageBoundary(volume=volume, page=page)

    # Detach the head and any footnote divs so we don't re-emit them in the body walk
    footnote_divs: list[Tag] = list(page_div.find_all("div", class_="footnote"))
    skip: set[int] = set()
    if head:
        skip.add(id(head))
        for d in head.descendants:
            skip.add(id(d))
    for fn in footnote_divs:
        skip.add(id(fn))
        for d in fn.descendants:
            skip.add(id(d))

    yield from _walk(page_div, skip)

    # Footnotes after the body — assembler will attach to last FootnoteRef
    for fn in footnote_divs:
        yield from _tokenize_footnote_block(fn, page)


def _walk(node: Tag, skip: set[int]) -> Iterator[Event]:
    """In-order walk of a node's contents, emitting events."""
    for child in node.children:
        if id(child) in skip:
            continue
        if isinstance(child, NavigableString):
            text = clean_display(str(child))
            if text:
                yield TextChunk(text=text)
            continue
        assert isinstance(child, Tag)
        yield from _walk_tag(child, skip)


def _walk_tag(tag: Tag, skip: set[int]) -> Iterator[Event]:
    name = tag.name
    classes = tag.get("class") or []

    if name == "span":
        data_type = tag.get("data-type")
        sid = tag.get("id", "")
        if data_type == "title":
            text = clean_display(tag.get_text())
            if text:
                yield TitleSection(text=text)
            return
        m = _AYA_ID_RE.match(sid)
        if m:
            yield AyahMarker(num=int(m.group(1)))
            # span may also wrap text; continue into children
            yield from _walk(tag, skip)
            return

    if name == "p":
        yield ParagraphBreak()
        yield from _walk(tag, skip)
        return

    if name == "sup":
        marker = clean_display(tag.get_text())
        marker = marker.strip("()")
        if marker:
            yield FootnoteRef(marker=marker)
        return

    if name == "br" or name == "hr":
        yield ParagraphBreak()
        return

    if name in ("div",) and "footnote" in classes:
        return  # handled separately

    # Default: descend, treat tag transparently
    yield from _walk(tag, skip)


def _tokenize_footnote_block(fn_div: Tag, page: int) -> Iterator[Event]:
    """
    A footnote block looks like:
      <div class='footnote'>(1) text...</div>
    Or sometimes contains multiple `</p>`-separated footnotes.
    """
    raw_html = str(fn_div)
    # bs4 will have absorbed `</p>` — re-split on visible paragraph breaks
    text = clean_display(fn_div.get_text(separator="\n"))
    if not text:
        return
    # Split into (marker, body) pairs
    parts = re.split(r"\n?\s*\((\d+)\)\s*", text)
    # parts looks like ['', '1', 'body1', '2', 'body2', ...] when leading marker exists
    i = 1 if parts and parts[0].strip() == "" else 0
    if i == 0 and len(parts) >= 2:
        # No leading marker — yield orphaned text as fallback
        yield FootnoteText(marker="", text=parts[0].strip(), page=page)
        i = 1
    while i + 1 < len(parts):
        marker = parts[i].strip()
        body = parts[i + 1].strip()
        if body:
            yield FootnoteText(marker=marker, text=body, page=page)
        i += 2


def _parse_page_head(head: Tag) -> tuple[int, int]:
    text = head.get_text(separator=" ")
    vol_m = _VOLUME_RE.search(text)
    page_m = _PAGE_NUM_RE.search(text)
    return (
        int(vol_m.group(1)) if vol_m else 0,
        int(page_m.group(1)) if page_m else 0,
    )
