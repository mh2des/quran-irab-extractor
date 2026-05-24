"""
Build the shippable SQLite + FTS5 database from validated.jsonl.

Schema notes:
  - ayat is the canonical 6236-row table keyed by (surah, ayah). Every Quranic ayah
    has a row here — either with extracted text from الجدول or backfilled from Tanzil.
  - ayah_groups represent the i'rab-block grouping (some groups span multiple ayat).
    Multiple ayat point to the same group_id when they share one i'rab block.
  - Two FTS5 virtual tables: one over ayah text (for "user types a phrase"),
    one over i'rab content (for "search inside explanations").
  - text_normalized columns are pre-normalized using normalize_ar(); FTS5 sees them
    as plain whitespace-separated tokens (no on-the-fly diacritic stripping needed).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Iterable

from .normalize import normalize_ar
from .surahs import CANONICAL_AYAH_COUNTS, CANONICAL_NAMES

SCHEMA_VERSION = 1

SCHEMA_SQL = """
PRAGMA journal_mode = OFF;
PRAGMA synchronous = OFF;
PRAGMA temp_store = MEMORY;

CREATE TABLE surahs (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    ayah_count   INTEGER NOT NULL
);

CREATE TABLE ayah_groups (
    id           INTEGER PRIMARY KEY,
    surah        INTEGER NOT NULL REFERENCES surahs(id),
    ayah_start   INTEGER NOT NULL,
    ayah_end     INTEGER NOT NULL,
    is_backfilled INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_groups_surah ON ayah_groups(surah, ayah_start);

CREATE TABLE ayat (
    id               INTEGER PRIMARY KEY,
    surah            INTEGER NOT NULL,
    ayah             INTEGER NOT NULL,
    text             TEXT NOT NULL,
    text_normalized  TEXT NOT NULL,
    group_id         INTEGER NOT NULL REFERENCES ayah_groups(id),
    is_backfilled    INTEGER NOT NULL DEFAULT 0,
    UNIQUE(surah, ayah)
);
CREATE INDEX idx_ayat_surah ON ayat(surah);
CREATE INDEX idx_ayat_group ON ayat(group_id);

CREATE TABLE irab_entries (
    id                 INTEGER PRIMARY KEY,
    group_id           INTEGER NOT NULL REFERENCES ayah_groups(id),
    section            TEXT NOT NULL,    -- 'irab' | 'sarf' | 'balagha' | 'fawaid' | 'mufradat'
    content            TEXT NOT NULL,
    content_normalized TEXT NOT NULL
);
CREATE INDEX idx_irab_group_section ON irab_entries(group_id, section);

CREATE TABLE ayah_words (
    id               INTEGER PRIMARY KEY,
    group_id         INTEGER NOT NULL REFERENCES ayah_groups(id),
    position         INTEGER NOT NULL,
    token            TEXT NOT NULL,
    token_normalized TEXT NOT NULL,
    analysis         TEXT NOT NULL
);
CREATE INDEX idx_words_group ON ayah_words(group_id, position);
CREATE INDEX idx_words_token ON ayah_words(token_normalized);

CREATE TABLE footnotes (
    id         INTEGER PRIMARY KEY,
    group_id   INTEGER NOT NULL REFERENCES ayah_groups(id),
    marker     TEXT,
    content    TEXT NOT NULL
);
CREATE INDEX idx_footnotes_group ON footnotes(group_id);

CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE VIRTUAL TABLE ayat_fts USING fts5(
    text_normalized,
    content='ayat',
    content_rowid='id'
);

CREATE VIRTUAL TABLE irab_fts USING fts5(
    content_normalized,
    content='irab_entries',
    content_rowid='id'
);
"""


def build_database(jsonl_path: Path, out_path: Path) -> dict:
    """Build the shippable SQLite from validated JSONL. Returns build stats."""
    if out_path.exists():
        out_path.unlink()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(out_path)
    conn.executescript(SCHEMA_SQL)

    # 1) Surahs
    conn.executemany(
        "INSERT INTO surahs (id, name, ayah_count) VALUES (?, ?, ?)",
        [(sid, CANONICAL_NAMES[sid], CANONICAL_AYAH_COUNTS[sid]) for sid in sorted(CANONICAL_NAMES)],
    )

    # 2) Walk JSONL, insert groups + ayat + sections + words + footnotes
    stats = {
        "groups": 0, "ayat": 0, "irab_entries": 0,
        "ayah_words": 0, "footnotes": 0, "backfilled_groups": 0,
    }

    for group in _iter_jsonl(jsonl_path):
        is_backfilled = 1 if group.get("backfilled") else 0
        if is_backfilled:
            stats["backfilled_groups"] += 1

        cur = conn.execute(
            "INSERT INTO ayah_groups (surah, ayah_start, ayah_end, is_backfilled) "
            "VALUES (?, ?, ?, ?)",
            (group["surah"], group["ayah_start"], group["ayah_end"], is_backfilled),
        )
        group_id = cur.lastrowid
        stats["groups"] += 1

        for ayah in group["ayat"]:
            conn.execute(
                "INSERT OR REPLACE INTO ayat "
                "(surah, ayah, text, text_normalized, group_id, is_backfilled) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    group["surah"], ayah["num"],
                    ayah["text"],
                    ayah.get("text_normalized") or normalize_ar(ayah["text"]),
                    group_id, is_backfilled,
                ),
            )
            stats["ayat"] += 1

        for section_key, section in group.get("sections", {}).items():
            conn.execute(
                "INSERT INTO irab_entries (group_id, section, content, content_normalized) "
                "VALUES (?, ?, ?, ?)",
                (
                    group_id, section_key,
                    section["content"],
                    section.get("content_normalized") or normalize_ar(section["content"]),
                ),
            )
            stats["irab_entries"] += 1

            if section_key == "irab":
                for w in section.get("words", []):
                    conn.execute(
                        "INSERT INTO ayah_words "
                        "(group_id, position, token, token_normalized, analysis) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (group_id, w["position"], w["token"],
                         normalize_ar(w["token"]), w["analysis"]),
                    )
                    stats["ayah_words"] += 1

        for fn in group.get("footnotes", []):
            conn.execute(
                "INSERT INTO footnotes (group_id, marker, content) VALUES (?, ?, ?)",
                (group_id, fn.get("marker") or "", fn["text"]),
            )
            stats["footnotes"] += 1

    # 3) Populate FTS5 indexes (faster as one bulk insert at the end)
    conn.execute(
        "INSERT INTO ayat_fts (rowid, text_normalized) "
        "SELECT id, text_normalized FROM ayat"
    )
    conn.execute(
        "INSERT INTO irab_fts (rowid, content_normalized) "
        "SELECT id, content_normalized FROM irab_entries"
    )

    # 4) Meta
    conn.executemany(
        "INSERT INTO meta (key, value) VALUES (?, ?)",
        [
            ("schema_version", str(SCHEMA_VERSION)),
            ("source", "الجدول في إعراب القرآن — محمود صافي"),
            ("canonical_reference", "Tanzil simple-clean (via alquran.cloud)"),
            ("build_date", date.today().isoformat()),
            ("total_ayat", str(stats["ayat"])),
            ("total_groups", str(stats["groups"])),
            ("total_irab_entries", str(stats["irab_entries"])),
            ("total_words", str(stats["ayah_words"])),
        ],
    )

    conn.commit()
    # Optimize for read-only shipping
    conn.executescript("PRAGMA journal_mode = DELETE; VACUUM; ANALYZE;")
    conn.close()
    return stats


def _iter_jsonl(path: Path) -> Iterable[dict]:
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)
