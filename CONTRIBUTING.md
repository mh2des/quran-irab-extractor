# Contributing to quran-irab-extractor

Thank you for your interest in contributing! Whether you're filing a bug,
proposing a feature, improving parser quality, or adding language bindings —
contributions are warmly welcome.

## Where help is most valuable

1. **Parser quality** — edge cases in the source HTML where extraction
   misses ayat or produces noisy output. Bring concrete examples (the
   surah and ayah numbers + a snippet from the source).
2. **Word-level extraction precision** — the current regex matches
   `(word) analysis` at sentence start but over-captures mid-sentence
   parentheses. A precision-improving heuristic or ML approach would help.
3. **Per-ayah i'rab splitting in multi-ayah groups** — the source uses
   inline `(N)` markers within combined i'rab blocks to indicate which
   ayah a sub-block applies to. Splitting on these could give us
   per-ayah i'rab attachment in multi-ayah groups.
4. **Language bindings** — Dart, Swift, Kotlin, or TypeScript packages
   that wrap the SQLite DB with idiomatic search APIs.
5. **Documentation** — query recipes, schema diagrams, translations.
6. **Tests** — golden-file tests for more surahs, especially short surahs
   (94, 105, 111…) and complex ones with muqatta'at (2, 26, 40).

## Development setup

```bash
git clone https://github.com/mansoorshakla/quran-irab-extractor.git
cd quran-irab-extractor
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run the test suite
pytest -v

# Lint
ruff check src/ tests/

# Type-check (optional)
mypy src/quran_irab/
```

## Workflow

1. Open an issue first if the change is non-trivial — it lets us discuss
   design before you spend time on code.
2. Fork the repo, create a feature branch (`git checkout -b fix/parser-quirk-X`).
3. Make your change. **Add a test.** Even one assertion is enough — the
   golden-file pattern in `tests/test_assemble.py` is a good template.
4. `pytest` should pass.
5. `ruff check src/ tests/` should pass.
6. Open a PR with a clear description of what the change does and why.

## Code style

- Python 3.11+ (we use modern syntax: `dict | None`, `list[int]`)
- Ruff for linting and formatting
- Type hints on new code
- Comments only for *why*, not *what* — well-named identifiers carry intent

## Reporting parser quirks

The parser handles `الجدول`'s consistent patterns well, but the source
is 15 volumes of hand-edited HTML and has irregularities. If you find
one, please file an issue using the "Parser quirk" template with:

- Surah and ayah number affected
- The actual extracted output (run `quran-irab parse … --surah N`)
- A snippet of the HTML source showing the structural pattern
- What the correct output should be

This lets contributors reproduce the issue quickly and add a regression
test.

## Conduct

Be respectful, helpful, and patient. Many contributors are not native
English speakers; many are not professional programmers. Communication
should reflect the adab (آداب) befitting work in service of the Qur'an.
