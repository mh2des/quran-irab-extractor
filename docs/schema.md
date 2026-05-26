# Database schema

The shippable SQLite database has 7 base tables, 2 FTS5 virtual tables,
and 1 metadata table. All identifiers are stable across schema-version 1.

## Tables

### `surahs`

The 114 canonical surahs, used as a foreign-key target and a name lookup.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PRIMARY KEY | 1–114 |
| `name` | TEXT | Canonical Arabic name (e.g. `الفاتحة`) |
| `ayah_count` | INTEGER | Canonical ayah count per Hafs |

### `ayah_groups`

One row per i'rab block. Some groups span multiple consecutive ayat that
share a single grammatical analysis (this is `الجدول`'s style for short
adjacent ayat).

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PRIMARY KEY | |
| `surah` | INTEGER NOT NULL | FK → `surahs.id` |
| `ayah_start` | INTEGER NOT NULL | Inclusive |
| `ayah_end` | INTEGER NOT NULL | Inclusive; equal to `ayah_start` for single-ayah groups |
| `is_backfilled` | INTEGER NOT NULL | 1 if the group was generated from canonical Tanzil text because الجدول didn't cover this ayah |

### `ayat`

The canonical 6,236-row table. Every Quranic ayah is here — either with
extracted text from `الجدول` or backfilled from Tanzil.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PRIMARY KEY | |
| `surah` | INTEGER NOT NULL | |
| `ayah` | INTEGER NOT NULL | Ayah number within the surah |
| `text` | TEXT NOT NULL | Display text with tashkeel |
| `text_normalized` | TEXT NOT NULL | Pre-normalized form for FTS5 |
| `group_id` | INTEGER NOT NULL | FK → `ayah_groups.id` |
| `is_backfilled` | INTEGER NOT NULL | |
| UNIQUE | `(surah, ayah)` | |

### `irab_entries`

Holds the grammatical commentary. **Schema v2 splits i'rab per-ayah:**

- `section='irab'`: **one row per ayah**. `ayah` is set to that ayah's number.
  A multi-ayah group's i'rab block is split using the source's `N -` / `(N)`
  per-ayah markers (see [source-format.md](source-format.md)). When the source
  genuinely merged the ayat (no markers), each ayah gets the whole block with
  `is_shared = 1`.
- `section='sarf'|'balagha'|'fawaid'|'mufradat'`: **one row per group**, with
  `ayah = NULL` (these are inherently group-level). For a multi-ayah group the
  app labels them "covers ayat X–Y".

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PRIMARY KEY | |
| `group_id` | INTEGER NOT NULL | FK → `ayah_groups.id` |
| `ayah` | INTEGER NULL | The specific ayah for `irab` rows; NULL for group-level sections |
| `section` | TEXT NOT NULL | One of `irab`, `sarf`, `balagha`, `fawaid`, `mufradat` |
| `is_shared` | INTEGER NOT NULL | 1 when this `irab` row is the whole group block shared across an undelimited multi-ayah group |
| `content` | TEXT NOT NULL | Rich text with `[N]` footnote markers and `### sub-headings` |
| `content_normalized` | TEXT NOT NULL | For FTS5 |

To fetch one ayah's full bundle:

```sql
SELECT section, content, is_shared
FROM irab_entries
WHERE group_id = ? AND (ayah = ? OR ayah IS NULL);
```

### `ayah_words`

Word-by-word grammatical analysis, extracted **per ayah** from the (split)
`irab` segment. Only the word-by-word portion is captured — the sentence-level
(جُمَل) analysis that follows it in the source is excluded.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PRIMARY KEY | |
| `group_id` | INTEGER NOT NULL | FK → `ayah_groups.id` |
| `ayah` | INTEGER NOT NULL | The specific ayah these words parse |
| `position` | INTEGER NOT NULL | 0-indexed position within the ayah's i'rab |
| `token` | TEXT NOT NULL | The Arabic word being parsed (e.g. `الحمد`) |
| `token_normalized` | TEXT NOT NULL | Normalized form |
| `analysis` | TEXT NOT NULL | Grammatical role (e.g. `مبتدأ مرفوع`) |

### `footnotes`

Scholarly footnotes attached to a group. Markers in `irab_entries.content`
appear as `[1]`, `[2]`, etc.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PRIMARY KEY | |
| `group_id` | INTEGER NOT NULL | FK → `ayah_groups.id` |
| `marker` | TEXT | Usually `"1"`, `"2"`, etc. |
| `content` | TEXT NOT NULL | The footnote body |

### `meta`

Build metadata as key-value pairs. Useful for migrations and version checks.

| Key | Example value |
|---|---|
| `schema_version` | `1` |
| `source` | `الجدول في إعراب القرآن — محمود صافي` |
| `canonical_reference` | `Tanzil simple-clean (via alquran.cloud)` |
| `build_date` | `2026-05-24` |
| `total_ayat` | `6236` |
| `total_groups` | `3263` |

## FTS5 virtual tables

### `ayat_fts`

Full-text index over `ayat.text_normalized`. Use for "user types a partial
Quranic phrase, find matching ayat".

```sql
SELECT a.surah, a.ayah, a.text
FROM ayat_fts f
JOIN ayat a ON a.id = f.rowid
WHERE ayat_fts MATCH 'الحمد لله رب'
ORDER BY rank LIMIT 10;
```

Prefix queries are supported:

```sql
... WHERE ayat_fts MATCH 'صراط*';
```

### `irab_fts`

Full-text index over `irab_entries.content_normalized`. Use for "find
every ayah whose i'rab/sarf/balagha/fawaid mentions a particular term".

```sql
SELECT g.surah, g.ayah_start, ie.section, SUBSTR(ie.content, 1, 100)
FROM irab_fts f
JOIN irab_entries ie ON ie.id = f.rowid
JOIN ayah_groups g ON g.id = ie.group_id
WHERE irab_fts MATCH 'مفعول مطلق'
ORDER BY rank LIMIT 10;
```

## Common queries

### Get the full i'rab bundle for an ayah

```sql
SELECT ie.section, ie.content
FROM ayat a
JOIN irab_entries ie ON ie.group_id = a.group_id
WHERE a.surah = ? AND a.ayah = ?
ORDER BY CASE ie.section
  WHEN 'irab' THEN 1
  WHEN 'sarf' THEN 2
  WHEN 'balagha' THEN 3
  WHEN 'fawaid' THEN 4
  ELSE 5
END;
```

### Get word-by-word analysis for an ayah

```sql
SELECT w.position, w.token, w.analysis
FROM ayat a
JOIN ayah_words w ON w.group_id = a.group_id
WHERE a.surah = ? AND a.ayah = ?
ORDER BY w.position;
```

### List all surahs with their ayah counts

```sql
SELECT id, name, ayah_count FROM surahs ORDER BY id;
```
