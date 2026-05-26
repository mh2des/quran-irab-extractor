"""Database build + schema integrity tests."""

import json
import sqlite3
from pathlib import Path

import pytest

from quran_irab.db import build_database


@pytest.fixture
def sample_jsonl(tmp_path: Path) -> Path:
    """Two groups: one normal Al-Fatiha-style, one backfilled."""
    path = tmp_path / "sample.jsonl"
    groups = [
        {
            "surah": 1, "surah_name": "الفاتحة",
            "ayah_start": 1, "ayah_end": 1,
            "ayat": [{"num": 1, "text": "بِسْمِ اللهِ الرَّحْمنِ الرَّحِيمِ",
                      "text_normalized": "بسم الله الرحمن الرحيم"}],
            "sections": {
                "irab": {
                    "content": "(بسم) جار ومجرور",
                    "content_normalized": "(بسم) جار ومجرور",
                    "words": [
                        {"position": 0, "token": "بسم", "analysis": "جار ومجرور"}
                    ],
                }
            },
            "footnotes": [{"marker": "1", "text": "حاشية اختبارية"}],
            "source_pages": [{"volume": 1, "page": 27}],
        },
        {
            "surah": 26, "surah_name": "الشعراء",
            "ayah_start": 1, "ayah_end": 1,
            "ayat": [{"num": 1, "text": "طسم", "text_normalized": "طسم"}],
            "sections": {},
            "footnotes": [],
            "source_pages": [],
            "backfilled": True,
        },
    ]
    with path.open("w", encoding="utf-8") as f:
        for g in groups:
            f.write(json.dumps(g, ensure_ascii=False) + "\n")
    return path


class TestDatabaseBuild:
    def test_build_creates_file(self, sample_jsonl: Path, tmp_path: Path):
        out = tmp_path / "test.sqlite"
        stats = build_database(sample_jsonl, out)
        assert out.exists()
        assert stats["groups"] == 2
        assert stats["ayat"] == 2
        assert stats["irab_entries"] == 1
        assert stats["ayah_words"] == 1
        assert stats["footnotes"] == 1
        assert stats["backfilled_groups"] == 1

    def test_all_114_surahs_seeded(self, sample_jsonl: Path, tmp_path: Path):
        out = tmp_path / "test.sqlite"
        build_database(sample_jsonl, out)
        conn = sqlite3.connect(out)
        count = conn.execute("SELECT COUNT(*) FROM surahs").fetchone()[0]
        assert count == 114

    def test_ayah_search_via_fts5(self, sample_jsonl: Path, tmp_path: Path):
        out = tmp_path / "test.sqlite"
        build_database(sample_jsonl, out)
        conn = sqlite3.connect(out)
        rows = conn.execute(
            "SELECT a.surah, a.ayah FROM ayat_fts f "
            "JOIN ayat a ON a.id = f.rowid WHERE ayat_fts MATCH 'بسم'"
        ).fetchall()
        assert (1, 1) in rows

    def test_irab_search_via_fts5(self, sample_jsonl: Path, tmp_path: Path):
        out = tmp_path / "test.sqlite"
        build_database(sample_jsonl, out)
        conn = sqlite3.connect(out)
        rows = conn.execute(
            "SELECT ie.section FROM irab_fts f "
            "JOIN irab_entries ie ON ie.id = f.rowid WHERE irab_fts MATCH 'جار'"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "irab"

    def test_meta_populated(self, sample_jsonl: Path, tmp_path: Path):
        out = tmp_path / "test.sqlite"
        build_database(sample_jsonl, out)
        conn = sqlite3.connect(out)
        meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        assert meta["schema_version"] == "2"
        assert "محمود صافي" in meta["source"]
        assert "Tanzil" in meta["canonical_reference"]

    def test_backfilled_flag_propagates(self, sample_jsonl: Path, tmp_path: Path):
        out = tmp_path / "test.sqlite"
        build_database(sample_jsonl, out)
        conn = sqlite3.connect(out)
        row = conn.execute(
            "SELECT is_backfilled FROM ayat WHERE surah = 26 AND ayah = 1"
        ).fetchone()
        assert row[0] == 1
