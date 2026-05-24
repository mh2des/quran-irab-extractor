"""`irab-extract` command-line entry point."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from .assemble import Assembler
from .db import build_database
from .tokenize import tokenize_file
from .validate import iter_jsonl, validate_and_backfill


@click.group()
def main() -> None:
    """Extraction pipeline for الجدول في إعراب القرآن."""


@main.command()
@click.argument("source", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--out", "out_path", type=click.Path(dir_okay=False, path_type=Path), required=True)
@click.option("--starting-surah", type=int, default=1, show_default=True,
              help="Surah ID for the first 'سورة X' title encountered in this file.")
@click.option("--surah", "filter_surah", type=int, default=None,
              help="If set, only emit groups for this surah ID.")
def parse(source: Path, out_path: Path, starting_surah: int, filter_surah: int | None) -> None:
    """Parse one volume HTML file → JSONL."""
    click.echo(f"Tokenizing {source.name} …", err=True)
    events = list(tokenize_file(source))
    click.echo(f"  {len(events)} events", err=True)

    asm = Assembler(starting_surah=starting_surah)
    groups = asm.consume(events)
    click.echo(f"  {len(groups)} ayah groups", err=True)

    if filter_surah is not None:
        groups = [g for g in groups if g.surah == filter_surah]
        click.echo(f"  {len(groups)} after surah-filter", err=True)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for g in groups:
            f.write(json.dumps(g.to_dict(), ensure_ascii=False))
            f.write("\n")
    click.echo(f"Wrote {out_path}", err=True)


@main.command(name="tokenize")
@click.argument("source", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--limit", type=int, default=50, show_default=True)
def tokenize_cmd(source: Path, limit: int) -> None:
    """Dump the first N events for debugging."""
    for i, ev in enumerate(tokenize_file(source)):
        if i >= limit:
            break
        click.echo(repr(ev))


@main.command()
@click.argument("source_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--out", "out_path", type=click.Path(dir_okay=False, path_type=Path),
              required=True, help="Output JSONL path (single combined file).")
@click.option("--pattern", default="*.htm", show_default=True)
def batch(source_dir: Path, out_path: Path, pattern: str) -> None:
    """Parse every volume in source_dir in order, into one JSONL stream."""
    files = sorted(source_dir.glob(pattern))
    if not files:
        click.echo(f"No files matching {pattern} in {source_dir}", err=True)
        sys.exit(1)
    click.echo(f"Found {len(files)} volumes", err=True)

    def all_events():
        for f in files:
            click.echo(f"  tokenizing {f.name}", err=True)
            yield from tokenize_file(f)

    asm = Assembler(starting_surah=1)
    groups = asm.consume(all_events())
    click.echo(f"Assembled {len(groups)} ayah groups", err=True)

    surahs_seen = sorted({g.surah for g in groups})
    click.echo(f"Surah IDs covered: {surahs_seen[:5]} … {surahs_seen[-5:]} "
               f"(total {len(surahs_seen)})", err=True)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    total_ayat = 0
    with out_path.open("w", encoding="utf-8") as f:
        for g in groups:
            f.write(json.dumps(g.to_dict(), ensure_ascii=False))
            f.write("\n")
            total_ayat += len(g.ayat)
    click.echo(f"Wrote {out_path} — {total_ayat} ayat, "
               f"{out_path.stat().st_size / 1024 / 1024:.1f} MB", err=True)


@main.command()
@click.argument("jsonl", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def stats(jsonl: Path) -> None:
    """Print coverage stats for a JSONL output."""
    by_surah: dict[int, dict] = {}
    total = {"groups": 0, "ayat": 0, "irab": 0, "sarf": 0, "balagha": 0, "fawaid": 0,
             "mufradat": 0, "words": 0, "footnotes": 0}
    with jsonl.open(encoding="utf-8") as f:
        for line in f:
            g = json.loads(line)
            sid = g["surah"]
            s = by_surah.setdefault(sid, {
                "name": g["surah_name"], "groups": 0, "ayat": 0,
                "ayat_with_irab": 0, "min_ayah": 999999, "max_ayah": 0,
            })
            s["groups"] += 1
            s["ayat"] += len(g["ayat"])
            s["min_ayah"] = min(s["min_ayah"], g["ayah_start"])
            s["max_ayah"] = max(s["max_ayah"], g["ayah_end"])
            total["groups"] += 1
            total["ayat"] += len(g["ayat"])
            total["footnotes"] += len(g["footnotes"])
            for k, sec in g["sections"].items():
                total[k] = total.get(k, 0) + 1
                if k == "irab":
                    s["ayat_with_irab"] += len(g["ayat"])
                    total["words"] += len(sec["words"])

    click.echo(f"Per-surah:")
    for sid in sorted(by_surah):
        s = by_surah[sid]
        click.echo(f"  {sid:>3}. {s['name']:<20} groups={s['groups']:>4} "
                   f"ayat={s['ayat']:>4} "
                   f"range={s['min_ayah']}-{s['max_ayah']} "
                   f"with_irab={s['ayat_with_irab']}")
    click.echo()
    click.echo("Totals:")
    for k, v in total.items():
        click.echo(f"  {k:<12} {v}")


@main.command()
@click.argument("jsonl", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--out", "out_path", type=click.Path(dir_okay=False, path_type=Path),
              help="If set, write validated + backfilled JSONL here.")
@click.option("--report", "report_path", type=click.Path(dir_okay=False, path_type=Path),
              help="If set, write detailed mismatch report (JSON) here.")
@click.option("--max-show", type=int, default=10, show_default=True,
              help="Max mismatches to print to stdout.")
def validate(jsonl: Path, out_path: Path | None, report_path: Path | None, max_show: int) -> None:
    """Validate extracted ayat against canonical Tanzil/Uthmani Quran."""
    groups = list(iter_jsonl(jsonl))
    click.echo(f"Loaded {len(groups)} groups from {jsonl}", err=True)

    augmented, report = validate_and_backfill(groups)

    click.echo()
    click.echo(f"=== Validation Report ===")
    click.echo(f"  Expected ayat:        {report.total_expected}")
    click.echo(f"  Matched (exact):      {report.matched}")
    click.echo(f"  Mismatched:           {len(report.mismatched)}")
    click.echo(f"  Backfilled (missing): {len(report.backfilled)}")
    click.echo(f"  Duplicate emissions:  {len(report.duplicate_emissions)}")
    click.echo(f"  Coverage (matched):   {report.coverage*100:.2f}%")
    if report.backfilled:
        click.echo(f"\n  Backfilled positions: "
                   f"{', '.join(f'{s}:{a}' for s, a in report.backfilled[:20])}"
                   f"{' …' if len(report.backfilled) > 20 else ''}")
    if report.mismatched:
        click.echo(f"\n  First {min(max_show, len(report.mismatched))} mismatches:")
        for m in report.mismatched[:max_show]:
            click.echo(f"    {m.surah}:{m.ayah}")
            click.echo(f"      extracted: {m.extracted[:80]}")
            click.echo(f"      canonical: {m.canonical[:80]}")
            click.echo(f"      norm-ext : {m.extracted_norm[:80]}")
            click.echo(f"      norm-can : {m.canonical_norm[:80]}")

    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            for g in augmented:
                f.write(json.dumps(g, ensure_ascii=False))
                f.write("\n")
        click.echo(f"\n  Wrote validated JSONL: {out_path} ({len(augmented)} groups)", err=True)

    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps({
            "total_expected": report.total_expected,
            "matched": report.matched,
            "coverage": report.coverage,
            "backfilled": [{"surah": s, "ayah": a} for s, a in report.backfilled],
            "duplicate_emissions": [{"surah": s, "ayah": a} for s, a in report.duplicate_emissions],
            "mismatched": [m.to_dict() for m in report.mismatched],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        click.echo(f"  Wrote detail report: {report_path}", err=True)


@main.command(name="build-db")
@click.argument("jsonl", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--out", "out_path", type=click.Path(dir_okay=False, path_type=Path),
              required=True, help="Where to write the SQLite database.")
def build_db_cmd(jsonl: Path, out_path: Path) -> None:
    """Build the shippable SQLite + FTS5 database from a validated JSONL."""
    click.echo(f"Building DB from {jsonl} → {out_path}", err=True)
    stats = build_database(jsonl, out_path)
    size_mb = out_path.stat().st_size / 1024 / 1024
    click.echo()
    click.echo("=== Build complete ===")
    for k, v in stats.items():
        click.echo(f"  {k:<22} {v}")
    click.echo(f"  {'file_size_mb':<22} {size_mb:.1f}")


if __name__ == "__main__":
    main()
