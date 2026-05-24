# quran-irab-extractor

> A reproducible pipeline that turns **الجدول في إعراب القرآن** (the 15-volume
> grammatical analysis of the entire Qur'an by Sheikh Mahmud Safi) into a
> searchable SQLite + FTS5 database covering all 6,236 ayat — including
> i'rab (إعراب), sarf (صرف), balagha (بلاغة), and fawa'id (فوائد).

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![Coverage: 100%](https://img.shields.io/badge/canonical_ayat-6236%2F6236-success.svg)](#coverage)

## Why

There is a huge gap between the published scholarship on Qur'anic Arabic
grammar and what's actually queryable on a phone. الجدول في إعراب القرآن
is one of the most comprehensive grammatical commentaries on the Qur'an,
but it exists only as a 15-volume printed book (and a few HTML scans).

This project makes it **searchable, programmable, and embeddable**:

- Tap any ayah → see its full grammatical breakdown.
- Type a partial phrase → find the ayah instantly.
- Search inside the i'rab itself ("show me every ayah whose i'rab mentions مفعول مطلق").
- Build word-by-word grammar lessons, flashcards, exam prep, or anything else.

Built originally for [irabapp](https://irab.app), released as a standalone
tool so other developers can build their own Arabic-grammar products on
top of it.

## What you get

A 36 MB SQLite database (6.7 MB compressed with zstd) containing:

| | Count |
|---|---|
| Quranic ayat | **6,236** (100% canonical coverage) |
| Ayah groups (i'rab blocks) | 3,263 |
| I'rab section entries | 3,230 |
| Sarf section entries | 1,859 |
| Balagha section entries | 971 |
| Fawa'id section entries | 983 |
| Word-level analyses | **64,067** |
| Footnotes | 4,580 |
| **FTS5 search latency** | **0.03–0.30 ms per query** |

## Quickstart

```bash
# 1. Clone and install
git clone https://github.com/mansoorshakla/quran-irab-extractor.git
cd quran-irab-extractor
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 2. Place your copy of الجدول HTML in sources/ (see "Sourcing the input")
mkdir -p sources/الجدول
cp /path/to/your/aljadwal/*.htm sources/الجدول/

# 3. Run the pipeline
quran-irab batch sources/الجدول --out out/full.jsonl              # ~3s
quran-irab validate out/full.jsonl --out out/validated.jsonl       # ~2s
quran-irab build-db out/validated.jsonl --out out/irab.sqlite      # ~5s
```

That's it. You now have a queryable database.

## Sample queries

```python
import sqlite3
from quran_irab.normalize import normalize_ar

conn = sqlite3.connect("out/irab.sqlite")

# Find an ayah by partial phrase
q = normalize_ar("الحمد لله رب")
rows = conn.execute("""
    SELECT a.surah, a.ayah, a.text
    FROM ayat_fts f JOIN ayat a ON a.id = f.rowid
    WHERE ayat_fts MATCH ?
    ORDER BY rank LIMIT 5
""", (f'"{q}"',)).fetchall()

# Search inside i'rab itself
q = normalize_ar("مفعول مطلق")
rows = conn.execute("""
    SELECT g.surah, g.ayah_start, ie.section, SUBSTR(ie.content, 1, 100)
    FROM irab_fts f JOIN irab_entries ie ON ie.id = f.rowid
    JOIN ayah_groups g ON g.id = ie.group_id
    WHERE irab_fts MATCH ?
    ORDER BY rank LIMIT 10
""", (f'"{q}"',)).fetchall()

# Get word-by-word for ayah 1:1
rows = conn.execute("""
    SELECT w.position, w.token, w.analysis
    FROM ayat a JOIN ayah_words w ON w.group_id = a.group_id
    WHERE a.surah = 1 AND a.ayah = 1
    ORDER BY w.position
""").fetchall()
```

## Architecture

The pipeline is a clean five-stage process, each stage producing a stable
intermediate artifact you can inspect:

```
الجدول HTML (15 files, ~20 MB)
        │
        │ tokenize.py   — flat event stream (PageBoundary, AyahMarker,
        │                 TitleSection, TextChunk, ParagraphBreak,
        │                 FootnoteRef, FootnoteText)
        ▼
[Events]
        │
        │ assemble.py   — state machine that builds AyahGroup objects.
        │                 Handles multi-ayah blocks, cross-volume surah
        │                 transitions via canonical (N) detection,
        │                 word-level extraction from (word) analysis.
        ▼
JSONL (~28 MB)         ◄── inspectable / diffable / version-controllable
        │
        │ validate.py   — compares every ayah against Tanzil canonical
        │                 (loose match handles Hafs Ottoman vs Tanzil
        │                 script variants). Backfills any missing ayat
        │                 with canonical text (muqatta'at gaps).
        ▼
JSONL (6,236 ayat — 100% canonical coverage)
        │
        │ db.py         — SQLite schema + FTS5 indexes
        ▼
irab.sqlite (~36 MB)
        │
        │ zstd -19
        ▼
irab.sqlite.zst (~6.7 MB) ◄── deliverable to mobile apps
```

## Database schema

See [docs/schema.md](docs/schema.md) for full details. Quick summary:

- `surahs` (114 rows) — name + ayah count per surah
- `ayah_groups` (3,263 rows) — one row per i'rab block (some span multiple ayat)
- `ayat` (6,236 rows) — canonical complete; each row has `text`, `text_normalized`, links to its group
- `irab_entries` (~7,000 rows) — one row per section type per group
- `ayah_words` (64,067 rows) — word-by-word grammatical analysis
- `footnotes` (4,580 rows) — scholarly notes attached to groups
- `ayat_fts` — FTS5 virtual table over `ayat.text_normalized` for partial-phrase search
- `irab_fts` — FTS5 virtual table over `irab_entries.content_normalized` for grammar-term search

## Arabic normalization

The hardest single problem in any Arabic search system is matching what the
user types against what's stored. This project provides a battle-tested
[`normalize_ar`](src/quran_irab/normalize.py) function that handles:

- Tashkeel (all diacritics)
- Dagger alif (ٰ → ا) — bridges Hafs and Uthmani scripts
- Alif variants (أإآٱ → ا)
- Hamza-bearer normalization (ىئ → يء)
- Ta marbuta (ة → ه)
- Tatweel, BOMs, zero-width joiners, Quranic annotation marks

A second `loose_match_normalize` exists for cross-tradition validation
(handles `ؤ↔ءو`, `ص↔س` family equivalences). See
[docs/arabic-normalization.md](docs/arabic-normalization.md).

## Sourcing the input

This project parses الجدول في إعراب القرآن (Mahmud Safi). The HTML files
are not included in this repository for copyright reasons. You can obtain
the book from:

- Printed copies via Dar Al-Rashid (Damascus) or major Islamic bookstores
- HTML scans from public scholarly archives such as the
  [Shamela library](https://shamela.ws/) (المكتبة الشاملة) — Book No. 21686

The expected structure is 15 HTML files (`001.htm` through `015.htm`)
placed in `sources/الجدول/`.

## Coverage

| Metric | Value |
|---|---|
| Surahs detected | 114 / 114 ✅ |
| Native extraction | 6,210 / 6,236 ayat (99.6%) |
| With backfill from Tanzil | **6,236 / 6,236 ayat (100%)** ✅ |
| Exact text match against Tanzil | 6,134 / 6,236 (98.4%) |
| Script-variant matches (e.g. `ؤ↔ءو`) | +98 ayat |
| Backfilled (muqatta'at gaps in source) | 26 ayat |

The 76 remaining mismatches are all genuine Hafs Ottoman vs Tanzil simplified
script variants (same ayah, different spelling tradition) — see
[docs/normalization.md](docs/arabic-normalization.md) for examples.

## Attribution

The grammatical commentary indexed by this project is the lifelong work of
**Sheikh Mahmud Safi (محمود صافي) — may Allah have mercy upon him**.
This project is a digital preservation effort. See [NOTICE.md](NOTICE.md)
for the full attribution and required-credit text when redistributing.

The Quranic text itself is the literal word of Allah and is in the public
domain. The Tanzil canonical reference is used under
[CC BY-ND 3.0](https://creativecommons.org/licenses/by-nd/3.0/).

## Contributing

Contributions are welcome — especially:

- **Parser quality**: edge cases in the source HTML, better word-level
  extraction precision, per-ayah i'rab splitting inside multi-ayah groups
- **Documentation**: more example queries, schema diagrams, translations
- **Bindings**: Dart/Swift/Kotlin packages that wrap the SQLite DB
- **Tests**: golden-file tests for more surahs, normalization edge cases

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development workflow.

## License

[MIT](LICENSE) for the code. The Quranic text is public domain. The
i'rab content remains the intellectual property of the original
author — see [NOTICE.md](NOTICE.md).
