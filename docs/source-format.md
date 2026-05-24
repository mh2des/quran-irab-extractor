# Source HTML format

`الجدول في إعراب القرآن` HTML is unusually well-structured for OCR'd
classical Arabic — credit to whoever produced the Shamela edition. This
document captures the patterns the parser relies on, and the quirks
that took the most effort to handle.

## File layout

15 HTML files: `001.htm` through `015.htm`, each one volume of the
printed edition. Each file is ~1 MB, ~500–600 `<div class='PageText'>`
blocks, each block being one printed page.

## Anchor elements

### Page boundary

```html
<div class='PageText'>
  <div class='PageHead'>
    <span class='PartName'>الجدول في إعراب القرآن - جـ 1</span>
    <span class='PageNumber'>(ص: 27)</span>
    <hr/>
  </div>
  ... page body ...
  <div class='footnote'>(1) footnote text…</div>
</div>
```

### Section title

```html
<span data-type='title' id=toc-9>الإعراب:</span>
```

Four section types recur per ayah/group:

- `الإعراب:` → key `irab`
- `الصرف:` → key `sarf`
- `البلاغة` → key `balagha`
- `الفوائد` → key `fawaid`
- Less commonly: `المفردات اللغوية:` → key `mufradat`

The same `<span data-type='title'>` element is also used for surah names
(`سورة الفاتحة`), the book's introduction, and sub-headings inside
fawa'id sections (e.g. `البسملة:`). The parser distinguishes them via
the title text:

- Starts with `سورة ` → new surah
- Matches one of the four section keys → section start
- Otherwise → sub-heading inside current section (rendered as
  `### text` in the output)

### Ayah marker

```html
<span id="aya-1902">​</span>
{أَتى أَمْرُ اللهِ فَلا تَسْتَعْجِلُوهُ ... (1)}
```

The `aya-N` ID is a sequential counter within the volume — **not the
canonical surah:ayah number**. The reliable canonical ayah number is
the `(N)` at the END of the curly-braced text.

### Multi-ayah braced block

When several consecutive ayat share one i'rab block, the source uses a
sequence of empty `<span id="aya-N">` markers followed by ONE braced
block containing all ayat with their internal `(N)` markers:

```html
<span id="aya-1905"></span>
<span id="aya-1906"></span>
<span id="aya-1907"></span>
<span id="aya-1908"></span>
<span id="aya-1909"></span>
{خَلَقَ الْإِنْسانَ مِنْ نُطْفَةٍ ... (4)
 وَالْأَنْعامَ خَلَقَها لَكُمْ ... (5)
 لَكُمْ فِيها جَمالٌ ... (6) ...}
```

The parser handles this by:

1. Queuing all consecutive `AyahMarker` events without committing them
2. When the braced block arrives, splitting its inner content on `(N)`
   boundaries
3. Committing each split section as a separate ayah, all attached to
   the same group

This was the single biggest extraction bug — until handled, we were
losing ~3000 ayat.

### Footnote reference

```html
... وعلامة الجر الكسرة<sup><font color=#be0000>(1)</font></sup> (الرحمن) نعت ...
```

Footnote text appears at the bottom of the page in `<div class='footnote'>`.
The parser collects footnotes by `(volume, page, marker)` and attaches
them to whatever group is current on that page.

## Quirks handled

### Trailing punctuation inside braces

```html
<span id="aya-294"></span>{الم (1)،}
```

The `،` (Arabic comma) AFTER the `(1)` is purely visual punctuation —
not a new ayah. Early versions of the parser treated it as a phantom
ayah 2 with text `،`.

**Fix**: only count text segments that are FOLLOWED by a `(N)` as ayat;
trailing fragments are dropped.

### Letter-less text fragments

Punctuation-only fragments (e.g. `،`, `;`, whitespace) are filtered out
in `_has_arabic_letters` before being treated as ayat.

### Missing surah headers

Volume 8 starts mid-surah with Al-Isra but has no `سورة الإسراء` title
at the top — the source assumes you know which surah you're in. The
parser detects new surahs via canonical `(1)` instead: when an ayah's
trailing number is 1 AND the current surah already has at least one
ayah, that's a new-surah transition.

### Muqatta'at gaps

Some short surahs (e.g. Ash-Shu'ara, Al-Ahqaf) open with disconnected
letters (طسم, حم) that the author discusses only in the fawa'id section
WITHOUT a separate `aya-N` marker. These create gaps where the canonical
ayat 1 (and sometimes 2) are absent from the extraction.

**Fix**: the validator backfills these from Tanzil canonical text,
producing groups with `is_backfilled=1` and no i'rab sections.

### Per-ayah subheadings inside multi-ayah blocks

Within an i'rab block covering ayat 4–6, the source uses inline
`(5)`, `(6)` markers to delimit which ayah each sub-block addresses:

```
(الإعراب for ayah 4 ...)
(5)
(الإعراب for ayah 5 ...)
(6)
(الإعراب for ayah 6 ...)
```

These are not currently split — the whole i'rab block stays attached
to the group. Splitting them is a polish item (see CONTRIBUTING.md).

### `</p>` without `<p>`

The source uses bare `</p>` tags as paragraph delimiters without
opening tags. BeautifulSoup auto-fixes this; the parser then treats
`<p>` open events as `ParagraphBreak` events.

### Inline references to other ayat

The source often quotes other ayat for cross-reference, using `{...}`
braces just like ayah text. These appear INSIDE section content, not
after an `AyahMarker`, so they don't trigger ayah commits — the
state machine only treats `{...}` as ayah text when a pending marker
is set.

## What the parser does NOT do

- It doesn't extract per-volume tables of contents (which exist in the source).
- It doesn't preserve the original font colors, sizes, or HTML structure.
- It doesn't track which qira'a (reading) is referenced — الجدول uses
  only Hafs throughout.
- It doesn't deduplicate cross-references ("see the analysis of word X
  in surah Y, ayah Z" remains as natural-language text).
