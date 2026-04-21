"""
OSINT helper: discover a city's municipal website via web search, crawl contact-like pages,
and extract email addresses (visible text / HTML).

Uses polite delays between HTTP requests. Respect site terms of service and robots.txt
in production; this script is for authorized research / pipeline testing only.

Usage:
    python osint_email_scraper.py --city "Indore"
    python osint_email_scraper.py --city "Indore" --base-url "https://www.imcindore.org/"

If Google search returns no URLs (rate limits / blocking), pass --base-url from a manual lookup.

Requires: requests, beautifulsoup4, googlesearch-python (see requirements.txt).
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from pathlib import Path
from typing import Iterable, Set
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# --- Config -----------------------------------------------------------------

OUTPUT_CSV = Path(__file__).resolve().parent / "real_officers_scraped.csv"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

REQUEST_TIMEOUT = 25

# User-specified pattern for visible email-like strings
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

# Homepage links whose URL or anchor text suggest contact / directory pages
LINK_KEYWORDS = (
    "contact",
    "directory",
    "officer",
    "telephone",
    "who is who",
    "whoiswho",
    "who-is-who",
    "whos who",
)

MAX_SEARCH_RESULTS = 6
MAX_CONTACT_PAGES = 12
POLITE_DELAY_SEC = 3.0


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass


def discover_seed_urls(city: str) -> list[str]:
    """Use Google search (via googlesearch-python) to find likely official sites."""
    query = f'{city} Municipal Corporation official website'
    print(f'🔎 Searching for: "{query}" ...')
    try:
        from googlesearch import search
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency: pip install googlesearch-python"
        ) from exc

    urls: list[str] = []
    try:
        gen = search(
            query,
            num_results=MAX_SEARCH_RESULTS,
            lang="en",
            timeout=REQUEST_TIMEOUT,
            sleep_interval=3,
        )
        for u in gen:
            if u and u.startswith(("http://", "https://")):
                urls.append(u.split("#", 1)[0])
    except Exception as exc:
        print(f"⚠️ Search failed ({exc!r}). Try again later or check network / rate limits.")
        raise

    if not urls:
        print("⚠️ No search results returned.")
    return urls


def pick_start_url(urls: list[str]) -> str | None:
    """Prefer Indian government / municipal-looking hosts when possible."""
    if not urls:
        return None
    preferred_substrings = (".gov.in", ".nic.in", "municipal", "nagar", "nigam", "mc.", "ulb")
    for u in urls:
        low = u.lower()
        if any(p in low for p in preferred_substrings):
            return u
    return urls[0]


def fetch_html(session: requests.Session, url: str) -> str | None:
    try:
        r = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        r.raise_for_status()
        ctype = (r.headers.get("Content-Type") or "").lower()
        if "html" not in ctype and "text" not in ctype:
            print(f"   ⏭️ Skipping non-HTML response: {url[:80]}...")
            return None
        return r.text
    except requests.RequestException as exc:
        print(f"   ⚠️ Request failed for {url[:80]}... — {exc}")
        return None


def link_matches_keywords(href: str, link_text: str) -> bool:
    h = (href or "").lower()
    t = (link_text or "").lower()
    blob = f"{h} {t}"
    return any(kw in blob for kw in LINK_KEYWORDS)


def collect_internal_links(base_url: str, html: str) -> Set[str]:
    """Find same-site links that look like contact/directory pages."""
    out: Set[str] = set()
    try:
        base = urlparse(base_url)
        base_origin = f"{base.scheme}://{base.netloc}"
    except Exception:
        return out

    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        raw = a.get("href", "").strip()
        if not raw or raw.startswith(("#", "javascript:", "mailto:")):
            continue
        abs_url = urljoin(base_url, raw)
        p = urlparse(abs_url)
        if p.scheme not in ("http", "https"):
            continue
        if f"{p.scheme}://{p.netloc}" != base_origin:
            continue
        text = a.get_text(" ", strip=True)
        if link_matches_keywords(abs_url, text):
            clean = abs_url.split("#", 1)[0]
            out.add(clean)
    return out


def extract_emails_from_html(html: str) -> Set[str]:
    if not html:
        return set()
    found = set(EMAIL_RE.findall(html))
    # Drop obvious non-emails (very long local parts)
    return {e for e in found if len(e) <= 120}


def append_csv_row(city: str, url: str, emails: Iterable[str]) -> None:
    emails_str = "; ".join(sorted(set(emails)))
    file_exists = OUTPUT_CSV.is_file()
    with OUTPUT_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if not file_exists:
            w.writerow(["City", "URL", "Emails"])
        w.writerow([city, url, emails_str])


def run(city: str, base_url: str | None) -> None:
    _configure_stdout()
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})

    if base_url:
        start = base_url.strip().split("#", 1)[0]
        if not start.startswith(("http://", "https://")):
            print("❌ --base-url must start with http:// or https://")
            return
        print(f"🔗 Using provided base URL (skipping web search): {start}")
    else:
        time.sleep(POLITE_DELAY_SEC)
        seed_urls = discover_seed_urls(city)
        start = pick_start_url(seed_urls)
        if not start:
            print(
                "❌ Could not determine a municipal website URL. "
                "Try again later, or run with --base-url https://official-site.example/ "
                "after manually finding the corporation website."
            )
            return

    print(f"🌐 Selected start URL: {start}")
    time.sleep(POLITE_DELAY_SEC)

    print("📥 Fetching homepage...")
    home_html = fetch_html(session, start)
    if not home_html:
        print("❌ Homepage fetch failed. Exiting.")
        return

    home_emails = extract_emails_from_html(home_html)
    print(f"🔍 Scanning homepage for emails... found {len(home_emails)} unique.")
    append_csv_row(city, start, home_emails)
    print(f"💾 Appended row for homepage → {OUTPUT_CSV.name}")

    contact_urls = collect_internal_links(start, home_html)
    # Deterministic order, cap count
    to_visit = sorted(contact_urls)[:MAX_CONTACT_PAGES]
    print(f"🔗 Found {len(contact_urls)} contact-like internal links; visiting up to {len(to_visit)}.")

    for i, page_url in enumerate(to_visit, start=1):
        time.sleep(POLITE_DELAY_SEC)
        print(f"🔍 Scanning contact page ({i}/{len(to_visit)})... {page_url[:100]}")
        html = fetch_html(session, page_url)
        if not html:
            append_csv_row(city, page_url, [])
            continue
        emails = extract_emails_from_html(html)
        print(f"   ✉️ Extracted {len(emails)} unique email(s).")
        append_csv_row(city, page_url, emails)
        print(f"   💾 Appended row → {OUTPUT_CSV.name}")

    print(f"✅ Done. Results appended to {OUTPUT_CSV.resolve()}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="OSINT: find municipal site for a city and scrape public emails.",
    )
    parser.add_argument(
        "--city",
        required=True,
        help='City name, e.g. "Indore"',
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Optional homepage URL to crawl (skips Google search if set).",
    )
    args = parser.parse_args()
    city = args.city.strip()
    if not city:
        parser.error("--city must be non-empty")
    run(city, args.base_url)


if __name__ == "__main__":
    main()
