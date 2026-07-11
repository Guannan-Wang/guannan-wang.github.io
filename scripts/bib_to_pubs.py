#!/usr/bin/env python3
"""Convert a BibTeX file into _publications/<slug>.md entries.

Zero external dependencies (Python 3.8+ standard library only), so it runs
unchanged locally (via the `py` launcher on Windows) or inside a Codespace.

Usage:
    py scripts/bib_to_pubs.py [references.bib] [--dry-run]

Behavior (see design spec section 4):
  * One markdown file per BibTeX entry, slug derived from the cite key.
  * `type` guessed from the entry type (article -> journal, inproceedings ->
    conference, preprints detected from venue text).
  * Merge-by-slug: re-running NEVER overwrites hand-curated fields
    (`thumbnail`, `selected`, `award`, and `links.code`). Everything else is
    regenerated from the BibTeX (which is the source of truth for it).
  * The raw BibTeX entry is embedded as the `bibtex:` field for the Cite button.

Review the diff, then commit.
"""

import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUB_DIR = os.path.join(REPO_ROOT, "_publications")

# Fields the converter must never clobber on re-run (curated by hand).
PROTECTED_TOP = ("thumbnail", "selected", "award")
PROTECTED_LINKS = ("code",)

MONTHS = {
    "jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05",
    "jun": "06", "jul": "07", "aug": "08", "sep": "09", "oct": "10",
    "nov": "11", "dec": "12",
}


# --------------------------------------------------------------------------
# BibTeX parsing (small hand-rolled scanner; handles balanced {} and "..." )
# --------------------------------------------------------------------------

def parse_bibtex(text):
    entries = []
    i, n = 0, len(text)
    while i < n:
        if text[i] != "@":
            i += 1
            continue
        m = re.match(r"@(\w+)\s*\{", text[i:])
        if not m:
            i += 1
            continue
        etype = m.group(1).lower()
        if etype in ("comment", "preamble", "string"):
            i += 1
            continue
        i += m.end()
        # cite key up to first comma
        key_end = text.find(",", i)
        brace_end = text.find("}", i)
        if key_end == -1 or (brace_end != -1 and brace_end < key_end):
            # entry with no fields
            key = text[i:brace_end].strip()
            entries.append({"_type": etype, "_key": key})
            i = brace_end + 1
            continue
        key = text[i:key_end].strip()
        i = key_end + 1
        fields = {"_type": etype, "_key": key}
        # parse "name = value" pairs until the closing brace of the entry
        while i < n:
            # skip whitespace/commas
            while i < n and text[i] in " \t\r\n,":
                i += 1
            if i < n and text[i] == "}":
                i += 1
                break
            fm = re.match(r"([A-Za-z][\w\-]*)\s*=\s*", text[i:])
            if not fm:
                # malformed; bail to next '@'
                nxt = text.find("@", i)
                i = nxt if nxt != -1 else n
                break
            fname = fm.group(1).lower()
            i += fm.end()
            value, i = _read_value(text, i, n)
            fields[fname] = _clean_value(value)
        entries.append(fields)
    return entries


def _read_value(text, i, n):
    if i >= n:
        return "", i
    ch = text[i]
    if ch == "{":
        depth, start = 0, i
        while i < n:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    return text[start + 1:i], i + 1
            i += 1
        return text[start + 1:], n
    if ch == '"':
        start = i + 1
        i += 1
        while i < n:
            if text[i] == '"':
                return text[start:i], i + 1
            i += 1
        return text[start:], n
    # bareword (number or macro) up to comma/brace
    start = i
    while i < n and text[i] not in ",}\r\n":
        i += 1
    return text[start:i].strip(), i


def _clean_value(v):
    v = re.sub(r"\s+", " ", v)
    v = v.replace("{", "").replace("}", "").strip()
    return v


# --------------------------------------------------------------------------
# Field derivation
# --------------------------------------------------------------------------

def slugify(s):
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def guess_type(entry):
    et = entry.get("_type", "")
    venue = (entry.get("journal", "") + " " +
             entry.get("archiveprefix", "") + " " +
             entry.get("eprint", "")).lower()
    if any(k in venue for k in ("arxiv", "biorxiv", "medrxiv", "preprint", "ssrn", "researchsquare")):
        return "preprint"
    if et in ("inproceedings", "conference", "proceedings"):
        return "conference"
    if et in ("unpublished",):
        return "preprint"
    if et in ("article", "misc", "techreport", "incollection", "book", "phdthesis", "mastersthesis"):
        return "journal"
    return "journal"


def format_authors(raw):
    if not raw:
        return ""
    people = [p.strip() for p in re.split(r"\s+and\s+", raw) if p.strip()]
    out = []
    for p in people:
        if "," in p:
            last, first = [x.strip() for x in p.split(",", 1)]
            out.append((first + " " + last).strip())
        else:
            out.append(p)
    return ", ".join(out)


def derive_date(entry):
    year = entry.get("year", "").strip()
    month = entry.get("month", "").strip().lower()[:3]
    if not re.match(r"^\d{4}$", year):
        year = "1900"
    mm = MONTHS.get(month, "01")
    return "%s-%s-01" % (year, mm)


def derive_links(entry):
    links = {}
    doi = entry.get("doi", "").strip()
    if doi:
        if doi.startswith("http"):
            links["doi"] = doi
        else:
            links["doi"] = "https://doi.org/" + doi
    ap = entry.get("archiveprefix", "").lower()
    eprint = entry.get("eprint", "").strip()
    if "arxiv" in ap and eprint:
        links["arxiv"] = "https://arxiv.org/abs/" + eprint
    url = entry.get("url", "").strip()
    if url and "doi" not in links and "arxiv" not in links:
        links["pdf"] = url
    return links


def reserialize_bibtex(entry):
    """Emit a clean, stable BibTeX entry for the Cite button."""
    order = ["title", "author", "journal", "booktitle", "volume", "number",
             "pages", "year", "publisher", "doi"]
    lines = ["@%s{%s," % (entry.get("_type", "article"), entry.get("_key", "ref"))]
    keys = [k for k in order if k in entry]
    keys += [k for k in entry if not k.startswith("_") and k not in order and k in ("eprint", "archiveprefix")]
    for k in keys:
        lines.append("  %-9s = {%s}," % (k, entry[k]))
    if lines[-1].endswith(","):
        lines[-1] = lines[-1][:-1]
    lines.append("}")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Front-matter read/merge/write
# --------------------------------------------------------------------------

def yaml_quote(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def read_existing(path):
    """Return the curated fields to preserve from an existing entry, if any."""
    preserved = {"top": {}, "links": {}}
    if not os.path.exists(path):
        return preserved
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return preserved
    fm = m.group(1)
    for key in PROTECTED_TOP:
        km = re.search(r"^%s\s*:\s*(.+)$" % re.escape(key), fm, re.MULTILINE)
        if km:
            preserved["top"][key] = km.group(1).strip()
    lm = re.search(r"^links:\s*\n((?:[ \t]+.+\n?)*)", fm, re.MULTILINE)
    if lm:
        for key in PROTECTED_LINKS:
            km = re.search(r"^\s+%s\s*:\s*(.+)$" % re.escape(key), lm.group(1), re.MULTILINE)
            if km:
                preserved["links"][key] = km.group(1).strip()
    return preserved


def build_markdown(entry, preserved):
    title = entry.get("title", "Untitled")
    ptype = guess_type(entry)
    date = derive_date(entry)
    venue = entry.get("journal") or entry.get("booktitle") or entry.get("publisher") or ""
    authors = format_authors(entry.get("author", ""))
    links = derive_links(entry)
    # merge preserved curated links (e.g. code) over derived
    for k, v in preserved["links"].items():
        links[k] = v.strip().strip('"')

    lines = ["---"]
    lines.append("title: " + yaml_quote(title))
    lines.append("type: " + ptype)
    lines.append("date: " + date)
    lines.append("venue: " + yaml_quote(venue))
    lines.append("authors: " + yaml_quote(authors))
    # selected (curated; default false)
    lines.append("selected: " + preserved["top"].get("selected", "false"))
    if "award" in preserved["top"]:
        lines.append("award: " + preserved["top"]["award"])
    if "thumbnail" in preserved["top"]:
        lines.append("thumbnail: " + preserved["top"]["thumbnail"])
    if links:
        lines.append("links:")
        for k in ("pdf", "doi", "arxiv", "code", "bibtex"):
            if k in links:
                lines.append("  %s: %s" % (k, links[k]))
    lines.append("bibtex: |")
    for bl in reserialize_bibtex(entry).splitlines():
        lines.append("  " + bl)
    lines.append("---")
    lines.append("")
    return "\n".join(lines) + "\n"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in sys.argv
    bib_path = args[0] if args else os.path.join(REPO_ROOT, "references.bib")
    if not os.path.exists(bib_path):
        print("ERROR: BibTeX file not found: %s" % bib_path)
        return 1
    with open(bib_path, "r", encoding="utf-8") as f:
        entries = parse_bibtex(f.read())
    if not entries:
        print("No entries parsed from %s" % bib_path)
        return 1
    os.makedirs(PUB_DIR, exist_ok=True)
    created, updated = 0, 0
    for e in entries:
        key = e.get("_key") or slugify(e.get("title", "ref"))
        slug = slugify(key)
        path = os.path.join(PUB_DIR, slug + ".md")
        existed = os.path.exists(path)
        preserved = read_existing(path)
        md = build_markdown(e, preserved)
        if dry:
            print("[dry-run] %s %s" % ("update" if existed else "create", slug + ".md"))
        else:
            with open(path, "w", encoding="utf-8", newline="\n") as out:
                out.write(md)
        if existed:
            updated += 1
        else:
            created += 1
    print("Done: %d created, %d updated (%d entries)." % (created, updated, len(entries)))
    print("Review the diff, then commit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
