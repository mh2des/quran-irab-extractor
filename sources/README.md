# Source HTML files go here

This directory is where you place your local copy of
**الجدول في إعراب القرآن** (Mahmud Safi) before running the pipeline.

## Expected layout

```
sources/
└── الجدول/
    ├── 001.htm
    ├── 002.htm
    ├── …
    └── 015.htm
```

15 HTML files, one per volume, named `001.htm` through `015.htm`.

## Where to obtain the source

The الجدول HTML is not redistributed with this project (see [NOTICE.md](../NOTICE.md)
for why). You can obtain it from:

- The [Shamela library](https://shamela.ws/book/21686) — book ID 21686.
  Download the HTML version and place the volume files here.
- Printed copies from Dar Al-Rashid (Damascus) or major Islamic
  bookstores worldwide — scan and OCR them yourself if needed.

## After placing the files

```bash
# From the repo root:
quran-irab batch sources/الجدول --out out/full.jsonl
quran-irab validate out/full.jsonl --out out/validated.jsonl
quran-irab build-db out/validated.jsonl --out out/irab.sqlite
```

That's it — `out/irab.sqlite` is your ready-to-ship database.
