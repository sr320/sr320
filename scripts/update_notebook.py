#!/usr/bin/env python3
"""
Refresh the "From the notebook" block in a GitHub profile README.

Reads the Tumbling Oysters RSS feed and rewrites the region between the
NOTEBOOK markers with the newest posts. No third-party dependencies.

The lab notebook is a Quarto site, so its feed is plain RSS 2.0 with the post
body in <description> as HTML. Only the first real paragraph is used as a
blurb; the body opens with an AI-use badge and a section heading that would
otherwise lead every entry.

Usage:
    python scripts/update_notebook.py
    python scripts/update_notebook.py --demo    # synthetic posts, no network
"""

import html
import os
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

FEED_URL = os.environ.get(
    "FEED_URL", "https://sr320.github.io/tumbling-oysters/index.xml"
)
COUNT = int(os.environ.get("NOTEBOOK_COUNT", "3"))
BLURB_CHARS = int(os.environ.get("BLURB_CHARS", "150"))
README = os.environ.get("README", "README.md")

START, END = "<!-- NOTEBOOK:START -->", "<!-- NOTEBOOK:END -->"


# --------------------------------------------------------------------------
# data
# --------------------------------------------------------------------------

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "profile-notebook/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return ET.fromstring(resp.read())


def clean(text, keep_emphasis=False):
    """Strip tags and tidy the spaces left where inline markup used to be."""
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    if keep_emphasis:
        # Posts italicize species binomials, so flattening <em> would turn
        # "Ostrea chilensis" into plain text. Carry it over as markdown.
        text = re.sub(r"(?is)<(?:em|i)\b[^>]*>(.*?)</(?:em|i)>", r"*\1*", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"\s+\)", ")", text)
    return text.strip()


def blurb(description):
    """First paragraph with real prose in it, truncated on a word boundary."""
    for raw in re.findall(r"(?is)<p\b[^>]*>(.*?)</p>", description):
        text = clean(raw, keep_emphasis=True)
        if len(text) < 60:
            continue  # badge row, figure caption, or similar
        if len(text) <= BLURB_CHARS:
            return text
        cut = text[:BLURB_CHARS].rsplit(" ", 1)[0].rstrip(" ,;:.—-")
        if cut.count("*") % 2:
            cut += "*"  # truncated mid-italic; close it or the markdown leaks
        return cut + "…"
    return ""


def parse(root):
    channel = root.find("channel")
    if channel is None:
        raise RuntimeError("feed has no <channel>")

    posts = []
    for item in channel.findall("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        try:
            when = parsedate_to_datetime(item.findtext("pubDate") or "")
        except (TypeError, ValueError):
            when = None
        posts.append(
            {
                "title": clean(title),
                "link": link,
                "when": when,
                "blurb": blurb(item.findtext("description") or ""),
                "tags": [c.text.strip() for c in item.findall("category") if c.text],
            }
        )

    if not posts:
        raise RuntimeError("feed carried no usable items")
    return posts


def demo_posts():
    now = datetime.now(timezone.utc)
    return [
        {
            "title": "62 CpGs Separate Quihua From Rio Pudeto",
            "link": "https://example.invalid/posts/86",
            "when": now,
            "blurb": "Whether the whole-genome bisulfite data actually says anything "
                     "about population structure…",
            "tags": ["Epigenetics", "Genomics"],
        },
        {
            "title": "Three Ostrea chilensis Assemblies Walk Into a Dot Plot",
            "link": "https://example.invalid/posts/85",
            "when": now,
            "blurb": "There are three genome files floating around this project, and "
                     "they disagree…",
            "tags": ["Genomics"],
        },
    ]


# --------------------------------------------------------------------------
# readme block
# --------------------------------------------------------------------------

def render(posts):
    # The heading and lead-in live in README.md as static prose; this block is
    # only ever the post list, so rewriting it cannot clobber hand-written text.
    lines = [START, ""]
    for post in posts:
        # Two trailing spaces are a hard break; without them GitHub runs the
        # title, blurb, and byline together into one paragraph.
        lines.append(f"**[{post['title']}]({post['link']})**  ")
        if post["blurb"]:
            lines.append(f"{post['blurb']}  ")

        meta = []
        if post["when"]:
            meta.append(post["when"].strftime("%b %-d, %Y"))
        meta.extend(post["tags"][:2])
        lines.append(f"<sub>{' · '.join(meta)}</sub>" if meta else "<sub></sub>")
        lines.append("")

    lines.append("<sub>Latest from [Tumbling Oysters](https://sr320.github.io/tumbling-oysters/)"
                 " · refreshed daily by GitHub Actions</sub>")
    lines.append(END)
    return "\n".join(lines)


def update_readme(posts, path=README):
    if not os.path.exists(path):
        print(f"{path} not found", file=sys.stderr)
        return False
    text = open(path, encoding="utf-8").read()
    if START not in text or END not in text:
        print(f"{path} has no NOTEBOOK markers, nothing to update", file=sys.stderr)
        return False

    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    open(path, "w", encoding="utf-8").write(head + render(posts) + tail)
    return True


def main():
    if "--demo" in sys.argv:
        posts = demo_posts()
    else:
        try:
            posts = parse(fetch(FEED_URL))[:COUNT]
        except (urllib.error.URLError, ET.ParseError, RuntimeError,
                ValueError, TimeoutError) as exc:
            # Leave the last good block in place rather than blanking it.
            print(f"feed unavailable ({exc}), notebook block left unchanged",
                  file=sys.stderr)
            return 0

    if not update_readme(posts):
        return 0

    print(f"{README}: {len(posts)} post(s), newest {posts[0]['title']!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
