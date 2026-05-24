# Arabic normalization

The hardest single problem in an Arabic search system is matching what
the user types against what's stored. Arabic has multiple valid script
conventions, optional diacritics, and several letters that swap
positions or shapes depending on tradition.

This project ships two normalizers in
[`src/quran_irab/normalize.py`](../src/quran_irab/normalize.py):

| Function | Use for |
|---|---|
| `normalize_ar(text)` | FTS5 indexing AND matching user search input |
| `loose_match_normalize(text)` | Cross-tradition validation only — too lossy for indexing |

## What `normalize_ar` does

In order:

1. **Strip zero-width characters** — ZWNJ, BOM, bidi marks. These are
   invisible but break exact matching.
2. **Dagger alif → full alif** — `ٰ` (U+0670) represents an unwritten
   alif in Uthmani script. Converting it to `ا` first lets Hafs and
   Uthmani forms of words like `العالمين` / `العَٰلَمِينَ` match.
3. **Strip tashkeel + tatweel + Quranic annotation marks** — all
   diacritics (fatha, kasra, damma, sukun, shadda, fathatan, etc.),
   tatweel `ـ`, and Quranic pause/sajda marks (`ۖ`, `ۗ`, `ۚ`, etc.).
4. **Normalize alif variants**: `أإآٱ → ا`.
5. **Normalize ya/hamza bearers**: `ى → ي`, `ئ → ء`.
6. **Normalize ta marbuta**: `ة → ه` (matters because users often type
   the visually similar `ه`).
7. **Strip quote characters**: `{}«»"`.
8. **Collapse whitespace**.

### Example transformations

| Input | Output |
|---|---|
| `بِسْمِ اللهِ الرَّحْمنِ الرَّحِيمِ` | `بسم الله الرحمن الرحيم` |
| `العَٰلَمِينَ` (Uthmani) | `العالمين` |
| `مالِكِ يَوْمِ الدِّينِ` | `مالك يوم الدين` |
| `صلاة` | `صلاه` |

### What it does NOT do

- It doesn't drop standalone hamza (`ء`) — `شيء` stays as `شيء`.
- It doesn't drop the alif inserted by step 2 — that's the point.
- It doesn't collapse emphatic-letter variants (`ص` stays `ص`).

For those, use `loose_match_normalize`.

## What `loose_match_normalize` does

Builds on `normalize_ar`, then adds:

1. **Drop hamza bearers**: `ؤ → و`, `ئ → ي`. Some Quran traditions
   write `يؤمنون`, others `يءومنون`.
2. **Drop standalone hamza `ء`** entirely.
3. **Drop all alif `ا`** entirely. This collapses the dagger-alif
   ambiguity even further — useful when one tradition writes an alif
   that another omits with no dagger.
4. **Collapse emphatic-letter pairs**: `ص↔س`, `ض↔د`, `ط↔ت`, `ظ↔ذ`.
5. **Strip ALL whitespace** — handles word-boundary disagreements like
   `بعدما` vs `بعد ما`.

This normalizer is **lossy enough that distinct words can collapse to
the same form** — that's by design. It's used ONLY in
`validate.py` to confirm "yes, this is the same ayah" when comparing
cross-tradition spellings. Never use it for search input.

## Why two normalizers?

The product use case (FTS5 search) and the validation use case
(cross-tradition matching) have opposite needs:

- **Search** must preserve enough information that distinct words don't
  collide. A user searching `النور` shouldn't get hits for `النار`.
  `normalize_ar` keeps emphatic letters and alifs.
- **Validation** can be very loose because the question is "are these
  two strings the same ayah?" given that the surah:ayah index already
  narrows the candidate space to one. `loose_match_normalize` accepts
  any script tradition.

Mixing the two would either break search (false-positive matches) or
break validation (98%+ false-negative mismatches due to harmless
spelling variation).

## Cross-tradition mismatch patterns (76 remaining)

After both normalizers, 76 ayat still don't match. They fall into
these categories, all of them benign:

| Pattern | Count | Example |
|---|---|---|
| `يي` vs `ي` at end of word | ~10 | `يحيي` vs `يحي` |
| `ا` vs `و` (Dawud variants) | ~5 | `داوود` vs `داود` |
| `ا` vs `ء` mid-word | ~10 | `تسءلون` vs `تسالون` |
| Word-segmentation that survives loose-match | ~5 | edge cases |
| Other minor spelling preferences | rest | |

These are all valid Quranic Arabic — they reflect choices made by
different scholarly editions of the printed Mushaf. The الجدول text
is correct; the Tanzil text is correct; they just differ.
