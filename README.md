# citation-check

Check that every reference in a `.bib` file is a real paper, with the right title, year and first author.

AI writing tools invent citations that look right. This catches them before a reviewer does.

```
$ python3 scripts/citation_check.py examples/ai-music-refs.bib
VERIFIED   copet2023musicgen
VERIFIED   huang2019musictransformer
NOT_FOUND  fake2024harmony
           - no paper with this title found
MISMATCH   he2016resnet
           - year 2012 vs 2016

2 verified, 1 mismatch, 1 not_found, 0 error
```

## What it does

Each entry is looked up by DOI (Crossref), arXiv id (arXiv), or title (Crossref and OpenAlex). The record found is compared with what your entry claims.

| Status | Meaning |
|---|---|
| `VERIFIED` | Found, and title, year (±1) and first author match. |
| `MISMATCH` | Found, but a detail is off, or the DOI points to a different paper. |
| `NOT_FOUND` | No index has a paper with that title. It may be invented, or it may be a thesis, book chapter or very new preprint. |
| `ERROR` | An index did not answer. It is never reported as `NOT_FOUND`. |

OpenAlex is included because Crossref misses conference papers that live only on OpenReview, such as most of ICLR.

## Quick start

```bash
git clone https://github.com/hey-shiv/citation-check.git
cd citation-check
python3 scripts/citation_check.py path/to/refs.bib
```

Options:

- `--json` prints results as JSON.
- `--mailto you@example.com` puts you in Crossref's faster "polite pool".
- `--delay 1` sets seconds between lookups (default 1).

The exit code is 1 if any entry is `NOT_FOUND` or `MISMATCH`, 2 if some could not be checked, and 0 if all are verified, so you can run it in CI.

## Use it from Claude Code

```bash
bash install.sh
```

This copies the script to `~/.claude/research-kit/` and the `citation-check` skill to `~/.claude/skills/`, without overwriting anything. Then ask Claude Code to "check my citations". It runs the script, reports the problems, and only edits your `.bib` after you agree. It never invents a replacement reference.

## Privacy and limits

- Only titles, DOIs and arXiv ids are sent, to Crossref, OpenAlex and arXiv. Nothing else leaves your machine.
- Python 3.9+, standard library only. macOS or Linux.
- It checks that a paper exists and the metadata matches. It does not check that the paper says what you cite it for.
- Books, theses and non-English venues are covered less well and may show as `NOT_FOUND`.

## Tests

```bash
python3 -m pytest tests
```

## The full kit

This is one of five skills in the **Claude Code Research Kit for ML Engineers**: paper digest, related-work table, citation check, reproduction plan, and Zotero to Obsidian. Join the waitlist: https://shivashant.gumroad.com/l/mjjiv

MIT licensed.
