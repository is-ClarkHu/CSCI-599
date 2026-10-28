"""Rebuild data/medals.csv from Wikipedia (CC BY-SA).

1. Download the series pages and every per-edition page listed in EDITION_PAGES into data/raw_wiki/.
2. Parse each edition's Event/Gold/Silver/Bronze tables (Guts excluded; "Junior" events -> WJUC).
3. Cross-check every page against its own medal table and print any mismatch.

Usage: python -m scripts.fetch_medals
Known benign mismatches: WUGC 2012 and 2016 differ only by Guts teams named "Japan red" / "United States 1".
"""

import csv
import io
import pathlib
import re
from collections import Counter

import httpx
import pandas as pd
from lxml import html

ROOT = pathlib.Path(__file__).resolve().parents[1]
WIKI = ROOT / "data" / "raw_wiki"
OUT = ROOT / "data" / "medals.csv"
SERIES_PAGES = {
    "WUGC": "World_Ultimate_Championships",
    "WBUC": "World_Beach_Ultimate_Championships",
    "WU24": "World_Under-24_Ultimate_Championships",
    "WJUC": "World_Junior_Ultimate_Championships",
    "WORLD_GAMES": "Flying_disc_at_the_World_Games",
}
EDITION_PAGES = {
    "WUGC": {1986: "1986_World_Ultimate_Championships", 1988: "1988_World_Ultimate_Championships",
             1990: "1990_World_Ultimate_Championships", 1994: "1994_World_Ultimate_Championships",
             2000: "2000_World_Ultimate_%26_Guts_Championships", 2008: "2008_World_Ultimate_%26_Guts_Championships",
             2012: "2012_World_Ultimate_%26_Guts_Championships", 2016: "2016_World_Ultimate_%26_Guts_Championships",
             2024: "2024_World_Ultimate_Championships"},
    "WBUC": {2023: "2023_World_Beach_Ultimate_Championships", 2025: "2025_World_Beach_Ultimate_Championships"},
    "WU24": {2013: "2013_World_Under-23_Ultimate_Championships", 2015: "2015_World_Under-23_Ultimate_Championships",
             2018: "2018_World_Under-24_Ultimate_Championships", 2019: "2019_World_Under-24_Ultimate_Championships",
             2023: "2023_World_Under-24_Ultimate_Championships", 2025: "2025_World_Under-24_Ultimate_Championships"},
    "WJUC": {y: f"{y}_World_Junior_Ultimate_Championships"
             for y in (2006, 2010, 2012, 2014, 2016, 2018, 2022, 2024, 2026)},
}


def fetch() -> None:
    (WIKI / "ed").mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": "csci599-a2-medals/1.0 (coursework)"}
    with httpx.Client(follow_redirects=True, timeout=30, headers=headers) as client:
        for series, title in SERIES_PAGES.items():
            (WIKI / f"{series}.html").write_text(client.get(f"https://en.wikipedia.org/wiki/{title}").raise_for_status().text)
        for series, pages in EDITION_PAGES.items():
            for year, title in pages.items():
                response = client.get(f"https://en.wikipedia.org/wiki/{title}").raise_for_status()
                (WIKI / "ed" / f"{series}_{year}.html").write_text(response.text)

NATION_ALIASES = {"United Kingdom": "Great Britain"}
DIVISIONS = {
    "open": "Open", "women's": "Women", "mixed": "Mixed",
    "open masters": "Open Masters", "women's masters": "Women's Masters", "mixed masters": "Mixed Masters",
    "open grand masters": "Open Grand Masters", "women's grand masters": "Women's Grand Masters",
    "mixed grand masters": "Mixed Grand Masters", "open great grand masters": "Open Great Grand Masters",
    "junior": "Open",
}


def clean(text) -> str:
    text = re.sub(r"\[\w+\]", "", str(text)).replace("*", "").strip()
    text = re.sub(r"\s*\([A-Z]{3}\)$", "", text)
    return NATION_ALIASES.get(text, text)


def editions(series: str) -> dict[int, tuple[str, str]]:
    table = pd.read_html(io.StringIO((WIKI / f"{series}.html").read_text()))[1]
    out = {}
    for _, row in table.iterrows():
        host = clean(row["Host"])
        if not str(row["Year"]).isdigit() or "Cancelled" in host or host == "nan":
            continue
        parts = [p.strip() for p in host.split(",")]
        out[int(row["Year"])] = (", ".join(parts[:-1]) or parts[0], parts[-1] if len(parts) > 1 else "")
    return out


def canonical_url(doc) -> str:
    return doc.xpath("//link[@rel='canonical']/@href")[0]


fetch()
EDITIONS = {s: editions(s) for s in ("WUGC", "WBUC", "WU24", "WJUC")}
rows: list[dict] = []
problems: list[str] = []

for page in sorted((WIKI / "ed").glob("*.html")):
    series, year = page.stem.split("_")[0], int(page.stem.split("_")[1])
    text = page.read_text()
    doc = html.fromstring(text)
    url = canonical_url(doc)
    tables = doc.xpath("//table[contains(@class,'wikitable')]")
    page_counts: Counter = Counter()
    medal_table = None
    for table in tables:
        frame = pd.read_html(io.StringIO(html.tostring(table, encoding="unicode")))[0]
        heading = "".join(table.xpath("preceding::*[self::h2 or self::h3 or self::h4][1]//text()")).strip().lower()
        cols = [str(c) for c in frame.columns]
        if "Rank" in cols and "Gold" in cols:
            medal_table = frame
            continue
        if cols[:4] != ["Event", "Gold", "Silver", "Bronze"]:
            continue
        for _, row in frame.iterrows():
            event = clean(row["Event"]).lower()
            medalists = [clean(row[c]) for c in ("Gold", "Silver", "Bronze")]
            page_counts.update({(m, i): 1 for i, m in enumerate(medalists)})
            if event == "guts":
                continue
            is_junior = heading == "junior" or event == "junior"
            target = "WJUC" if is_junior else series
            if event not in DIVISIONS:
                problems.append(f"{page.stem}: unknown event {event!r}")
                continue
            city, host = EDITIONS[series].get(year, ("", ""))
            for place, team in enumerate(medalists, start=1):
                rows.append({"series": target, "year": year, "city": city, "host_country": NATION_ALIASES.get(host, host),
                             "division": DIVISIONS[event], "place": place, "team": team, "team_country": team,
                             "source_url": url})
    # Cross-check: per-nation gold/silver/bronze counts must equal the page's own medal table.
    if medal_table is not None:
        for _, row in medal_table.iterrows():
            nation = clean(row["Nation"])
            if nation.startswith("Totals"):
                continue
            expected = tuple(int(row[c]) for c in ("Gold", "Silver", "Bronze"))
            got = tuple(page_counts[(nation, i)] for i in range(3))
            if expected != got:
                problems.append(f"{page.stem}: {nation} medal table {expected} != events {got}")
    else:
        problems.append(f"{page.stem}: no medal table to cross-check")

# World Games (mixed division only), from the series page table 0.
wg_doc = html.fromstring((WIKI / "WORLD_GAMES.html").read_text())
wg = pd.read_html(io.StringIO((WIKI / "WORLD_GAMES.html").read_text()))[0]
for _, row in wg.iterrows():
    year, city = str(row["Games"]).split(" ", 1)
    for place, col in enumerate(("Gold", "Silver", "Bronze"), start=1):
        team = clean(row[col])
        rows.append({"series": "WORLD_GAMES", "year": int(year), "city": city, "host_country": "",
                     "division": "Mixed", "place": place, "team": team, "team_country": team,
                     "source_url": canonical_url(wg_doc)})

rows.sort(key=lambda r: (r["series"], r["year"], r["division"], r["place"]))
keys = [(r["series"], r["year"], r["division"], r["place"]) for r in rows]
dupes = [k for k, n in Counter(keys).items() if n > 1]
OUT.parent.mkdir(parents=True, exist_ok=True)
with OUT.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)

print(f"rows={len(rows)} duplicates={dupes}")
print(Counter(r["series"] for r in rows))
print(sorted(Counter(r["division"] for r in rows).items()))
print("problems:", *problems, sep="\n  ")
