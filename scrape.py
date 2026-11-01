# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx", "pandas", "lxml", "beautifulsoup4"]
# ///
"""
Skurubron infrastrukturavgift scraper.

Source: Transportstyrelsen publishes monthly bridge-toll statistics for Skurubron
as HTML tables. The toll was introduced 1 Oct 2023. Completed years have their own
page (statistik-2023/ ... statistik-2025/). The CURRENT year's months are published
MONTHLY (with roughly one month of lag) on the Skurubron landing page itself, before
a dedicated year page exists.

This script fetches each source, parses the three tables (passages, Swedish vehicle
fee decisions, foreign vehicle fee decisions), normalises to one row per month, and
writes:
  - data/skurubron.sqlite   (table: monthly)
  - web/data.json           (consumed by the local web page)

Politeness / freshness (two gates, cheapest first):
  New data appears at most once a month, and with roughly a month of lag.

  Gate 1 - LOCAL, zero network:
    A newer data month than the one we already hold cannot exist until the calendar
    reaches the month AFTER our latest stored data month (data is monthly, in arrears).
    Until then we stop without any network call. Crucially this keys off the latest
    DATA we actually have, not off when we last checked -- so a publication that lands
    mid-month is still picked up on the next run (see the 2 Nov / 5 Nov / 10 Nov case).

  Gate 2 - ONE request:
    Once Gate 1 allows it, we make a single request to the landing page for the latest
    published month and compare it to what is stored. If it is not newer, we stop
    without fetching the per-year pages, and Gate 1 will allow another check next run.

  --force bypasses both gates and rebuilds from scratch.

Usage:
  uv run --quiet --script scrape.py            # fetch only if genuinely needed
  uv run --quiet --script scrape.py --force    # always refetch and rebuild
"""
import io
import json
import sqlite3
import sys
from pathlib import Path

import httpx
import pandas as pd

BASE = ("https://www.transportstyrelsen.se/sv/om-oss/statistik-och-analys/"
        "statistik-inom-vagtrafik/infrastrukturavgift-statistik/skurubron/")

# Toll introduced 1 Oct 2023.
FIRST_YEAR = 2023
# Scan a few years of dedicated pages; the current/most-recent year may only exist
# on the landing page, which is always fetched separately.
SCAN_YEARS = range(FIRST_YEAR, 2029)

ROOT = Path(__file__).parent
DATA = ROOT / "data"
WEB = ROOT / "docs"   # GitHub Pages serves from /docs
DB = DATA / "skurubron.sqlite"

MONTHS = {
    "januari": 1, "februari": 2, "mars": 3, "april": 4, "maj": 5, "juni": 6,
    "juli": 7, "augusti": 8, "september": 9, "oktober": 10,
    "november": 11, "december": 12,
}

HEADERS = {"User-Agent": "skurubron-costtracker/1.0 (personal project; monthly fetch)"}


def num(x):
    """Parse Swedish-formatted number: '1 296 600' -> 1296600, '0,9%' -> 0.9."""
    if x is None:
        return None
    s = str(x).strip().replace("\xa0", " ").replace("%", "")
    s = s.replace(" ", "").replace(",", ".")
    if s in ("", "-", "nan"):
        return None
    try:
        f = float(s)
        return int(f) if f.is_integer() else f
    except ValueError:
        return None


def year_url(year: int) -> str:
    return f"{BASE}statistik-{year}/"


def fetch(url: str) -> str | None:
    try:
        r = httpx.get(url, headers=HEADERS, timeout=30, follow_redirects=True)
        if r.status_code == 200 and "Antal passager" in r.text:
            return r.text
        return None
    except httpx.HTTPError as e:
        print(f"  fetch error {url}: {e}", file=sys.stderr)
        return None


def classify(df: pd.DataFrame) -> str | None:
    cols = " ".join(str(c).lower() for c in df.columns)
    if "antal passager" in cols or "totalt antal passager" in cols:
        return "passages"
    if "avgiftsbeslut" in cols:
        return "fees"
    return None


def detect_year(html: str) -> int | None:
    """The passages heading on a page reads 'Antal passager per månad <YEAR>'."""
    import re
    m = re.search(r"Antal passager per m[åa]nad\s*(\d{4})", html)
    return int(m.group(1)) if m else None


def parse_page(html: str, year: int) -> dict[int, dict]:
    """Return {month_number: {fields...}} for one page, dropping empty months."""
    tables = pd.read_html(io.StringIO(html))
    rows: dict[int, dict] = {}
    fee_tables_seen = 0
    for df in tables:
        df = df.copy()
        kind = classify(df)
        if kind is None:
            continue
        mcol = df.columns[0]
        for _, row in df.iterrows():
            mname = str(row[mcol]).strip().lower()
            if mname not in MONTHS:
                continue
            m = MONTHS[mname]
            rec = rows.setdefault(m, {"year": year, "month": m})
            if kind == "passages":
                rec["passages_total"] = num(row.iloc[1])
                rec["foreign_share_pct"] = num(row.iloc[2]) if df.shape[1] > 2 else None
                rec["passages_chargeable"] = num(row.iloc[3]) if df.shape[1] > 3 else None
            elif kind == "fees":
                origin = "se" if fee_tables_seen == 0 else "foreign"
                rec[f"fee_decisions_{origin}"] = num(row.iloc[1])
                rec[f"fee_amount_{origin}"] = num(row.iloc[2]) if df.shape[1] > 2 else None
        if kind == "fees":
            fee_tables_seen += 1
    # Drop months with no passage and no fee data (pre-toll / not-yet-published).
    return {m: r for m, r in rows.items()
            if r.get("passages_total") or r.get("fee_amount_se")
            or r.get("fee_amount_foreign")}


def ym_add(ym: tuple[int, int], n: int = 1) -> tuple[int, int]:
    """Add n months to a (year, month) pair."""
    idx = (ym[0] * 12 + (ym[1] - 1)) + n
    return (idx // 12, idx % 12 + 1)


def latest_stored() -> tuple[int, int] | None:
    """(year, month) of the newest row already in the DB, or None."""
    if not DB.exists():
        return None
    con = sqlite3.connect(DB)
    try:
        row = con.execute(
            "SELECT year, month FROM monthly ORDER BY year DESC, month DESC LIMIT 1"
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    finally:
        con.close()
    return (row[0], row[1]) if row else None


def latest_available(landing_html: str) -> tuple[int, int] | None:
    """Newest (year, month) published on the landing page (the current year)."""
    year = detect_year(landing_html)
    if year is None:
        return None
    parsed = parse_page(landing_html, year)
    if not parsed:
        return None
    m = max(parsed)
    return (year, m)


def main():
    force = "--force" in sys.argv
    DATA.mkdir(parents=True, exist_ok=True)
    WEB.mkdir(parents=True, exist_ok=True)

    # Gate 1 (local, zero network). Data is published monthly and in arrears, so
    # the newest month whose data could plausibly be out is the month BEFORE the
    # current one (lag is at least ~1 month). If the latest month we already hold
    # is that candidate (or newer), there is nothing to fetch -- stop with no
    # network call. Otherwise we are behind and must check.
    #
    # This keys off the latest DATA we hold, not off when we last checked, so a
    # publication that lands mid-month is picked up on the next run regardless of
    # how many times we checked earlier that month (the 2 Nov / 5 Nov / 10 Nov
    # case). Assuming a 1-month lag errs toward one harmless extra check rather
    # than ever missing data.
    if not force:
        stored0 = latest_stored()
        if stored0 is not None:
            now = pd.Timestamp.now()
            candidate = ym_add((now.year, now.month), -1)  # newest plausibly-published month
            if stored0 >= candidate:
                print(f"Latest stored data is {stored0[0]}-{stored0[1]:02d}; the newest "
                      f"month that could be published is {candidate[0]}-{candidate[1]:02d}. "
                      f"Nothing to fetch. No network call. Use --force to rebuild.")
                return

    # One request first: the landing page carries the current year's monthly data
    # and tells us the newest available month.
    landing = fetch(BASE)
    if landing is None:
        print("Could not reach Transportstyrelsen landing page.", file=sys.stderr)
        sys.exit(1)

    avail = latest_available(landing)
    stored = latest_stored()
    if avail:
        print(f"Latest available: {avail[0]}-{avail[1]:02d}", end="")
        print(f"   stored: {stored[0]}-{stored[1]:02d}" if stored else "   stored: (none)")

    # Freshness gate: stop before fetching per-year pages if we are current.
    if not force and stored and avail and avail <= stored:
        print("Already up to date — skipping network fetch of year pages. "
              "Use --force to rebuild.")
        return

    # Collect: current year from the landing page, prior years from their pages.
    by_year: dict[int, dict[int, dict]] = {}
    landing_year = detect_year(landing)
    if landing_year is not None:
        parsed = parse_page(landing, landing_year)
        if parsed:
            by_year[landing_year] = parsed
            print(f"{landing_year} (landing page): {len(parsed)} months")

    for year in SCAN_YEARS:
        if year in by_year:
            continue  # already have it from the landing page
        html = fetch(year_url(year))
        if html is None:
            print(f"{year}: no dedicated page")
            continue
        parsed = parse_page(html, year)
        if parsed:
            by_year[year] = parsed
            print(f"{year}: {len(parsed)} months")

    all_rows: list[dict] = []
    for year in sorted(by_year):
        for m in sorted(by_year[year]):
            all_rows.append(by_year[year][m])

    if not all_rows:
        print("No data parsed. Aborting.", file=sys.stderr)
        sys.exit(1)

    for r in all_rows:
        se, fo = r.get("fee_amount_se"), r.get("fee_amount_foreign")
        # None (not published yet) must stay None, not become 0 -- a genuine 0 and
        # "not published" are different things for the chart and the KPIs.
        r["fee_amount_total"] = None if (se is None and fo is None) else (se or 0) + (fo or 0)

    # --- SQLite ---
    con = sqlite3.connect(DB)
    con.execute("DROP TABLE IF EXISTS monthly")
    con.execute("""
        CREATE TABLE monthly (
            year INTEGER, month INTEGER,
            passages_total INTEGER, passages_chargeable INTEGER,
            foreign_share_pct REAL,
            fee_decisions_se INTEGER, fee_amount_se INTEGER,
            fee_decisions_foreign INTEGER, fee_amount_foreign INTEGER,
            fee_amount_total INTEGER,
            PRIMARY KEY (year, month)
        )""")
    cols = ["year", "month", "passages_total", "passages_chargeable",
            "foreign_share_pct", "fee_decisions_se", "fee_amount_se",
            "fee_decisions_foreign", "fee_amount_foreign", "fee_amount_total"]
    con.executemany(
        f"INSERT INTO monthly ({','.join(cols)}) VALUES ({','.join('?'*len(cols))})",
        [[r.get(c) for c in cols] for r in all_rows],
    )
    con.commit()
    con.close()

    # --- JSON for the web page ---
    (WEB / "data.json").write_text(
        json.dumps({"updated": pd.Timestamp.now().isoformat(timespec="seconds"),
                    "source": BASE,
                    "latest_month": f"{all_rows[-1]['year']}-{all_rows[-1]['month']:02d}",
                    "months": all_rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    total_pass = sum(r.get("passages_total") or 0 for r in all_rows)
    total_paid = sum(r.get("fee_amount_total") or 0 for r in all_rows)
    print(f"\nWrote {len(all_rows)} months -> {DB} and docs/data.json")
    print(f"Lifetime passages: {total_pass:,}".replace(",", " "))
    print(f"Lifetime paid:     {total_paid:,} kr".replace(",", " "))


if __name__ == "__main__":
    main()
