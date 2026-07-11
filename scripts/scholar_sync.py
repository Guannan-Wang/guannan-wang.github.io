#!/usr/bin/env python3
"""Update _data/scholar.yml with Google Scholar citation metrics.

Zero external dependencies (Python 3.8+ standard library only).

Two fetch backends, tried in order:
  1. SerpApi  — used when the SERPAPI_KEY environment variable is set
     (reliable from CI; free tier ~100 searches/mo). This is the "one-line"
     upgrade the design spec mentions.
  2. Public profile scrape — no key, but Google may block datacenter IPs.

Safety (per design spec section 6):
  * Never blanks the file: if the fetch fails OR returns implausible values,
    the existing _data/scholar.yml is left untouched and the script exits 0
    (so the weekly workflow never fails and never wipes the hero strip).
  * The workflow commits only when the file actually changes.

Usage:
    python scripts/scholar_sync.py [SCHOLAR_USER_ID]
Default user id is read from _config.yml's author.googlescholar, else the
GUANNAN id below.
"""

import json
import os
import re
import sys
import urllib.request
from datetime import date, timezone, datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO_ROOT, "_data", "scholar.yml")
DEFAULT_USER = "ZJqzi60AAAAJ"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def user_id_from_config():
    cfg = os.path.join(REPO_ROOT, "_config.yml")
    try:
        with open(cfg, encoding="utf-8") as f:
            m = re.search(r"googlescholar\s*:\s*\"?[^\"\n]*user=([A-Za-z0-9_-]+)", f.read())
            if m:
                return m.group(1)
    except OSError:
        pass
    return DEFAULT_USER


def fetch_serpapi(user, key):
    url = ("https://serpapi.com/search.json?engine=google_scholar_author"
           "&author_id=%s&api_key=%s" % (user, key))
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    table = data.get("cited_by", {}).get("table", [])
    vals = {}
    for row in table:
        for k, v in row.items():
            vals[k] = v.get("all")
    return {
        "citations": vals.get("citations"),
        "h_index": vals.get("h_index"),
        "i10_index": vals.get("i10_index"),
    }


def fetch_scrape(user):
    url = "https://scholar.google.com/citations?user=%s&hl=en" % user
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode("utf-8", "replace")
    # The stats table lists, in order: citations(all), citations(recent),
    # h-index(all), h-index(recent), i10(all), i10(recent).
    nums = re.findall(r'gsc_rsb_std">(\d+)', html)
    if len(nums) < 6:
        raise ValueError("could not parse metrics table (blocked or layout change)")
    return {
        "citations": int(nums[0]),
        "h_index": int(nums[2]),
        "i10_index": int(nums[4]),
    }


def plausible(m):
    try:
        c, h, i = int(m["citations"]), int(m["h_index"]), int(m["i10_index"])
    except (TypeError, ValueError, KeyError):
        return False
    # Metrics only grow; guard against a garbage/zero fetch blanking the strip.
    return c > 0 and 0 <= h <= 500 and 0 <= i <= 5000 and h <= c


def write(m):
    today = datetime.now(timezone.utc).date().isoformat()
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write(
            "# Citation metrics shown in the homepage hero strip.\n"
            "# Auto-updated weekly by scripts/scholar_sync.py "
            "(.github/workflows/scholar.yml).\n"
            "# Last-good values are cached: a blocked fetch never blanks these.\n"
            "citations: %d\n" % int(m["citations"])
            + "h_index: %d\n" % int(m["h_index"])
            + "i10_index: %d\n" % int(m["i10_index"])
            + 'updated: "%s"\n' % today
        )


def main():
    user = sys.argv[1] if len(sys.argv) > 1 else user_id_from_config()
    key = os.environ.get("SERPAPI_KEY", "").strip()
    backends = []
    if key:
        backends.append(("serpapi", lambda: fetch_serpapi(user, key)))
    backends.append(("scrape", lambda: fetch_scrape(user)))
    metrics = None
    for name, fn in backends:
        try:
            metrics = fn()
            if plausible(metrics):
                print("Fetched via %s: %s" % (name, metrics))
                break
            print("%s returned implausible values: %s" % (name, metrics))
            metrics = None
        except Exception as e:  # noqa: BLE001 — any failure must be non-fatal
            print("%s fetch failed: %s" % (name, e))
            metrics = None
    if metrics is None:
        print("No good fetch; keeping cached _data/scholar.yml unchanged.")
        return 0
    write(metrics)
    print("Wrote %s" % OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
