#!/usr/bin/env python3
"""Check that every reference in a .bib file is a real paper.

Looks each entry up by DOI (Crossref), arXiv id (arXiv), or title
(Crossref and OpenAlex), and compares title, year and first author
against what the entry claims. Stdlib only; sends only titles, DOIs and
arXiv ids to those public APIs.

Usage:
    python3 citation_check.py refs.bib
    python3 citation_check.py refs.bib --json
    python3 citation_check.py refs.bib --mailto you@example.com

Exit code is 1 if any entry is NOT_FOUND or MISMATCH, 2 if some entries
could not be checked (network errors), 0 if all verified.
"""
import argparse
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher

VERIFIED, MISMATCH, NOT_FOUND, ERROR = "VERIFIED", "MISMATCH", "NOT_FOUND", "ERROR"
TITLE_OK = 0.90
TITLE_MATCH = 0.75
ATOM = "{http://www.w3.org/2005/Atom}"


# --- .bib parsing -----------------------------------------------------------

def _read_value(text, i):
    """Read a braced, quoted or bare value starting at text[i]; return (value, end)."""
    if text[i] == "{":
        depth, j = 0, i
        while j < len(text):
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    return text[i + 1:j], j + 1
            j += 1
        return text[i + 1:], len(text)
    if text[i] == '"':
        j = text.find('"', i + 1)
        j = len(text) if j == -1 else j
        return text[i + 1:j], j + 1
    m = re.match(r"[^,}\s]+", text[i:])
    return (m.group(0), i + m.end()) if m else ("", i)


def parse_bib(text):
    """Return a list of entries: {"key", "type", fields...} with lowercase field names."""
    entries = []
    for m in re.finditer(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", text):
        kind = m.group(1).lower()
        if kind in ("comment", "string", "preamble"):
            continue
        entry = {"key": m.group(2), "type": kind}
        i = m.end()
        while i < len(text):
            fm = re.compile(r"\s*(\w+)\s*=\s*").match(text, i)
            if not fm:
                break
            value, i = _read_value(text, fm.end())
            entry[fm.group(1).lower()] = clean(value)
            cm = re.compile(r"\s*,?").match(text, i)
            i = cm.end()
            if i < len(text) and text[i] == "}":
                break
        entries.append(entry)
    return entries


def clean(value):
    return re.sub(r"\s+", " ", value.replace("{", "").replace("}", "")).strip()


def norm(title):
    return re.sub(r"[^a-z0-9 ]", "", (title or "").lower()).strip()


def similarity(a, b):
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


def first_author_surname(authors):
    """'Vaswani, Ashish and Shazeer, Noam' or 'Ashish Vaswani and ...' -> 'vaswani'."""
    first = (authors or "").split(" and ")[0].strip()
    if not first:
        return ""
    name = first.split(",")[0] if "," in first else first.split()[-1]
    return norm(name)


def arxiv_id(entry):
    for field in ("eprint", "arxiv", "journal", "url", "doi"):
        m = re.search(r"(\d{4}\.\d{4,5})(v\d+)?", entry.get(field, ""))
        if m and (field != "doi" or "arxiv" in entry.get(field, "").lower()):
            return m.group(1)
    return None


# --- lookups ----------------------------------------------------------------

SYSTEM_CA = "/etc/ssl/cert.pem"  # present on macOS and most Linux


RETRY_CODES = (429, 500, 502, 503, 504)


def http_get(url, mailto=None, retries=3, raw=False):
    """GET url and return text (or bytes if raw), retrying rate limits and brief outages."""
    agent = "citation-check/1.0" + (f" (mailto:{mailto})" if mailto else "")
    req = urllib.request.Request(url, headers={"User-Agent": agent})
    ctx, attempt = None, 0
    while True:
        try:
            with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
                body = resp.read()
            return body if raw else body.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            # rate limited or briefly down: wait (Retry-After if given) and try again
            if e.code not in RETRY_CODES or attempt == retries:
                raise
            wait = e.headers.get("Retry-After", "")
            time.sleep(min(int(wait), 30) if wait.isdigit() else 2 * 2 ** attempt)
            attempt += 1
        except urllib.error.URLError as e:
            # python.org builds on macOS ship without CA certificates; retry with the system bundle
            if ctx or not isinstance(e.reason, ssl.SSLCertVerificationError) or not os.path.exists(SYSTEM_CA):
                raise
            ctx = ssl.create_default_context(cafile=SYSTEM_CA)


def _crossref_item(item):
    year = None
    for key in ("published-print", "published-online", "issued", "created"):
        parts = (item.get(key) or {}).get("date-parts") or [[None]]
        if parts[0] and parts[0][0]:
            year = parts[0][0]
            break
    authors = item.get("author") or [{}]
    return {
        "title": (item.get("title") or [""])[0],
        "year": year,
        "author": norm(authors[0].get("family", "")),
        "doi": item.get("DOI"),
        "source": "crossref",
    }


def lookup_doi(doi, fetch):
    data = json.loads(fetch("https://api.crossref.org/works/" + urllib.parse.quote(doi)))
    return _crossref_item(data["message"])


def lookup_arxiv(aid, fetch):
    root = ET.fromstring(fetch("https://export.arxiv.org/api/query?id_list=" + aid))
    entry = root.find(ATOM + "entry")
    if entry is None or entry.find(ATOM + "title") is None:
        return None
    author = entry.find(ATOM + "author/" + ATOM + "name")
    published = entry.findtext(ATOM + "published", "")
    return {
        "title": clean(entry.findtext(ATOM + "title", "")),
        "year": int(published[:4]) if published[:4].isdigit() else None,
        "author": first_author_surname(author.text) if author is not None else "",
        "doi": None,
        "source": "arxiv",
    }


def _openalex_items(title, fetch):
    q = urllib.parse.urlencode({"search": title, "per-page": 3,
                                "select": "title,publication_year,authorships,doi"})
    for w in json.loads(fetch("https://api.openalex.org/works?" + q))["results"]:
        authors = w.get("authorships") or [{}]
        yield {
            "title": w.get("title") or "",
            "year": w.get("publication_year"),
            "author": first_author_surname((authors[0].get("author") or {}).get("display_name", "")),
            "doi": (w.get("doi") or "").replace("https://doi.org/", "") or None,
            "source": "openalex",
        }


def _crossref_search(title, fetch):
    q = urllib.parse.urlencode({"query.bibliographic": title, "rows": 3})
    return [_crossref_item(i) for i in json.loads(fetch("https://api.crossref.org/works?" + q))["message"]["items"]]


SEARCHES = {"crossref": _crossref_search, "openalex": lambda t, f: list(_openalex_items(t, f))}


def search_title(title, fetch):
    """Search every index by title; return (best match or None, names of indexes that failed).

    Crossref misses conference papers that live only on OpenReview (e.g. ICLR),
    which OpenAlex covers, so a title is only called missing when both answered.
    """
    candidates, failed = [], []
    for name, search in SEARCHES.items():
        try:
            candidates.extend(search(title, fetch))
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
            failed.append(name)
    best = max(candidates, key=lambda c: similarity(title, c["title"]), default=None)
    return best, failed


# --- verdict ----------------------------------------------------------------

def judge(entry, found, by_id=False):
    """Compare the entry with the record found; return (status, list of problems)."""
    if found is None:
        return NOT_FOUND, ["no paper with this title found"]
    if similarity(entry.get("title"), found["title"]) < TITLE_MATCH:
        if by_id:
            return MISMATCH, [f"DOI/arXiv id points to a different paper: \"{found['title']}\""]
        return NOT_FOUND, ["no paper with this title found"]
    problems = []
    if similarity(entry.get("title"), found["title"]) < TITLE_OK:
        problems.append(f"title differs: found \"{found['title']}\"")
    year = entry.get("year", "")
    if year.isdigit() and found["year"] and abs(int(year) - int(found["year"])) > 1:
        problems.append(f"year {year} vs {found['year']}")
    claimed = first_author_surname(entry.get("author"))
    if claimed and found["author"] and claimed != found["author"]:
        problems.append(f"first author {claimed} vs {found['author']}")
    return (MISMATCH if problems else VERIFIED), problems


def check_entry(entry, fetch):
    key, failed, by_id = entry["key"], [], True
    try:
        if entry.get("doi") and not arxiv_id({"doi": entry["doi"]}):
            found = lookup_doi(entry["doi"], fetch)
        elif arxiv_id(entry):
            try:
                found = lookup_arxiv(arxiv_id(entry), fetch)
            except (urllib.error.URLError, TimeoutError, ET.ParseError) as e:
                # arXiv rate-limits hard; OpenAlex indexes arXiv, so fall back to the title
                if getattr(e, "code", None) == 404 or not entry.get("title"):
                    raise
                found, failed = search_title(entry["title"], fetch)
                by_id = False
        elif entry.get("title"):
            found, failed = search_title(entry["title"], fetch)
            by_id = False
        else:
            return {"key": key, "status": ERROR, "problems": ["entry has no title, DOI or arXiv id"]}
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"key": key, "status": NOT_FOUND, "problems": ["DOI or arXiv id does not resolve"]}
        return {"key": key, "status": ERROR, "problems": [f"HTTP {e.code}"]}
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, ET.ParseError) as e:
        return {"key": key, "status": ERROR, "problems": [f"lookup failed: {e}"]}
    status, problems = judge(entry, found, by_id)
    if status == NOT_FOUND and failed:
        # never call a paper missing when an index did not answer
        status, problems = ERROR, [f"not confirmed: could not reach {', '.join(failed)}"]
    return {"key": key, "status": status, "problems": problems, "found": found}


def main(argv=None, fetch=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("bib", help="path to a .bib file")
    ap.add_argument("--json", action="store_true", help="print results as JSON")
    ap.add_argument("--mailto", help="your email, sent to Crossref for its polite pool")
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between lookups (default 1)")
    args = ap.parse_args(argv)

    fetch = fetch or (lambda url: http_get(url, args.mailto))
    with open(args.bib, encoding="utf-8", errors="replace") as fh:
        entries = parse_bib(fh.read())
    if not entries:
        print("No entries found in " + args.bib)
        return 1

    results = []
    for n, entry in enumerate(entries):
        if n and args.delay:
            time.sleep(args.delay)
        results.append(check_entry(entry, fetch))

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            print(f"{r['status']:<10} {r['key']}")
            for p in r["problems"]:
                print(f"           - {p}")
        counts = {s: sum(r["status"] == s for r in results) for s in (VERIFIED, MISMATCH, NOT_FOUND, ERROR)}
        print("\n" + ", ".join(f"{v} {k.lower()}" for k, v in counts.items()))
    if any(r["status"] in (MISMATCH, NOT_FOUND) for r in results):
        return 1
    return 2 if any(r["status"] == ERROR for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
