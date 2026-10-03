#!/usr/bin/env python3
"""Read GMS news (patch notes, events, sales) from Nexon's CMS feed as plain text.

nexon.com/maplestory pages are rendered by JavaScript, so a plain fetch returns only the page title. The
same posts are served as JSON by g.nexonstatic.com, which this script reads.

  python3 nexon_news.py list [--grep "v.27|event"] [--category update|events|sale|maintenance|general] [--limit 40]
  python3 nexon_news.py get 44597 [--grep "Sunny Sunday"] [--context 40]
"""

import argparse
import html
import json
import re
import sys
import urllib.request

FEED = "https://g.nexonstatic.com/maplestory/cms/v1/news"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def to_text(body):
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", body, flags=re.S)
    body = re.sub(r"<br\s*/?>", "\n", body)
    body = re.sub(r"</(p|div|li|tr|h\d|table)>", "\n", body)
    body = re.sub(r"<t[dh][^>]*>", " | ", body)
    body = re.sub(r"<li[^>]*>", "- ", body)
    body = re.sub(r"<[^>]+>", "", body)
    body = html.unescape(body)
    body = re.sub(r"[ \t\xa0]+", " ", body)
    return re.sub(r"\n\s*\n+", "\n", body).strip()


def cmd_list(a):
    posts = fetch(FEED)
    pat = re.compile(a.grep, re.I) if a.grep else None
    shown = 0
    for p in posts:
        if a.category and p.get("category") != a.category:
            continue
        if pat and not pat.search(p.get("name", "")):
            continue
        print(f"{p['liveDate'][:10]}  {p['id']:>6}  {p.get('category', ''):<11}  {p['name']}")
        shown += 1
        if shown >= a.limit:
            break


def cmd_get(a):
    post = fetch(f"{FEED}/{a.id}")
    text = to_text(post.get("body", ""))
    print(f"# {post.get('name')}  ({post.get('liveDate', '')[:10]}, id {a.id})")
    print(f"# https://www.nexon.com/maplestory/news/{post.get('category', 'all')}/{a.id}\n")
    if not a.grep:
        print(text)
        return
    lines = text.splitlines()
    pat = re.compile(a.grep, re.I)
    hits = [i for i, line in enumerate(lines) if pat.search(line)]
    if not hits:
        sys.exit(f"No lines match '{a.grep}'")
    printed = -1
    for i in hits:
        start, end = max(i, printed + 1), min(len(lines), i + a.context)
        if start >= end:
            continue
        print(f"--- line {start}")
        print("\n".join(lines[start:end]))
        printed = end - 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("list", help="list recent posts")
    pl.add_argument("--grep")
    pl.add_argument("--category")
    pl.add_argument("--limit", type=int, default=40)
    pg = sub.add_parser("get", help="print one post as text")
    pg.add_argument("id")
    pg.add_argument("--grep", help="only print sections starting at matching lines")
    pg.add_argument("--context", type=int, default=40, help="lines to print after each match")
    a = ap.parse_args()
    cmd_list(a) if a.cmd == "list" else cmd_get(a)


if __name__ == "__main__":
    main()
